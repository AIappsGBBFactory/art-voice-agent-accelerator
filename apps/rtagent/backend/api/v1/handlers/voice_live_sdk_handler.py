"""VoiceLive SDK handler bridging ACS media streams to multi-agent orchestration."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any, Awaitable, Dict, Literal, Optional, Union

import numpy as np
from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
	ServerEventType, 
	ResponseStatus,
	ClientEventConversationItemCreate,
	ClientEventResponseCreate,
	UserMessageItem,
	InputTextContentPart,
)
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity.aio import DefaultAzureCredential

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from utils.ml_logging import get_logger
from apps.rtagent.backend.src.agents.vlagent.settings import get_settings
from apps.rtagent.backend.src.agents.vlagent.registry import load_registry, HANDOFF_MAP
from apps.rtagent.backend.src.agents.vlagent.orchestrator import LiveOrchestrator
from apps.rtagent.backend.src.agents.vlagent.session_loader import load_user_profile_by_email
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
	send_session_envelope,
	send_user_transcript,
	_set_connection_metadata,
)
from apps.rtagent.backend.src.ws_helpers.envelopes import (
	make_envelope,
	make_assistant_streaming_envelope,
)
from apps.rtagent.backend.src.agents.vlagent.tool_store.tools_helper import (
	push_tool_start,
	push_tool_end,
)

logger = get_logger("api.v1.handlers.voice_live_sdk_handler")
tracer = trace.get_tracer(__name__)

_TRACED_EVENTS = {
	ServerEventType.ERROR.value,
	ServerEventType.RESPONSE_CREATED.value,
	ServerEventType.RESPONSE_DONE.value,
	ServerEventType.RESPONSE_AUDIO_DONE.value,
	ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED.value,
	ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA.value,
	ServerEventType.SESSION_UPDATED.value,
	ServerEventType.SESSION_CREATED.value,
	ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED.value,
	ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED.value,
}

_DTMF_FLUSH_DELAY_SECONDS = 1.5

_AGENT_LABELS = {
	"PayPalAgent": "PayPal Specialist",
	"FraudAgent": "Fraud Specialist",
	"ComplianceDesk": "Compliance Specialist",
	"AuthAgent": "Auth Agent",
	"TransferAgency": "Transfer Agency Specialist",
	"TradingDesk": "Trading Specialist",
	"EricaConcierge": "Erica",
	"CardRecommendation": "Card Specialist",
	"InvestmentAdvisor": "Investment Advisor",
}


def _resolve_agent_label(agent_name: Optional[str]) -> Optional[str]:
	if not agent_name:
		return None
	return _AGENT_LABELS.get(agent_name, agent_name)


def _safe_primitive(value: Any) -> Any:
	if value is None or isinstance(value, (str, int, float, bool)):
		return value
	if isinstance(value, (list, tuple)):
		return [_safe_primitive(v) for v in value]
	if isinstance(value, dict):
		return {k: _safe_primitive(v) for k, v in value.items()}
	return str(value)


def _background_task(coro: Awaitable[Any], *, label: str) -> None:
	task = asyncio.create_task(coro)

	def _log_outcome(t: asyncio.Task) -> None:
		try:
			t.result()
		except Exception:
			logger.debug("Background task '%s' failed", label, exc_info=True)

	task.add_done_callback(_log_outcome)


def _serialize_session_config(session_obj: Any) -> Optional[Dict[str, Any]]:
	if not session_obj:
		return None

	for attr in ("model_dump", "to_dict", "as_dict", "dict"):
		method = getattr(session_obj, attr, None)
		if callable(method):
			try:
				data = method()
				if isinstance(data, dict):
					return data
			except Exception:
				logger.debug("Failed to serialize session via %s", attr, exc_info=True)

	serializer = getattr(session_obj, "serialize", None) or getattr(session_obj, "to_json", None)
	if callable(serializer):
		try:
			data = serializer()
			if isinstance(data, str):
				return json.loads(data)
			if isinstance(data, dict):
				return data
		except Exception:
			logger.debug("Failed to serialize session via serializer", exc_info=True)

	try:
		raw = vars(session_obj)
	except Exception:
		return None

	return {k: _safe_primitive(v) for k, v in raw.items()}


class _SessionMessenger:
	"""Bridge VoiceLive events to the session-aware WebSocket manager."""

	def __init__(self, websocket: WebSocket) -> None:
		self._ws = websocket
		self._default_sender: Optional[str] = None
		self._missing_session_warned = False
		self._active_turn_id: Optional[str] = None
		self._pending_user_turn_id: Optional[str] = None

	def _ensure_turn_id(self, candidate: Optional[str], *, allow_generate: bool = True) -> Optional[str]:
		if candidate:
			self._active_turn_id = candidate
			return candidate
		if self._active_turn_id:
			return self._active_turn_id
		if not allow_generate:
			return None
		generated = uuid.uuid4().hex
		self._active_turn_id = generated
		return generated

	def _release_turn(self, turn_id: Optional[str]) -> None:
		if turn_id and self._active_turn_id == turn_id:
			self._active_turn_id = None
		elif turn_id is None:
			self._active_turn_id = None

	def begin_user_turn(self, turn_id: Optional[str]) -> Optional[str]:
		"""Initialise a user turn and emit a placeholder streaming message."""
		if not turn_id:
			self._pending_user_turn_id = None
			return None
		if self._pending_user_turn_id == turn_id:
			return turn_id
		self._pending_user_turn_id = turn_id
		if not self._can_emit():
			return turn_id

		payload: Dict[str, Any] = {
			"type": "user",
			"message": "",
			"content": "",
			"streaming": True,
			"turn_id": turn_id,
			"response_id": turn_id,
			"status": "streaming",
		}
		envelope = make_envelope(
			etype="event",
			sender="User",
			payload=payload,
			topic="session",
			session_id=self._session_id,
			call_id=self._call_id,
		)

		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label="voicelive_user_turn_started",
				broadcast_only=True,
			),
			label="user_turn_started",
		)
		return turn_id

	def resolve_user_turn_id(self, candidate: Optional[str]) -> Optional[str]:
		"""Ensure user turn IDs remain consistent across delta and final events."""
		if candidate:
			self._pending_user_turn_id = candidate
			return candidate
		return self._pending_user_turn_id

	def finish_user_turn(self, turn_id: Optional[str]) -> None:
		resolved = turn_id or self._pending_user_turn_id
		if resolved and self._pending_user_turn_id == resolved:
			self._pending_user_turn_id = None

	def set_active_agent(self, agent_name: Optional[str]) -> None:
		"""Update the default sender name used for assistant/system envelopes."""
		self._default_sender = _resolve_agent_label(agent_name) or agent_name or None

	@property
	def _session_id(self) -> Optional[str]:
		return getattr(self._ws.state, "session_id", None)

	@property
	def _call_id(self) -> Optional[str]:
		return getattr(self._ws.state, "call_connection_id", None)

	@property
	def session_id(self) -> Optional[str]:
		return self._session_id

	@property
	def call_id(self) -> Optional[str]:
		return self._call_id

	def _can_emit(self) -> bool:
		if self._session_id:
			self._missing_session_warned = False
			return True

		if not self._missing_session_warned:
			logger.warning(
				"[VoiceLive] Unable to emit envelope - websocket missing session_id (call=%s)",
				self._call_id,
			)
			self._missing_session_warned = True
		return False

	async def send_user_message(self, text: str, *, turn_id: Optional[str] = None) -> None:
		"""Forward a user transcript to all session listeners."""
		if not text or not self._can_emit():
			return

		_background_task(
			send_user_transcript(
				self._ws,
				text,
				session_id=self._session_id,
				conn_id=None,
				broadcast_only=True,
				turn_id=turn_id,
			),
			label="send_user_transcript",
		)

	def _resolve_sender(self, sender: Optional[str]) -> str:
		return _resolve_agent_label(sender) or self._default_sender or "Assistant"

	async def send_assistant_message(
		self,
		text: str,
		*,
		sender: Optional[str] = None,
		response_id: Optional[str] = None,
		status: Optional[str] = None,
	) -> None:
		"""Emit assistant transcript chunks to the frontend chat UI."""
		if not self._can_emit():
			return

		turn_id = self._ensure_turn_id(response_id)
		if not turn_id:
			return

		message_text = text or ""
		sender_name = self._resolve_sender(sender)
		payload = {
			"type": "assistant",
			"message": message_text,
			"content": message_text,
			"streaming": False,
			"turn_id": turn_id,
			"response_id": response_id or turn_id,
			"status": status or "completed",
		}
		envelope = make_envelope(
			etype="event",
			sender=sender_name,
			payload=payload,
			topic="session",
			session_id=self._session_id,
			call_id=self._call_id,
		)

		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label="voicelive_assistant_transcript",
				broadcast_only=True,
			),
			label="assistant_transcript_envelope",
		)
		self._release_turn(turn_id)

	async def send_assistant_streaming(
		self,
		text: str,
		*,
		sender: Optional[str] = None,
		response_id: Optional[str] = None,
	) -> None:
		"""Emit assistant streaming deltas for progressive rendering."""
		if not text or not self._can_emit():
			return

		turn_id = self._ensure_turn_id(response_id)
		if not turn_id:
			return

		sender_name = self._resolve_sender(sender)
		envelope = make_assistant_streaming_envelope(
			text,
			sender=sender_name,
			session_id=self._session_id,
			call_id=self._call_id,
		)
		payload = envelope.setdefault("payload", {})
		payload.setdefault("message", text)
		payload["turn_id"] = turn_id
		payload["response_id"] = response_id or turn_id
		payload["status"] = "streaming"
		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label="voicelive_assistant_streaming",
				broadcast_only=True,
			),
			label="assistant_streaming_envelope",
		)

	async def send_assistant_cancelled(
		self,
		*,
		response_id: Optional[str],
		sender: Optional[str] = None,
		reason: Optional[str] = None,
	) -> None:
		"""Emit a cancellation update for interrupted assistant turns."""
		if not self._can_emit():
			return

		turn_id = self._ensure_turn_id(response_id, allow_generate=False)
		if not turn_id:
			return

		sender_name = self._resolve_sender(sender)
		payload: Dict[str, Any] = {
			"type": "assistant_cancelled",
			"message": "",
			"content": "",
			"streaming": False,
			"turn_id": turn_id,
			"response_id": response_id or turn_id,
			"status": "cancelled",
		}
		if reason:
			payload["cancel_reason"] = reason

		envelope = make_envelope(
			etype="event",
			sender=sender_name,
			payload=payload,
			topic="session",
			session_id=self._session_id,
			call_id=self._call_id,
		)

		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label="voicelive_assistant_cancelled",
				broadcast_only=True,
			),
			label="assistant_cancelled_envelope",
		)
		self._release_turn(turn_id)

	async def send_session_update(
		self,
		*,
		agent_name: Optional[str],
		session_obj: Optional[Any],
		transport: Optional[str] = None,
	) -> None:
		"""Broadcast session configuration updates to the UI."""
		if not self._can_emit():
			return

		payload: Dict[str, Any] = {
			"event_type": "session_updated",
			"agent_label": _resolve_agent_label(agent_name),
			"agent_name": agent_name,
			"transport": transport,
			"session": _serialize_session_config(session_obj),
		}

		agent_label_display = payload.get("agent_label") or agent_name
		if agent_label_display:
			payload["agent_label"] = agent_label_display
			payload.setdefault("active_agent_label", agent_label_display)
			payload.setdefault(
				"message",
				f"Active agent: {agent_label_display}",
			)

		if session_obj:
			payload["session_id"] = getattr(session_obj, "id", None)

			voice = getattr(session_obj, "voice", None)
			if voice:
				payload["voice"] = {
					"name": getattr(voice, "name", None),
					"type": getattr(voice, "type", None),
					"rate": getattr(voice, "rate", None),
					"style": getattr(voice, "style", None),
				}

			turn_detection = getattr(session_obj, "turn_detection", None)
			if turn_detection:
				payload["turn_detection"] = {
					"type": getattr(turn_detection, "type", None),
					"threshold": getattr(turn_detection, "threshold", None),
					"silence_duration_ms": getattr(turn_detection, "silence_duration_ms", None),
				}

		envelope = make_envelope(
			etype="event",
			sender="System",
			payload=payload,
			topic="session",
			session_id=self._session_id,
			call_id=self._call_id,
		)

		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label="voicelive_session_updated",
				broadcast_only=True,
			),
			label="session_update_envelope",
		)

	async def send_status_update(
		self,
		text: str,
		*,
		tone: Optional[str] = None,
		caption: Optional[str] = None,
		sender: Optional[str] = None,
		event_label: str = "voicelive_status_update",
	) -> None:
		"""Emit a system status envelope for richer UI feedback."""
		if not text or not self._can_emit():
			return

		payload: Dict[str, Any] = {
			"type": "status",
			"message": text,
			"content": text,
		}
		if tone:
			payload["statusTone"] = tone
		if caption:
			payload["statusCaption"] = caption
		sender_name = self._resolve_sender(sender) if (sender or self._default_sender) else "System"

		envelope = make_envelope(
			etype="status",
			sender=sender_name,
			payload=payload,
			topic="session",
			session_id=self._session_id,
			call_id=self._call_id,
		)

		_background_task(
			send_session_envelope(
				self._ws,
				envelope,
				session_id=self._session_id,
				conn_id=None,
				event_label=event_label,
				broadcast_only=True,
			),
			label=event_label,
		)

	async def notify_tool_start(self, *, call_id: Optional[str], name: Optional[str], args: Dict[str, Any]) -> None:
		"""Relay tool start events to the session dashboard."""
		if not self._can_emit() or not call_id or not name:
			return
		try:
			_background_task(
				push_tool_start(
					self._ws,
					call_id,
					name,
					args,
					is_acs=True,
					session_id=self._session_id,
				),
				label=f"tool_start_{name}",
			)
		except Exception:
			logger.debug("Failed to emit tool_start frame for VoiceLive session", exc_info=True)

	async def notify_tool_end(
		self,
		*,
		call_id: Optional[str],
		name: Optional[str],
		status: str,
		elapsed_ms: float,
		result: Optional[Dict[str, Any]] = None,
		error: Optional[str] = None,
	) -> None:
		"""Relay tool completion events (success or failure)."""
		if not self._can_emit() or not call_id or not name:
			return
		try:
			_background_task(
				push_tool_end(
					self._ws,
					call_id,
					name,
					status,
					elapsed_ms,
					result=result,
					error=error,
					is_acs=True,
					session_id=self._session_id,
				),
				label=f"tool_end_{name}",
			)
		except Exception:
			logger.debug("Failed to emit tool_end frame for VoiceLive session", exc_info=True)

VoiceLiveTransport = Literal["acs", "realtime"]


class VoiceLiveSDKHandler:
	"""Minimal VoiceLive handler that mirrors the vlagent multi-agent sample.

	The handler streams ACS audio into Azure VoiceLive, delegates orchestration to the
	shared multi-agent orchestrator, and relays VoiceLive audio deltas back to ACS.

	Args:
		websocket: ACS WebSocket connection for bidirectional media.
		session_id: Identifier used for logging and latency tracking.
		call_connection_id: ACS call connection identifier for diagnostics.
	"""

	def __init__(
		self,
		*,
		websocket: WebSocket,
		session_id: str,
		call_connection_id: Optional[str] = None,
		transport: VoiceLiveTransport = "acs",
		user_email: Optional[str] = None,
	) -> None:
		self.websocket = websocket
		self.session_id = session_id
		self.call_connection_id = call_connection_id or session_id
		self._messenger = _SessionMessenger(websocket)
		self._transport: VoiceLiveTransport = transport
		self._manual_commit_enabled = transport == "acs"
		self._user_email = user_email

		self._settings = None
		self._credential: Optional[Union[AzureKeyCredential, TokenCredential]] = None
		self._connection = None
		self._connection_cm = None
		self._orchestrator: Optional[LiveOrchestrator] = None
		self._event_task: Optional[asyncio.Task] = None
		self._running = False
		self._shutdown = asyncio.Event()
		self._acs_sample_rate = 16000
		self._active_response_ids: set[str] = set()
		self._stop_audio_pending = False
		self._response_audio_frames: Dict[str, int] = {}
		self._fallback_audio_frame_index = 0
		self._dtmf_digits: list[str] = []
		self._dtmf_flush_task: Optional[asyncio.Task] = None
		self._dtmf_flush_delay = _DTMF_FLUSH_DELAY_SECONDS
		self._dtmf_lock = asyncio.Lock()
		self._last_user_transcript: Optional[str] = None
		self._last_user_turn_id: Optional[str] = None

	def _set_metadata(self, key: str, value: Any) -> None:
		if not _set_connection_metadata(self.websocket, key, value):
			setattr(self.websocket.state, key, value)

	def _get_metadata(self, key: str, default: Any = None) -> Any:
		"""Read per-connection metadata from the websocket.state (or default)."""
		return getattr(self.websocket.state, key, default)

	def _mark_audio_playback(self, active: bool, *, reset_cancel: bool = True) -> None:
		# single source of truth for "assistant is speaking"
		self._set_metadata("audio_playing", active)
		self._set_metadata("tts_active", active)
		if reset_cancel:
			self._set_metadata("tts_cancel_requested", False)

	def _trigger_barge_in(
		self,
		trigger: str,
		stage: str,
		*,
		energy_level: Optional[float] = None,
		reset_audio_state: bool = True,
	) -> None:
		request_fn = getattr(self.websocket.state, "request_barge_in", None)
		if callable(request_fn):
			try:
				kwargs: Dict[str, Any] = {}
				if energy_level is not None:
					kwargs["energy_level"] = energy_level
				request_fn(trigger, stage, **kwargs)
			except Exception:
				logger.debug("Failed to dispatch barge-in request", exc_info=True)
		else:
			logger.debug(
				"[%s] No barge-in handler available for realtime trigger", self.session_id
			)

		self._set_metadata("tts_cancel_requested", True)
		if reset_audio_state:
			self._mark_audio_playback(False, reset_cancel=False)

	async def start(self) -> None:
		"""Establish VoiceLive connection and start event processing."""
		if self._running:
			return

		try:
			self._settings = get_settings()
			connection_options = {
				"max_msg_size": self._settings.ws_max_msg_size,
				"heartbeat": self._settings.ws_heartbeat,
				"timeout": self._settings.ws_timeout,
			}

			self._credential = self._build_credential(self._settings)
			self._connection_cm = connect(
				endpoint=self._settings.azure_voicelive_endpoint,
				credential=self._credential,
				model=self._settings.azure_voicelive_model,
				connection_options=connection_options,
			)
			self._connection = await self._connection_cm.__aenter__()

			agents = load_registry(str(self._settings.agents_path))
			
			user_profile = None
			if hasattr(self, '_user_email') and self._user_email:
				logger.info("Loading user profile for session | email=%s", self._user_email)
				user_profile = await load_user_profile_by_email(self._user_email)
			
			self._orchestrator = LiveOrchestrator(
				conn=self._connection,
				agents=agents,
				handoff_map=HANDOFF_MAP,
				start_agent=self._settings.start_agent,
				audio_processor=None,
				messenger=self._messenger,
				call_connection_id=self.call_connection_id,
				transport=self._transport,
			)

			system_vars = {}
			if user_profile:
				system_vars["session_profile"] = user_profile
				system_vars["client_id"] = user_profile.get("client_id")
				system_vars["customer_intelligence"] = user_profile.get("customer_intelligence", {})
				logger.info(
					"✅ Session initialized with user profile | client_id=%s name=%s",
					user_profile.get("client_id"),
					user_profile.get("full_name")
				)
			
			await self._orchestrator.start(system_vars=system_vars)

			self._running = True
			self._shutdown.clear()
			self._event_task = asyncio.create_task(self._event_loop())
			logger.info(
				"VoiceLive SDK handler started | session=%s call=%s",
				self.session_id,
				self.call_connection_id,
			)
		except Exception:
			await self.stop()
			raise

	async def stop(self) -> None:
		"""Stop event processing and release VoiceLive resources."""
		if not self._running:
			return

		self._running = False
		self._shutdown.set()

		if self._dtmf_flush_task:
			self._dtmf_flush_task.cancel()
			try:
				await self._dtmf_flush_task
			except asyncio.CancelledError:
				pass
			finally:
				self._dtmf_flush_task = None
		self._dtmf_digits.clear()

		if self._event_task:
			self._event_task.cancel()
			try:
				await self._event_task
			except asyncio.CancelledError:
				pass
			finally:
				self._event_task = None

		if self._connection_cm:
			try:
				await self._connection_cm.__aexit__(None, None, None)
			except Exception:
				logger.exception("Error closing VoiceLive connection")
			finally:
				self._connection_cm = None
				self._connection = None

		if isinstance(self._credential, DefaultAzureCredential):
			try:
				await self._credential.close()
			except Exception:
				logger.debug("Failed to close DefaultAzureCredential", exc_info=True)
		self._credential = None

		logger.info(
			"VoiceLive SDK handler stopped | session=%s call=%s",
			self.session_id,
			self.call_connection_id,
		)

	async def handle_audio_data(self, message_data: str) -> None:
		"""Forward ACS media payloads to VoiceLive."""
		if not self._running or not self._connection:
			logger.debug("VoiceLive handler inactive; dropping media message")
			return

		try:
			payload = json.loads(message_data)
		except json.JSONDecodeError:
			logger.debug("Skipping non-JSON media message")
			return

		kind = payload.get("kind") or payload.get("Kind")
		
		if kind == "AudioMetadata":
			metadata = payload.get("payload", {})
			self._acs_sample_rate = metadata.get("rate", self._acs_sample_rate)
			logger.info(
				"Updated ACS audio metadata | session=%s rate=%s channels=%s",
				self.session_id,
				self._acs_sample_rate,
				metadata.get("channels", 1),
			)
			return

		if kind == "AudioData":
			audio_section = payload.get("audioData") or payload.get("AudioData") or {}
			if audio_section.get("silent"):
				return
			encoded = audio_section.get("data")
			if not encoded:
				return
			await self._connection.input_audio_buffer.append(audio=encoded)
			return

		if kind == "StopAudio":
			if self._manual_commit_enabled:
				await self._commit_input_buffer()
			return

		if kind == "DtmfData":
			tone = (payload.get("dtmfData") or payload.get("DtmfData") or {}).get("data")
			await self._handle_dtmf_tone(tone)
			return

	async def handle_pcm_chunk(self, audio_bytes: bytes, sample_rate: int = 16000) -> None:
		"""Forward raw PCM frames (e.g., from realtime WS) to VoiceLive."""
		if not self._running or not self._connection or not audio_bytes:
			return

		try:
			encoded = base64.b64encode(audio_bytes).decode("utf-8")
		except Exception:
			logger.debug("Failed to encode realtime PCM chunk for VoiceLive", exc_info=True)
			return

		self._acs_sample_rate = sample_rate or self._acs_sample_rate
		await self._connection.input_audio_buffer.append(audio=encoded)

	async def commit_audio_buffer(self) -> None:
		"""Commit the current VoiceLive input buffer to trigger response generation."""
		if not self._manual_commit_enabled:
			return
		await self._commit_input_buffer()

	async def _event_loop(self) -> None:
		"""Consume VoiceLive events, orchestrate tools, and stream audio to ACS."""
		assert self._connection is not None
		try:
			async for event in self._connection:
				if self._shutdown.is_set():
					break

				self._observe_event(event)

				if self._orchestrator:
					await self._orchestrator.handle_event(event)

				await self._forward_event_to_acs(event)
		except asyncio.CancelledError:
			logger.debug("VoiceLive event loop cancelled | session=%s", self.session_id)
			raise
		except Exception:
			logger.exception("VoiceLive event loop error | session=%s", self.session_id)
		finally:
			self._shutdown.set()

	async def _forward_event_to_acs(self, event: Any) -> None:
		if not self._websocket_open:
			return

		etype = event.type if hasattr(event, "type") else None
		
		# Log all events for debugging
		if etype:
			logger.debug(
				"[VoiceLive] Event: %s | session=%s",
				etype.value if hasattr(etype, 'value') else str(etype),
				self.session_id,
			)
		
		if etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
			transcript = getattr(event, "transcript", "")
			turn_id = self._messenger.resolve_user_turn_id(self._extract_item_id(event))
			if transcript and (
				transcript != self._last_user_transcript or turn_id != self._last_user_turn_id
			):
				await self._messenger.send_user_message(transcript, turn_id=turn_id)
				logger.info(
					"[VoiceLiveSDK] User transcript | session=%s text='%s'",
					self.session_id,
					transcript,
				)
				self._last_user_transcript = transcript
				self._last_user_turn_id = turn_id
				self._messenger.finish_user_turn(turn_id)
			return
		elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
			response_id = getattr(event, "response_id", None)
			delta_bytes = getattr(event, "delta", None)
			logger.debug(
				"[VoiceLive] Audio delta received | session=%s response=%s bytes=%s",
				self.session_id,
				response_id,
				len(delta_bytes) if delta_bytes else 0,
			)
			if response_id:
				self._active_response_ids.add(response_id)
			self._stop_audio_pending = False
			await self._send_audio_delta(event.delta, response_id=response_id)
		
		elif etype == ServerEventType.RESPONSE_DONE:
			response_id = self._extract_response_id(event)
			if response_id:
				logger.debug(
					"[VoiceLive] Response done | session=%s response=%s",
					self.session_id,
					response_id,
				)
				if self._should_stop_for_response(event) and response_id in self._active_response_ids:
					await self._send_stop_audio()
				self._active_response_ids.discard(response_id)
				self._mark_audio_playback(False)
			else:
				logger.debug(
					"[VoiceLive] Response done without audio playback | session=%s",
					self.session_id,
				)
				self._mark_audio_playback(False)

		elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
			# User started speaking - stop assistant playback
			logger.info(
				"[VoiceLive] User speech started | session=%s",
				self.session_id,
			)
			self._active_response_ids.clear()
			energy = getattr(event, "speech_energy", None)
			turn_id = self._extract_item_id(event)
			resolved_turn = self._messenger.begin_user_turn(turn_id)
			if resolved_turn:
				self._last_user_turn_id = resolved_turn
				self._last_user_transcript = ""
			self._trigger_barge_in(
				"voicelive_vad",
				"speech_started",
				energy_level=energy,
			)
			await self._send_stop_audio()
			self._stop_audio_pending = False

		elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
			logger.debug("🎤 User paused speaking")
			logger.debug("🤖 Generating assistant reply")
			self._mark_audio_playback(False)

		elif etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
			transcript_text = getattr(event, "transcript", "") or getattr(event, "delta", "")
			if not transcript_text:
				return
			session_id = self._messenger._session_id
			if not session_id:
				return
			turn_id = self._messenger.resolve_user_turn_id(self._extract_item_id(event))
			payload = {
				"type": "user",
				"message": "...",
				"content": transcript_text,
				"streaming": True,
			}
			if turn_id:
				payload["turn_id"] = turn_id
				payload["response_id"] = turn_id
			envelope = make_envelope(
				etype="event",
				sender="User",
				payload=payload,
				topic="session",
				session_id=session_id,
				call_id=self.call_connection_id,
			)
			_background_task(
				send_session_envelope(
					self.websocket,
					envelope,
					session_id=session_id,
					conn_id=None,
					event_label="voicelive_user_transcript_delta",
					broadcast_only=True,
				),
				label="voicelive_user_transcript_delta",
			)


		elif etype == ServerEventType.RESPONSE_AUDIO_DONE:
			logger.debug(
				"[VoiceLiveSDK] Audio stream marked done | session=%s response=%s",
				self.session_id,
				getattr(event, "response_id", "unknown"),
			)
			response_id = getattr(event, "response_id", None)
			if response_id:
				self._active_response_ids.discard(response_id)
				await self._emit_audio_frame_to_ui(response_id, data_b64=None, frame_index=self._final_frame_index(response_id), is_final=True)
			else:
				await self._emit_audio_frame_to_ui(None, data_b64=None, frame_index=self._final_frame_index(None), is_final=True)
		elif etype == ServerEventType.ERROR:
			await self._handle_server_error(event)
			self._mark_audio_playback(False)
	
		elif etype == ServerEventType.CONVERSATION_ITEM_CREATED:
			logger.debug("Conversation item created: %s", event.item.id)
	
	async def _send_audio_delta(self, audio_bytes: bytes, *, response_id: Optional[str]) -> None:
		pcm_bytes = self._to_pcm_bytes(audio_bytes)
		if not pcm_bytes:
			return

		# Resample VoiceLive 24 kHz PCM to match ACS expectations.
		resampled = self._resample_audio(pcm_bytes)
		frame_index = self._allocate_frame_index(response_id)
		try:
			logger.debug(
				"[VoiceLiveSDK] Sending audio delta | session=%s bytes=%s",
				self.session_id,
				len(pcm_bytes),
			)
			self._mark_audio_playback(True)
			if self._transport == "acs":
				message = {
					"kind": "AudioData",
					"AudioData": {"data": resampled},
					"StopAudio": None,
				}
				await self.websocket.send_json(message)
			await self._emit_audio_frame_to_ui(
				response_id,
				data_b64=resampled,
				frame_index=frame_index,
				is_final=False,
			)
		except Exception:
			logger.debug("Failed to relay audio delta", exc_info=True)

	async def _emit_audio_frame_to_ui(
		self,
		response_id: Optional[str],
		*,
		data_b64: Optional[str],
		frame_index: int,
		is_final: bool,
	) -> None:
		if not self._websocket_open:
			return
		if is_final:
			self._mark_audio_playback(False)
		payload = {
			"type": "audio_data",
			"frame_index": frame_index,
			"total_frames": None,
			"sample_rate": self._acs_sample_rate,
			"is_final": is_final,
			"response_id": response_id,
		}
		if data_b64:
			payload["data"] = data_b64
		try:
			await self.websocket.send_json(payload)
		except Exception:
			logger.debug("Failed to emit UI audio frame", exc_info=True)

	def _allocate_frame_index(self, response_id: Optional[str]) -> int:
		if response_id:
			current = self._response_audio_frames.get(response_id, 0)
			self._response_audio_frames[response_id] = current + 1
			return current
		current = self._fallback_audio_frame_index
		self._fallback_audio_frame_index += 1
		return current

	def _final_frame_index(self, response_id: Optional[str]) -> int:
		if response_id and response_id in self._response_audio_frames:
			next_idx = self._response_audio_frames.pop(response_id)
			return max(next_idx - 1, 0)
		if not response_id:
			final_idx = max(self._fallback_audio_frame_index - 1, 0)
			self._fallback_audio_frame_index = 0
			return final_idx
		return 0

	async def _send_stop_audio(self) -> None:
		self._mark_audio_playback(False, reset_cancel=False)
		if self._transport != "acs":
			self._stop_audio_pending = False
			return
		if self._stop_audio_pending:
			return
		stop_message = {"kind": "StopAudio", "AudioData": None, "StopAudio": {}}
		try:
			await self.websocket.send_json(stop_message)
			self._stop_audio_pending = True
		except Exception:
			self._stop_audio_pending = False
			logger.debug("Failed to send StopAudio", exc_info=True)

	async def _send_error(self, event: Any) -> None:
		error_info: Dict[str, Any] = {
			"kind": "ErrorData",
			"errorData": {
				"code": getattr(event.error, "code", "VoiceLiveError"),
				"message": getattr(event.error, "message", "Unknown VoiceLive error"),
			},
		}
		try:
			await self.websocket.send_json(error_info)
		except Exception:
			logger.debug("Failed to send error message", exc_info=True)

	async def _handle_server_error(self, event: Any) -> None:
		error_obj = getattr(event, "error", None)
		code = getattr(error_obj, "code", "VoiceLiveError")
		message = getattr(error_obj, "message", "Unknown VoiceLive error")
		details = getattr(error_obj, "details", None)

		logger.error(
			"[VoiceLiveSDK] Server error received | session=%s call=%s code=%s message=%s",
			self.session_id,
			self.call_connection_id,
			code,
			message,
		)
		if details:
			logger.error(
				"[VoiceLiveSDK] Error details | session=%s call=%s details=%s",
				self.session_id,
				self.call_connection_id,
				details,
			)

		await self._send_stop_audio()
		await self._send_error(event)

	async def _handle_dtmf_tone(self, raw_tone: Any) -> None:
		normalized = self._normalize_dtmf_tone(raw_tone)
		if not normalized:
			logger.debug("Ignoring invalid DTMF tone %s | session=%s", raw_tone, self.session_id)
			return

		if normalized == "#":
			self._cancel_dtmf_flush_timer()
			await self._flush_dtmf_buffer(reason="terminator")
			return
		if normalized == "*":
			await self._clear_dtmf_buffer()
			return

		async with self._dtmf_lock:
			self._dtmf_digits.append(normalized)
			buffer_len = len(self._dtmf_digits)
		logger.info(
			"Received DTMF tone %s (buffer_len=%s) | session=%s",
			normalized,
			buffer_len,
			self.session_id,
		)
		self._schedule_dtmf_flush()

	def _schedule_dtmf_flush(self) -> None:
		self._cancel_dtmf_flush_timer()
		self._dtmf_flush_task = asyncio.create_task(self._delayed_dtmf_flush())

	def _cancel_dtmf_flush_timer(self) -> None:
		if self._dtmf_flush_task:
			self._dtmf_flush_task.cancel()
			self._dtmf_flush_task = None

	async def _delayed_dtmf_flush(self) -> None:
		try:
			await asyncio.sleep(self._dtmf_flush_delay)
			await self._flush_dtmf_buffer(reason="timeout")
		except asyncio.CancelledError:
			return
		finally:
			self._dtmf_flush_task = None

	async def _flush_dtmf_buffer(self, *, reason: str) -> None:
		async with self._dtmf_lock:
			if not self._dtmf_digits:
				return
			sequence = "".join(self._dtmf_digits)
			self._dtmf_digits.clear()
		await self._send_dtmf_user_message(sequence, reason=reason)

	async def _clear_dtmf_buffer(self) -> None:
		self._cancel_dtmf_flush_timer()
		async with self._dtmf_lock:
			if self._dtmf_digits:
				logger.info(
					"Clearing DTMF buffer without forwarding (buffer_len=%s) | session=%s",
					len(self._dtmf_digits),
					self.session_id,
				)
			self._dtmf_digits.clear()

	async def send_text_message(self, text: str) -> None:
		"""Send a text message from the user to the VoiceLive conversation.
		
		With Azure Semantic VAD enabled, text messages are sent via conversation.item.create
		using UserMessageItem with InputTextContentPart, not through audio buffer.
		
		Implements barge-in: triggers interruption if agent is currently speaking.
		"""
		if not text or not self._connection:
			return
		
		try:
			# BARGE-IN: trigger interruption if TTS is currently active
			is_playing = self._get_metadata("tts_active", False)
			if is_playing:
				self._trigger_barge_in(
					trigger="user_text_input",
					stage="text_message_send",
					reset_audio_state=True,
				)
				# Actively send StopAudio to ACS so playback halts immediately
				try:
					await self._send_stop_audio()
				except Exception:
					logger.debug("Failed to send StopAudio during text barge-in", exc_info=True)
				
				logger.info(
					"Text barge-in triggered (agent was speaking) | session=%s",
					self.session_id,
				)
			
			# Create a text content part
			text_part = InputTextContentPart(text=text)
			
			# Wrap it as a user message item
			user_message = UserMessageItem(content=[text_part])
			
			# Send conversation.item.create
			await self._connection.send(
				ClientEventConversationItemCreate(item=user_message)
			)
			
			# Ask for a model response considering all history (audio + text)
			await self._connection.send(ClientEventResponseCreate())
			
			logger.info(
				"Forwarded user text message (%s chars) | session=%s",
				len(text),
				self.session_id,
			)
		except Exception:
			logger.exception(
				"Failed to forward user text to VoiceLive | session=%s",
				self.session_id,
			)

	async def _send_dtmf_user_message(self, digits: str, *, reason: str) -> None:
		if not digits or not self._connection:
			return
		item = {
			"type": "message",
			"role": "user",
			"content": [{"type": "input_text", "text": digits}],
		}
		try:
			await self._connection.conversation.item.create(item=item)
			await self._connection.response.create()
			logger.info(
				"Forwarded DTMF sequence (%s digits) via %s | session=%s",
				len(digits),
				reason,
				self.session_id,
			)
		except Exception:
			logger.exception("Failed to forward DTMF digits to VoiceLive | session=%s", self.session_id)

	@staticmethod
	def _normalize_dtmf_tone(raw_tone: Any) -> Optional[str]:
		if raw_tone is None:
			return None
		tone = str(raw_tone).strip().lower()
		tone_map = {
			"0": "0",
			"zero": "0",
			"1": "1",
			"one": "1",
			"2": "2",
			"two": "2",
			"3": "3",
			"three": "3",
			"4": "4",
			"four": "4",
			"5": "5",
			"five": "5",
			"6": "6",
			"six": "6",
			"7": "7",
			"seven": "7",
			"8": "8",
			"eight": "8",
			"9": "9",
			"nine": "9",
			"*": "*",
			"star": "*",
			"asterisk": "*",
			"#": "#",
			"pound": "#",
			"hash": "#",
		}
		return tone_map.get(tone)

	def _to_pcm_bytes(self, audio_payload: Any) -> Optional[bytes]:
		if isinstance(audio_payload, bytes):
			return audio_payload
		if isinstance(audio_payload, str):
			try:
				return base64.b64decode(audio_payload)
			except Exception:
				logger.debug("Failed to decode base64 audio payload", exc_info=True)
		return None

	def _observe_event(self, event: Any) -> None:
		type_value = getattr(event, "type", "unknown")
		type_str = (
			type_value.value if isinstance(type_value, ServerEventType) else str(type_value)
		)

		logger.debug(
			"[VoiceLiveSDK] Event received | session=%s type=%s",
			self.session_id,
			type_str,
		)

		# if type_str not in _TRACED_EVENTS:
		# 	return

		attributes = {
			"voicelive.event.type": type_str,
			"voicelive.session_id": self.session_id,
			"call.connection.id": self.call_connection_id,
		}
		if hasattr(event, "transcript") and getattr(event, "transcript"):
			transcript = getattr(event, "transcript")
			attributes["voicelive.transcript.length"] = len(transcript)
		if hasattr(event, "delta") and getattr(event, "delta"):
			delta = getattr(event, "delta")
			attributes["voicelive.delta.size"] = len(delta) if isinstance(delta, (bytes, str)) else 0

		with tracer.start_as_current_span(
			"voicelive.event",
			kind=SpanKind.INTERNAL,
			attributes=attributes,
		):
			pass

	async def _commit_input_buffer(self) -> None:
		if not self._connection:
			return
		try:
			await self._connection.input_audio_buffer.commit()
			logger.debug(
				"[VoiceLiveSDK] Committed input audio buffer | session=%s",
				self.session_id,
			)
		except Exception:
			logger.warning(
				"[VoiceLiveSDK] Failed to commit input audio buffer | session=%s",
				self.session_id,
				exc_info=True,
			)

	def _resample_audio(self, audio_bytes: bytes) -> str:
		try:
			source = np.frombuffer(audio_bytes, dtype=np.int16)
			source_rate = 24000
			target_rate = max(self._acs_sample_rate, 1)
			if source_rate == target_rate:
				return base64.b64encode(audio_bytes).decode("utf-8")

			ratio = target_rate / source_rate
			new_len = max(int(len(source) * ratio), 1)
			new_idx = np.linspace(0, len(source) - 1, new_len)
			resampled = np.interp(new_idx, np.arange(len(source)), source.astype(np.float32))
			resampled_int16 = resampled.astype(np.int16).tobytes()
			return base64.b64encode(resampled_int16).decode("utf-8")
		except Exception:
			logger.debug("Audio resample failed; returning original", exc_info=True)
			return base64.b64encode(audio_bytes).decode("utf-8")

	@property
	def _websocket_open(self) -> bool:
		return (
			hasattr(self.websocket, "application_state")
			and hasattr(self.websocket, "client_state")
			and self.websocket.application_state == WebSocketState.CONNECTED
			and self.websocket.client_state == WebSocketState.CONNECTED
		)

	@staticmethod
	def _extract_item_id(event: Any) -> Optional[str]:
		for attr in (
			"item_id",
			"conversation_item_id",
			"input_audio_item_id",
			"id",
		):
			value = getattr(event, attr, None)
			if value:
				return value
		item = getattr(event, "item", None)
		if item and hasattr(item, "id"):
			return getattr(item, "id")
		return None

	@staticmethod
	def _extract_response_id(event: Any) -> Optional[str]:
		response = getattr(event, "response", None)
		if response and hasattr(response, "id"):
			return getattr(response, "id")
		return None

	def _should_stop_for_response(self, event: Any) -> bool:
		response = getattr(event, "response", None)
		if not response:
			return bool(self._active_response_ids)

		status = getattr(response, "status", None)
		if isinstance(status, ResponseStatus):
			return status != ResponseStatus.IN_PROGRESS
		if isinstance(status, str):
			return status.lower() != ResponseStatus.IN_PROGRESS.value
		return True

	@staticmethod
	def _build_credential(settings) -> Union[AzureKeyCredential, TokenCredential]:
		if settings.has_api_key_auth:
			return AzureKeyCredential(settings.azure_voicelive_api_key)
		return DefaultAzureCredential()


__all__ = ["VoiceLiveSDKHandler"]
