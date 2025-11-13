"""VoiceLive SDK handler bridging ACS media streams to multi-agent orchestration."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict, Optional, Union

import numpy as np
from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import ServerEventType, ResponseStatus
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity.aio import DefaultAzureCredential

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from utils.ml_logging import get_logger
from apps.rtagent.backend.src.agents.vlagent.settings import get_settings
from apps.rtagent.backend.src.agents.vlagent.registry import load_registry, HANDOFF_MAP
from apps.rtagent.backend.src.agents.vlagent.orchestrator import LiveOrchestrator

import logging

logger = get_logger("api.v1.handlers.voice_live_sdk_handler")
tracer = trace.get_tracer(__name__)

_TRACED_EVENTS = {
	ServerEventType.ERROR.value,
	ServerEventType.RESPONSE_CREATED.value,
	ServerEventType.RESPONSE_DONE.value,
	ServerEventType.RESPONSE_AUDIO_DONE.value,
	ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED.value,
	ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED.value,
	ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED.value,
}

_DTMF_FLUSH_DELAY_SECONDS = 1.5

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
	) -> None:
		self.websocket = websocket
		self.session_id = session_id
		self.call_connection_id = call_connection_id or session_id

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
		self._dtmf_digits: list[str] = []
		self._dtmf_flush_task: Optional[asyncio.Task] = None
		self._dtmf_flush_delay = _DTMF_FLUSH_DELAY_SECONDS
		self._dtmf_lock = asyncio.Lock()

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
				model=self._settings.voicelive_model,
				connection_options=connection_options,
			)
			self._connection = await self._connection_cm.__aenter__()

			agents = load_registry(str(self._settings.agents_path))
			self._orchestrator = LiveOrchestrator(
				conn=self._connection,
				agents=agents,
				handoff_map=HANDOFF_MAP,
				start_agent=self._settings.start_agent,
				audio_processor=None,
			)

			await self._orchestrator.start()

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
			await self._commit_input_buffer()
			return

		if kind == "DtmfData":
			tone = (payload.get("dtmfData") or payload.get("DtmfData") or {}).get("data")
			await self._handle_dtmf_tone(tone)
			return

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
		if etype == ServerEventType.RESPONSE_AUDIO_DELTA:
			response_id = getattr(event, "response_id", None)
			if response_id:
				self._active_response_ids.add(response_id)
			self._stop_audio_pending = False
			await self._send_audio_delta(event.delta)

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
			else:
				logger.debug("[VoiceLive] Response done without audio playback | session=%s", self.session_id)

		elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
			# User started speaking - stop assistant playback
			logger.info(
				"[VoiceLive] User speech started | session=%s",
				self.session_id,
			)
			self._active_response_ids.clear()
			await self._send_stop_audio()
			self._stop_audio_pending = False


		elif etype == ServerEventType.RESPONSE_AUDIO_DONE:
			logger.debug(
				"[VoiceLiveSDK] Audio stream marked done | session=%s response=%s",
				self.session_id,
				getattr(event, "response_id", "unknown"),
			)
			response_id = getattr(event, "response_id", None)
			if response_id:
				self._active_response_ids.discard(response_id)
		elif etype == ServerEventType.ERROR:
			await self._handle_server_error(event)
		elif etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
			transcript = getattr(event, "transcript", "")
			if transcript:
				logger.info(
					"[VoiceLiveSDK] User transcript | session=%s text='%s'",
					self.session_id,
					transcript,
				)

	async def _send_audio_delta(self, audio_bytes: bytes) -> None:
		pcm_bytes = self._to_pcm_bytes(audio_bytes)
		if not pcm_bytes:
			return

		# Resample VoiceLive 24 kHz PCM to match ACS expectations.
		resampled = self._resample_audio(pcm_bytes)
		message = {
			"kind": "AudioData",
			"AudioData": {"data": resampled},
			"StopAudio": None,
		}
		try:
			logger.debug(
				"[VoiceLiveSDK] Sending audio delta | session=%s bytes=%s",
				self.session_id,
				len(pcm_bytes),
			)
			await self.websocket.send_json(message)
		except Exception:
			logger.debug("Failed to relay audio delta", exc_info=True)

	async def _send_stop_audio(self) -> None:
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

		if type_str not in _TRACED_EVENTS:
			return

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
