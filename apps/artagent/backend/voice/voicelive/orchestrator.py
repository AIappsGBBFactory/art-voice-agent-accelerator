"""
VoiceLive Orchestrator
=======================

Orchestrates agent switching and tool execution for VoiceLive multi-agent system.

All tool execution flows through the shared tool registry for centralized management:
- Handoff tools → trigger agent switching
- Business tools → execute and return results to model

Architecture:
    VoiceLiveSDKHandler
           │
           ▼
    LiveOrchestrator ─► UnifiedAgent registry
           │                    │
           ├─► handle_event()   └─► apply_voicelive_session()
           │                        trigger_voicelive_response()
           └─► _execute_tool_call() ───► shared tool registry

Usage:
    from apps.artagent.backend.voice.voicelive import (
        LiveOrchestrator,
        TRANSFER_TOOL_NAMES,
        CALL_CENTER_TRIGGER_PHRASES,
    )

    orchestrator = LiveOrchestrator(
        conn=voicelive_connection,
        agents=unified_agents,  # dict[str, UnifiedAgent]
        handoff_map=handoff_map,
        start_agent="Concierge",
    )
    await orchestrator.start(system_vars={...})
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from typing import TYPE_CHECKING, Any

# Self-contained tool registry (no legacy vlagent dependency)
from apps.artagent.backend.registries.toolstore import (
    execute_tool,
    initialize_tools,
)
from apps.artagent.backend.src.services.session_loader import load_user_profile_by_client_id
from apps.artagent.backend.voice.handoffs import sanitize_handoff_context
from apps.artagent.backend.voice.shared.handoff_service import HandoffService
from apps.artagent.backend.voice.shared.errors import (
    BENIGN_VOICELIVE_ERROR_CODES,
    classify_voice_error,
    classify_voicelive_server_error,
    emit_voice_error,
)
from apps.artagent.backend.voice.shared.metrics import OrchestratorMetrics
from apps.artagent.backend.voice.shared.session_state import (
    sync_state_from_memo,
    sync_state_to_memo,
)
from azure.ai.voicelive.models import (
    AssistantMessageItem,
    FunctionCallOutputItem,
    InputTextContentPart,
    OutputTextContentPart,
    ServerEventType,
    UserMessageItem,
)
from opentelemetry import trace

if TYPE_CHECKING:
    from src.stateful.state_managment import MemoManager

from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.src.orchestration.naming import agent_key, find_agent_by_name

from apps.artagent.backend.src.utils.tracing import (
    create_service_dependency_attrs,
    create_service_handler_attrs,
)
from src.enums.monitoring import GenAIOperation, GenAIProvider, SpanAttr
from utils.ml_logging import get_logger

logger = get_logger("voicelive.orchestrator")
tracer = trace.get_tracer(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

TRANSFER_TOOL_NAMES = {"transfer_call_to_destination", "transfer_call_to_call_center"}

CALL_CENTER_TRIGGER_PHRASES = {
    "transfer to call center",
    "transfer me to the call center",
}

# How long `_schedule_greeting_fallback()` waits before delivering the greeting
# itself. The bootstrap `session.updated` echo is the only reliable signal that
# the agent's voice/instructions are actually live, and it arrives ~550-600ms
# after `apply_voicelive_session()` returns (observed on production calls). At
# the previous 0.35s this "fallback" therefore won *every* time, which inverted
# its intent: it greeted against a session the service had not acknowledged yet,
# and the echo that landed ~200ms later tore the half-spoken greeting down. The
# delay must sit comfortably above the echo latency so the echo is the normal
# trigger and this timer only covers the case where no echo ever arrives.
GREETING_FALLBACK_DELAY_S = 1.5

# Benign VoiceLive server-error codes emitted when a barge-in / response.cancel
# races a response that already finished. These are expected and must NOT be
# logged as errors or surfaced to the UI. Shared with the handler so both layers
# suppress exactly the same set.
_BENIGN_ERROR_CODES = BENIGN_VOICELIVE_ERROR_CODES


def _voice_identity(voice: Any) -> str | None:
    """Extract a comparable voice identity from a payload or a server echo.

    The Voice Live wire format allows ``voice`` to be either a plain string
    (OpenAI voices such as ``alloy``) or an object with a ``name`` (Azure
    standard / custom / personal voices), and the SDK echoes it back in the
    same shape it was accepted. Normalizing both to a lowercase name is what
    makes "did the voice I asked for actually apply?" answerable.
    """
    if voice is None:
        return None
    if isinstance(voice, str):
        return voice.strip().lower() or None
    name = getattr(voice, "name", None)
    if name is None and isinstance(voice, dict):
        name = voice.get("name")
    if isinstance(name, str):
        return name.strip().lower() or None
    return None


# Azure OpenAI / AI Foundry deployment names routinely carry the *deployment
# tier* (SKU) as a suffix on the base model name: a session that requested
# ``gpt-realtime`` is echoed back as ``gpt-realtime-datazone-standard``. That is
# the same underlying model on a differently-provisioned deployment, not a
# substitution — treating it as one fires a warning on every ``session.updated``
# and pins the ``session_contract_ok`` KPI to False.
#
# This is an explicit allowlist on purpose. A generic "applied starts with
# requested" rule would also accept ``gpt-realtime-mini``, a genuinely different
# and cheaper model — exactly the substitution this contract check exists to
# catch. Widening the tolerance therefore has to be a deliberate edit here.
_MODEL_SKU_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        (
            "datazone-standard",
            "data-zone-standard",
            "datazonestandard",
            "datazone-batch",
            "datazone",
            "global-standard",
            "globalstandard",
            "global-batch",
            "globalbatch",
            "global-provisioned-managed",
            "provisioned-managed",
            "provisionedmanaged",
            "provisioned",
            "regional",
            "standard",
            "batch",
            "global",
        ),
        key=len,
        reverse=True,
    )
)


def _model_base_and_sku(model: str | None) -> tuple[str | None, str | None]:
    """Split a normalized deployment name into its base model and deployment tier.

    Strips **at most one** recognized SKU suffix, longest match first so
    ``-datazone-standard`` wins over ``-standard``. A single bounded strip against
    a known list keeps the transform auditable: an unrecognized tail stays on the
    base, where it correctly registers as a mismatch.

    Returns ``(base, sku)``; ``sku`` is ``None`` when the name carries no
    recognized tier suffix.
    """
    if not model:
        return None, None
    for suffix in _MODEL_SKU_SUFFIXES:
        marker = f"-{suffix}"
        if model.endswith(marker) and len(model) > len(marker):
            return model[: -len(marker)], suffix
    return model, None


def verify_voicelive_session_contract(
    *,
    requested_voice: Any,
    requested_model: str | None,
    session_obj: Any,
) -> dict[str, Any]:
    """Compare the session config we asked for against what the service echoed.

    ``session.updated`` is the only ground truth for a Voice Live session: the
    service echoes the config it actually accepted. Without this comparison a
    rejected/ignored voice or a model that silently differs from the one the
    agent selected is indistinguishable from success — which is exactly how a
    "the TTS voice isn't being respected" bug stays invisible.

    Unknown/absent echo fields are treated as "not verifiable" (``None``) rather
    than as a mismatch, so older service versions don't produce false alarms.

    The model comparison is **SKU-tolerant**: Azure echoes the deployment name,
    which usually appends the provisioned tier to the base model
    (``gpt-realtime`` → ``gpt-realtime-datazone-standard``). Both sides are run
    through :func:`_model_base_and_sku`, which removes at most one *recognized*
    tier suffix, and the bases are compared. An allowlist is used rather than a
    prefix/substring rule precisely so a genuinely different model still fails:
    ``gpt-4o-realtime-preview`` and ``gpt-realtime-mini`` are not tiers of
    ``gpt-realtime`` and are both reported as mismatches. Normalizing both sides
    also makes the check symmetric, for when our own configured deployment name
    is the SKU-qualified one.

    Returns a dict with ``voice_requested``/``voice_applied``/``voice_ok``,
    ``model_requested``/``model_applied``/``model_ok`` and an aggregate ``ok``
    that is False only when something is verifiably wrong. ``model_applied``
    stays the *raw* normalized echo so operators can still see which tier the
    session landed on; the SKU-stripped values used for the comparison are
    exposed separately as ``model_*_base`` / ``model_*_sku``.
    """
    voice_requested = _voice_identity(requested_voice)
    voice_applied = _voice_identity(getattr(session_obj, "voice", None))
    voice_ok: bool | None = None
    if voice_requested is not None and voice_applied is not None:
        voice_ok = voice_requested == voice_applied

    model_requested = (requested_model or "").strip().lower() or None
    raw_model_applied = getattr(session_obj, "model", None)
    model_applied = (
        raw_model_applied.strip().lower() if isinstance(raw_model_applied, str) else None
    )
    model_requested_base, model_requested_sku = _model_base_and_sku(model_requested)
    model_applied_base, model_applied_sku = _model_base_and_sku(model_applied)
    model_ok: bool | None = None
    if model_requested_base is not None and model_applied_base is not None:
        model_ok = model_requested_base == model_applied_base

    return {
        "voice_requested": voice_requested,
        "voice_applied": voice_applied,
        "voice_ok": voice_ok,
        "model_requested": model_requested,
        "model_applied": model_applied,
        "model_ok": model_ok,
        "model_requested_base": model_requested_base,
        "model_applied_base": model_applied_base,
        "model_requested_sku": model_requested_sku,
        "model_applied_sku": model_applied_sku,
        "ok": voice_ok is not False and model_ok is not False,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION ORCHESTRATOR REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

# Module-level registry for VoiceLive orchestrators (per session)
# This enables scenario updates to reach active VoiceLive sessions
# Uses standard dict but includes cleanup of stale entries
_voicelive_orchestrators: dict[str, "LiveOrchestrator"] = {}
_registry_lock = asyncio.Lock()


def register_voicelive_orchestrator(session_id: str, orchestrator: "LiveOrchestrator") -> None:
    """Register a VoiceLive orchestrator for scenario updates."""
    # Clean up stale entries first (orchestrators that may have been orphaned)
    _cleanup_stale_orchestrators()
    _voicelive_orchestrators[session_id] = orchestrator
    logger.debug(
        "Registered VoiceLive orchestrator | session=%s registry_size=%d",
        session_id,
        len(_voicelive_orchestrators),
    )


def unregister_voicelive_orchestrator(session_id: str) -> None:
    """Unregister a VoiceLive orchestrator when session ends."""
    orchestrator = _voicelive_orchestrators.pop(session_id, None)
    if orchestrator:
        logger.debug(
            "Unregistered VoiceLive orchestrator | session=%s registry_size=%d",
            session_id,
            len(_voicelive_orchestrators),
        )


def get_voicelive_orchestrator(session_id: str) -> "LiveOrchestrator | None":
    """Get the VoiceLive orchestrator for a session."""
    return _voicelive_orchestrators.get(session_id)


def _cleanup_stale_orchestrators() -> int:
    """
    Clean up orchestrators that are no longer valid.

    This catches cases where sessions ended without proper cleanup.
    Returns the number of stale entries removed.
    """
    stale_keys = []
    for session_id, orchestrator in list(_voicelive_orchestrators.items()):
        # Check if orchestrator is still valid (has connection reference)
        if orchestrator.conn is None and orchestrator.agents == {}:
            stale_keys.append(session_id)

    for key in stale_keys:
        _voicelive_orchestrators.pop(key, None)

    if stale_keys:
        logger.debug(
            "Cleaned up %d stale orchestrators from registry | remaining=%d",
            len(stale_keys),
            len(_voicelive_orchestrators),
        )

    return len(stale_keys)


def get_orchestrator_registry_size() -> int:
    """Get current size of orchestrator registry (for monitoring)."""
    return len(_voicelive_orchestrators)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def _auto_load_user_context(system_vars: dict[str, Any]) -> None:
    """
    Auto-load user profile into system_vars if client_id is present but session_profile is missing.

    This ensures that agents receiving handoffs with client_id can access user context
    for personalized conversations, even if the originating agent didn't pass full profile.

    Modifies system_vars in-place.
    """
    if system_vars.get("session_profile"):
        # Already have session_profile, no need to load
        return

    client_id = system_vars.get("client_id")
    if not client_id:
        # Check handoff_context for client_id
        handoff_ctx = system_vars.get("handoff_context", {})
        client_id = handoff_ctx.get("client_id") if isinstance(handoff_ctx, dict) else None

    if not client_id:
        return

    try:
        profile = await load_user_profile_by_client_id(client_id)
        if profile:
            system_vars["session_profile"] = profile
            system_vars["client_id"] = profile.get("client_id", client_id)
            system_vars["customer_intelligence"] = profile.get("customer_intelligence", {})
            system_vars["caller_name"] = profile.get("full_name")
            if profile.get("institution_name"):
                system_vars.setdefault("institution_name", profile["institution_name"])
            logger.info(
                "🔄 Auto-loaded user context for handoff | client_id=%s name=%s",
                client_id,
                profile.get("full_name"),
            )
    except Exception as exc:
        logger.warning("Failed to auto-load user context: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════


class LiveOrchestrator:
    """
    Orchestrates agent switching and tool execution for VoiceLive multi-agent system.

    All tool execution flows through the shared tool registry for centralized management:
    - Handoff tools → trigger agent switching
    - Business tools → execute and return results to model

    GenAI Telemetry:
    - Emits invoke_agent spans for App Insights Agents blade
    - Tracks token usage per agent session
    - Records LLM TTFT (Time To First Token) metrics
    """

    def __init__(
        self,
        conn,
        agents: dict[str, UnifiedAgent],
        handoff_map: dict[str, str] | None = None,
        start_agent: str = "Concierge",
        audio_processor=None,
        messenger=None,
        call_connection_id: str | None = None,
        *,
        transport: str = "acs",
        model_name: str | None = None,
        memo_manager: MemoManager | None = None,
        orchestrator_config: Any | None = None,
    ):
        self.conn = conn
        self.agents = agents
        self._handoff_map = handoff_map or {}
        self.active = start_agent
        self.audio = audio_processor
        self.messenger = messenger
        self._model_name = model_name or "gpt-4o-realtime"
        self.visited_agents: set = set()
        self._pending_greeting: str | None = None
        self._pending_greeting_agent: str | None = None
        # Bounded deque to preserve last N user utterances for better handoff context
        self._user_message_history: deque[str] = deque(maxlen=5)
        # User turns carried over from a *previous* connection (restored from
        # MemoManager in _sync_from_memo_manager). Kept out of the live deque so
        # the recap stays frozen for the connection's lifetime, which is what
        # keeps the rendered instructions constant across turns.
        #
        # These are also injected as native conversation items at bootstrap
        # (start -> _switch_to -> _inject_conversation_history, which sees them
        # because __init__ restores them first), so this block is defence in
        # depth rather than the sole carrier: that injection is best-effort and
        # only ever runs on the switch path. It costs nothing in steady state
        # because it never changes, but it does mean the model currently sees
        # these turns twice — as items and as prose. See _build_conversation_recap.
        self._restored_user_messages: tuple[str, ...] = ()
        self._last_user_message: str | None = None  # Keep for backward compatibility
        # Track assistant responses for conversation history persistence
        self._last_assistant_message: str | None = None
        self.call_connection_id = call_connection_id
        self._call_center_triggered = False
        self._transport = transport
        self._greeting_tasks: set[asyncio.Task] = set()
        self._active_response_id: str | None = None
        # De-dupe assistant transcript deltas by their unique server event_id.
        # Some Voice Live model configs (observed with cascaded / BYOM chat models)
        # re-deliver the same response.audio_transcript.delta event, which the
        # append-based accumulator would otherwise render as doubled words
        # ("Let'sLet's take take"). Bounded to the active response; cleared on
        # response.done and each new user turn.
        self._seen_transcript_delta_ids: set[str] = set()
        self._system_vars: dict[str, Any] = {}
        # Flag to prevent SESSION_UPDATED from cancelling handoff-triggered responses
        self._handoff_response_pending: bool = False
        # Same guard for a greeting the fallback timer already put on the wire.
        # The bootstrap echo races that response, and because a greeting really
        # is in flight the `_active_response_id` guard below does not stop the
        # cancel — the caller hears the opening line cut off mid-word. No fixed
        # timer can rule this out, so the flag is the correlation, not the delay.
        self._greeting_response_pending: bool = False

        # Scenario switch flag — prevents _sync_from_memo_manager from overwriting
        # self.active with stale MemoManager data after an explicit scenario switch
        self._scenario_switch_pending: bool = False

        # Track pending tool outputs to batch them before calling response.create()
        # When model makes multiple tool calls, we queue results and trigger ONE response
        self._pending_tool_outputs: list[tuple[str, str]] = []  # [(call_id, output_json), ...]
        self._response_had_tool_calls: bool = False

        # MemoManager for session state continuity (consistent with CascadeOrchestratorAdapter)
        self._memo_manager: MemoManager | None = memo_manager

        # Unified metrics tracking (tokens, TTFT, turn count)
        self._metrics = OrchestratorMetrics(
            agent_name=start_agent,
            call_connection_id=call_connection_id,
            session_id=getattr(messenger, "session_id", None) if messenger else None,
        )

        # Throttle session context updates to avoid hot path latency
        self._last_session_update_time: float = 0.0
        self._session_update_min_interval: float = 2.0  # Min seconds between updates
        self._pending_session_update: bool = False

        # Number of context-only session.update() calls still awaiting their
        # `session.updated` echo. Context-only updates change *instructions*
        # only; the service echoes them exactly like a fresh bootstrap, so
        # without this correlation _handle_session_updated would tear down
        # audio on every conversational turn. A counter (not a bool) because
        # _update_session_context() runs both from a background task
        # (_schedule_throttled_session_update) and inline from the tool-call
        # path, so two updates can legitimately be in flight at once.
        self._pending_context_session_updates: int = 0

        # Fingerprint of the instruction blob last *successfully* pushed, as
        # (active_agent, sha256). The rendered prompt is ~24KB and over 99% of it
        # is identical from one turn to the next, so re-uploading it after every
        # turn is pure waste. Comparing against this lets _update_session_context()
        # skip the network round-trip entirely when nothing changed.
        self._last_pushed_instructions: tuple[str, str] | None = None

        if self.messenger:
            try:
                self.messenger.set_active_agent(self.active)
            except AttributeError:
                logger.debug("Messenger does not support set_active_agent", exc_info=True)

        # Use case-insensitive lookup for start agent validation
        actual_key, _ = find_agent_by_name(self.agents, self.active)
        if actual_key is None:
            raise ValueError(f"Start agent '{self.active}' not found in registry")
        # Normalize active to the actual key in agents dict
        self.active = actual_key

        # The agent this *connection* was established for. `connect()` binds the
        # generative model (and any BYOM profile) to the start agent and neither
        # can change for the rest of the call, so this is the only value the
        # bound model can legitimately be attributed to. `self.active` is not a
        # substitute: `_sync_from_memo_manager()` below can restore an agent
        # persisted by an *earlier* connection on the same session_id, which is
        # exactly the drift the session contract needs to be able to report.
        self._bound_start_agent: str = actual_key

        # Whether that start agent was *pinned* for this connection by a
        # session-scoped (Quick Tune / Agent Builder) agent, as opposed to being
        # the scenario or deployment default. Read straight off the constructor
        # argument rather than the `_orchestrator_config` property, because the
        # property lazily re-resolves (session lookup + scenario load) and must
        # not be triggered from __init__ on the connection-establishment path.
        #
        # `_sync_from_memo_manager()` below consults it: a deliberately tuned
        # agent is configuration for *this* connection and outranks any agent
        # persisted by a previous one.
        self._start_agent_authoritative: bool = bool(
            getattr(orchestrator_config, "start_agent_authoritative", False)
        )

        # Initialize the tool registry
        initialize_tools()

        # Initialize HandoffService for unified handoff resolution
        self._handoff_service: HandoffService | None = None

        # Seed the resolved scenario config from the caller (the handler already
        # resolved it with the connection's scenario name). Without this the
        # lazy property re-resolves WITHOUT a scenario name and silently returns
        # scenario=None, which drops declarative handoff instructions and routing.
        if orchestrator_config is not None:
            self._cached_orchestrator_config = orchestrator_config

        # Sync state from MemoManager if available
        if self._memo_manager:
            self._sync_from_memo_manager()

    # ═══════════════════════════════════════════════════════════════════════════
    # MEMO MANAGER SYNC (consistent with CascadeOrchestratorAdapter)
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def memo_manager(self) -> MemoManager | None:
        """Return the current MemoManager instance."""
        return self._memo_manager

    @property
    def _session_id(self) -> str | None:
        """
        Get the session ID from memo_manager or messenger.

        Cached property to avoid repeated attribute access.
        """
        if self._memo_manager:
            session_id = getattr(self._memo_manager, "session_id", None)
            if session_id:
                return session_id
        if self.messenger:
            return getattr(self.messenger, "session_id", None)
        return None

    def _websocket_for_errors(self) -> Any | None:
        """Return the session WebSocket used to surface errors, if reachable."""
        if self.messenger is not None:
            return getattr(self.messenger, "_ws", None)
        return None

    @property
    def _orchestrator_config(self):
        """
        Get cached orchestrator config for scenario resolution.

        Normally seeded by the handler via the ``orchestrator_config`` constructor
        argument, so the orchestrator sees exactly the scenario the connection was
        established with.

        The lazy fallback below exists only for callers that construct the
        orchestrator directly. It cannot know the connection's scenario name, so it
        can only find session-scoped scenarios or the ``AGENT_SCENARIO`` default —
        prefer passing ``orchestrator_config``.

        The config is cached per-instance (session lifetime), which is appropriate
        because scenario changes during a call would be disruptive anyway.
        """
        if not hasattr(self, "_cached_orchestrator_config"):
            from apps.artagent.backend.voice.shared.config_resolver import (
                resolve_orchestrator_config,
            )

            self._cached_orchestrator_config = resolve_orchestrator_config(
                session_id=self._session_id
            )
            logger.debug(
                "[LiveOrchestrator] Cached orchestrator config | scenario=%s session=%s",
                self._cached_orchestrator_config.scenario_name,
                self._session_id,
            )
        return self._cached_orchestrator_config

    def _memo_restore_conflict(self, agent_name: str) -> str | None:
        """Say why a MemoManager-restored agent must not take over this connection.

        ``_sync_from_memo_manager()`` runs once, from ``__init__``, at which point
        the Voice Live WebSocket is already established. Restoring an agent is
        therefore never a neutral act: the connection was opened *for* a specific
        start agent, and ``connect()`` has already frozen the generative model and
        the BYOM profile around that agent for the rest of the call.

        Two restores are unsafe, and both were observed as the same production
        report ("I tuned the agent and only the model took"):

        ``session_agent_authoritative``
            A Quick Tune / Agent Builder agent was pinned for this connection
            (see :attr:`_start_agent_authoritative`). It is configuration the
            caller just chose; an agent left behind by an *earlier* connection on
            the same ``session_id`` is stale state and must not displace it —
            doing so silently swaps in the other agent's voice and instructions.

        ``model_bound``
            The restored agent asks for a different Voice Live model than the one
            bound at ``connect()``. The model cannot change mid-call, so the agent
            would be served by a model it did not ask for: the observed failure is
            a session that greets and then never answers again. A wrong-but-
            serviceable agent beats a mute call.

        Everything else is genuine continuity and is allowed — notably resuming on
        the agent a previous connection handed off to, when the bound model can
        still serve it.

        Args:
            agent_name: Registry key of the agent MemoManager wants to restore.

        Returns:
            A short machine-greppable reason, or ``None`` when the restore is safe.
        """
        if agent_name == self.active:
            return None

        if self._start_agent_authoritative:
            return "session_agent_authoritative"

        agent = self.agents.get(agent_name)
        if agent is None:
            return None

        try:
            # self.agents holds UnifiedAgent directly; ``_agent`` is the adapter
            # shape used elsewhere in this file. Same unwrap as _switch_to().
            ua = getattr(agent, "_agent", agent)
            target_deployment = getattr(ua.get_model_for_mode("voicelive"), "deployment_id", None)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Failed to resolve per-agent model for restore check | agent=%s",
                agent_name,
                exc_info=True,
            )
            return None

        if not target_deployment or not self._model_name:
            # Nothing to compare against — never turn an unknown into a refusal.
            return None

        # SKU-tolerant, exactly like the session contract: Azure deployment names
        # append the provisioned tier (``gpt-realtime`` →
        # ``gpt-realtime-datazone-standard``) and that is the same model.
        requested_base, _ = _model_base_and_sku(target_deployment.strip().lower())
        bound_base, _ = _model_base_and_sku(self._model_name.strip().lower())
        if requested_base == bound_base:
            return None

        return "model_bound"

    def _sync_from_memo_manager(self) -> None:
        """
        Sync orchestrator state from MemoManager.
        Called at initialization and optionally at turn boundaries.

        Uses shared sync_state_from_memo for consistency with CascadeOrchestratorAdapter.

        NOTE: For VoiceLive, we intentionally DO NOT sync visited_agents because:
        - VoiceLive starts with a fresh conversation history each connection
        - If we sync visited_agents, we'd show return_greeting but model has no context
        - This causes the model to behave inconsistently (greeting says "welcome back"
          but model doesn't know what happened before)

        The restored ``active_agent`` gets the same per-connection scepticism, one
        step short of the outright refusal ``visited_agents`` gets: it is applied
        only when :meth:`_memo_restore_conflict` finds nothing that makes it unsafe
        for *this* connection. See that method for where the line sits.
        """
        if not self._memo_manager:
            return

        # Use shared sync utility
        state = sync_state_from_memo(
            self._memo_manager,
            available_agents=set(self.agents.keys()),
        )

        # Apply synced state - but NOT visited_agents for VoiceLive
        # VoiceLive conversation history is per-connection, so we always treat as first visit
        if self._scenario_switch_pending:
            # Scenario switch is authoritative — write adapter's active agent to MemoManager
            logger.info(
                "[LiveOrchestrator] Scenario switch pending — writing active to MemoManager | active=%s memo_active=%s",
                self.active,
                state.active_agent,
            )
            sync_state_to_memo(self._memo_manager, active_agent=self.active)
            self._scenario_switch_pending = False
        elif state.active_agent:
            conflict = self._memo_restore_conflict(state.active_agent)
            if conflict:
                logger.warning(
                    "[LiveOrchestrator] active_agent restore refused | reason=%s memo_active=%s "
                    "keeping=%s bound_model=%s — the agent this connection was established for "
                    "stays live",
                    conflict,
                    state.active_agent,
                    self.active,
                    self._model_name,
                )
                # Re-anchor the persisted state on the agent that is actually
                # live, so the next connection on this session_id does not
                # inherit the same stale value and re-run this refusal.
                sync_state_to_memo(self._memo_manager, active_agent=self.active)
            else:
                self.active = state.active_agent
                logger.debug("[LiveOrchestrator] Synced active_agent: %s", self.active)

        # IMPORTANT: Do NOT sync visited_agents for VoiceLive
        # Each VoiceLive connection starts fresh - syncing visited_agents causes
        # return_greeting to be used but model has no conversation context
        # if state.visited_agents:
        #     self.visited_agents = state.visited_agents
        #     logger.debug("[LiveOrchestrator] Synced visited_agents: %s", self.visited_agents)
        logger.debug(
            "[LiveOrchestrator] Skipping visited_agents sync - VoiceLive starts fresh each connection"
        )

        if state.system_vars:
            self._system_vars.update(state.system_vars)
            logger.debug("[LiveOrchestrator] Synced system_vars")

        # Restore user message history if available (for session continuity)
        try:
            stored_history = self._memo_manager.get_value_from_corememory("user_message_history")
            if stored_history and isinstance(stored_history, list):
                self._user_message_history = deque(stored_history, maxlen=5)
                # Snapshot separately so the recap stays frozen for this
                # connection: turns spoken *on* this connection are appended to
                # the deque later and must NOT end up here, because the service
                # already holds those as conversation items.
                self._restored_user_messages = tuple(self._user_message_history)
                if stored_history:
                    self._last_user_message = stored_history[-1]
                logger.debug(
                    "[LiveOrchestrator] Restored %d messages from history",
                    len(stored_history),
                )
        except Exception:
            logger.debug("Failed to restore user message history", exc_info=True)

        # Handle pending handoff if any
        if state.pending_handoff:
            target = state.pending_handoff.get("target_agent")
            if target and target in self.agents:
                # Same per-connection check as the active_agent restore above:
                # a queued handoff is memo state too, and landing on an agent the
                # bound model cannot serve is a mute call however it was reached.
                conflict = self._memo_restore_conflict(target)
                if conflict:
                    logger.warning(
                        "[LiveOrchestrator] Pending handoff refused | reason=%s target=%s "
                        "keeping=%s bound_model=%s",
                        conflict,
                        target,
                        self.active,
                        self._model_name,
                    )
                else:
                    logger.info("[LiveOrchestrator] Pending handoff detected: %s", target)
                    self.active = target
                # Clear the pending handoff either way — leaving it queued would
                # just re-run the same refusal on the next connection.
                sync_state_to_memo(
                    self._memo_manager, active_agent=self.active, clear_pending_handoff=True
                )

    def _sync_to_memo_manager(self) -> None:
        """
        Sync orchestrator state back to MemoManager.
        Called at turn boundaries to persist state.

        Uses shared sync_state_to_memo for consistency with CascadeOrchestratorAdapter.
        """
        if not self._memo_manager:
            return

        # Use shared sync utility
        sync_state_to_memo(
            self._memo_manager,
            active_agent=self.active,
            visited_agents=self.visited_agents,
            system_vars=self._system_vars,
        )

        # Sync last user message (VoiceLive-specific) for backward compatibility
        if hasattr(self._memo_manager, "last_user_message") and self._last_user_message:
            self._memo_manager.last_user_message = self._last_user_message

        # Persist user message history for session continuity
        if self._user_message_history:
            try:
                self._memo_manager.set_corememory(
                    "user_message_history", list(self._user_message_history)
                )
            except Exception:
                logger.debug("Failed to persist user message history", exc_info=True)

        logger.debug("[LiveOrchestrator] Synced state to MemoManager")

    def cleanup(self) -> None:
        """
        Clean up orchestrator resources to prevent memory leaks.

        This should be called when the VoiceLive session ends. It:
        - Cancels all pending greeting tasks
        - Clears references to agents and connections
        - Clears user message history deque
        - Resets all stateful tracking variables

        Note: This method is synchronous and does not await any coroutines.
        For async cleanup, use the handler's stop() method which calls this.
        """
        # Cancel all pending greeting tasks
        self._cancel_pending_greeting_tasks()

        # Clear agents registry reference
        self.agents = {}
        self._handoff_map = {}

        # Clear connection reference (do not close - handler owns it)
        self.conn = None

        # Clear messenger reference to break circular refs
        self.messenger = None
        self.audio = None

        # Clear memo manager reference (handler/endpoint owns lifecycle)
        self._memo_manager = None

        # Clear handoff service
        self._handoff_service = None

        # Clear user message history
        self._user_message_history.clear()
        self._restored_user_messages = ()
        self._last_pushed_instructions = None
        self._last_user_message = None
        self._last_assistant_message = None

        # Clear pending greeting state
        self._pending_greeting = None
        self._pending_greeting_agent = None

        # Reset tracking variables
        self._active_response_id = None
        self._system_vars.clear()
        self.visited_agents.clear()

        logger.debug("[LiveOrchestrator] Cleanup complete")

    def update_scenario(
        self,
        agents: dict[str, UnifiedAgent],
        handoff_map: dict[str, str],
        start_agent: str | None = None,
        scenario_name: str | None = None,
        *,
        scenario: Any | None = None,
    ) -> None:
        """
        Update the orchestrator with a new scenario configuration.

        This is called when the user changes scenarios mid-session via the UI.
        The orchestrator's agents and handoff map are updated to reflect
        the new scenario without restarting the VoiceLive connection.

        Args:
            agents: New UnifiedAgent registry (no adapter needed)
            handoff_map: New handoff routing map
            start_agent: Optional new start agent to switch to
            scenario_name: Optional scenario name for logging

        Keyword Args:
            scenario: Optional ``ScenarioConfig`` for the new scenario. When given,
                the cached config is re-seeded with it so handoff instructions and
                routing follow the new scenario. When omitted the cache is simply
                dropped, which forces a re-resolve that cannot see a scenario name.
        """
        old_agents = list(self.agents.keys())
        old_active = self.active
        needs_session_update = False

        # Update agents registry
        self.agents = agents

        # Update handoff map
        self._handoff_map = handoff_map

        # Clear cached HandoffService so it's recreated with new scenario
        self._handoff_service = None

        # A new scenario means new handoff instructions, so the fingerprint of the
        # last pushed blob no longer describes what the session should be running.
        self._last_pushed_instructions = None

        # Refresh the cached orchestrator config for the new scenario.
        # CRITICAL: Without this, _update_session_context() uses the OLD cached config
        # and injects the wrong handoff instructions for the new scenario.
        if scenario is not None:
            from apps.artagent.backend.voice.shared.config_resolver import (
                OrchestratorConfigResult,
            )

            self._cached_orchestrator_config = OrchestratorConfigResult(
                start_agent=start_agent or self.active,
                agents=agents,
                handoff_map=handoff_map,
                scenario=scenario,
                scenario_name=scenario_name or getattr(scenario, "name", None),
                template_vars=dict(getattr(scenario, "global_template_vars", None) or {}),
            )
        elif hasattr(self, "_cached_orchestrator_config"):
            delattr(self, "_cached_orchestrator_config")

        # Clear visited agents for fresh scenario experience
        self.visited_agents.clear()

        # Always switch to start_agent when a new scenario is explicitly selected
        if start_agent:
            if start_agent != self.active:
                self.active = start_agent
                needs_session_update = True
                logger.info(
                    "🔄 VoiceLive switching to scenario start_agent | from=%s to=%s scenario=%s",
                    old_active,
                    start_agent,
                    scenario_name or "(unknown)",
                )
            else:
                # Same agent but scenario changed - still need to update session
                needs_session_update = True
        elif self.active not in agents:
            # Current agent not in new scenario - switch to first available
            available = list(agents.keys())
            if available:
                self.active = available[0]
                needs_session_update = True
                logger.warning(
                    "🔄 VoiceLive current agent not in scenario, switching | from=%s to=%s",
                    old_active,
                    self.active,
                )

        logger.info(
            "🔄 VoiceLive scenario updated | old_agents=%s new_agents=%s active=%s scenario=%s",
            old_agents,
            list(agents.keys()),
            self.active,
            scenario_name or "(unknown)",
        )

        # Mark scenario switch pending so _sync_from_memo_manager doesn't
        # overwrite self.active with stale data from a previous MemoManager snapshot
        self._scenario_switch_pending = True

        # CRITICAL: Trigger a session update to apply the new agent's instructions
        # This ensures VoiceLive uses the correct system prompt for the new agent
        if needs_session_update:
            self._schedule_scenario_session_update()

    def _schedule_scenario_session_update(self) -> None:
        """
        Schedule a full agent session update after scenario change.

        This applies the new agent's complete session configuration (voice, tools,
        VAD, instructions) - not just instructions. This is critical for scenario
        switches to take effect properly in VoiceLive.

        This runs in the background to avoid blocking the scenario update call.
        """

        async def _do_update():
            try:
                agent = self.agents.get(self.active)
                if not agent:
                    logger.warning(
                        "🔄 VoiceLive scenario update failed - agent not found | agent=%s",
                        self.active,
                    )
                    return

                # Build system vars for the new agent
                system_vars = dict(self._system_vars)
                system_vars["active_agent"] = self.active

                # Get session_id for the apply call
                session_id = self._session_id

                # CRITICAL: Apply the FULL agent session config, not just instructions
                # This includes voice, tools, VAD settings, etc.
                # This is the same as what _switch_to() does during handoffs
                # Drop any outstanding context-only credits first: this echo is a
                # genuine bootstrap and must run the audio reset, even if a
                # throttled context update is still unaccounted for.
                self._pending_context_session_updates = 0
                # apply_voicelive_session pushes its own instructions, so whatever
                # we last fingerprinted no longer describes the live session.
                self._last_pushed_instructions = None
                await agent.apply_voicelive_session(
                    self.conn,
                    system_vars=system_vars,
                    say=None,  # Don't trigger a greeting on scenario switch
                    session_id=session_id,
                    call_connection_id=self.call_connection_id,
                )

                # Update messenger's active agent
                if self.messenger:
                    try:
                        self.messenger.set_active_agent(self.active)
                    except AttributeError:
                        pass

                logger.info(
                    "🔄 VoiceLive session fully updated for scenario change | agent=%s session=%s",
                    self.active,
                    session_id,
                )
            except Exception:
                logger.warning("Failed to update session after scenario change", exc_info=True)

        # Schedule on the event loop
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(_do_update(), loop)
        except RuntimeError:
            # No running loop - try create_task if we're in an async context
            try:
                asyncio.create_task(_do_update())
            except RuntimeError:
                logger.warning("Cannot schedule session update - no event loop available")

    async def _inject_conversation_history(self) -> None:
        """
        Inject conversation history as text items into VoiceLive conversation.

        CRITICAL FOR CONTEXT RETENTION:
        VoiceLive processes audio natively, but the model can "forget" context
        between turns. By injecting the conversation history as explicit text
        items, we give the model concrete text to reference.

        This should be called:
        - After session.update on agent switch (_switch_to)
        - Before the first response is triggered

        The text items become part of the conversation context that the model
        sees for all subsequent responses.
        """
        if not self.conn or not self._user_message_history:
            return

        try:
            # Inject each historical user message as a text conversation item
            # This establishes explicit text context for the model
            for msg in self._user_message_history:
                if not msg or not msg.strip():
                    continue

                # Create user message item with text content
                text_part = InputTextContentPart(text=msg)
                user_item = UserMessageItem(content=[text_part])

                # Add to conversation
                await self.conn.conversation.item.create(item=user_item)

            # Also inject last assistant message if available
            if self._last_assistant_message:
                # Create assistant message with text content
                text_part = OutputTextContentPart(text=self._last_assistant_message)
                assistant_item = AssistantMessageItem(content=[text_part])
                await self.conn.conversation.item.create(item=assistant_item)

            logger.info(
                "[LiveOrchestrator] Injected %d conversation items for context",
                len(self._user_message_history) + (1 if self._last_assistant_message else 0),
            )
        except Exception:
            logger.debug("Failed to inject conversation history", exc_info=True)

    def _refresh_session_context(self) -> None:
        """
        Refresh session context from MemoManager at the start of each turn.

        This picks up any external updates such as:
        - CRM lookups completed by tools
        - Session profile updates from MFA verification
        - Slot values filled by previous turns
        - Tool outputs from business logic

        Called from _handle_transcription_completed to ensure each turn
        has fresh context for prompt rendering.
        """
        if not self._memo_manager:
            return

        try:
            # Refresh session profile if updated externally
            session_profile = self._memo_manager.get_value_from_corememory("session_profile")
            if session_profile and isinstance(session_profile, dict):
                # Update system_vars with fresh profile data
                self._system_vars["session_profile"] = session_profile
                self._system_vars["client_id"] = session_profile.get("client_id")
                self._system_vars["caller_name"] = session_profile.get("full_name")
                self._system_vars["customer_intelligence"] = session_profile.get(
                    "customer_intelligence", {}
                )
                if session_profile.get("institution_name"):
                    self._system_vars["institution_name"] = session_profile["institution_name"]

            # Refresh slots (collected information from previous turns)
            slots = self._memo_manager.get_context("slots", {})
            if slots:
                self._system_vars["slots"] = slots
                self._system_vars["collected_information"] = slots

            # Refresh tool outputs for context continuity
            tool_outputs = self._memo_manager.get_context("tool_outputs", {})
            if tool_outputs:
                self._system_vars["tool_outputs"] = tool_outputs

            logger.debug("[LiveOrchestrator] Refreshed session context from MemoManager")
        except Exception:
            logger.debug("Failed to refresh session context", exc_info=True)

    async def _update_session_context(self) -> None:
        """
        Push the active agent's instructions onto the live VoiceLive session.

        Called before a model response so the instructions reflect anything that
        changed out-of-band (slots written by a tool, a refreshed session profile,
        a new scenario handoff block).

        The rendered blob is large (~24KB for a typical agent) and almost always
        identical to the previous turn's, so the push is gated on a fingerprint of
        the fully-rendered text: when nothing changed, no ``session.update()`` is
        sent at all. In steady state that means zero per-turn uploads.

        The instructions include:
        - Base agent instructions (from prompt template)
        - Scenario handoff instructions
        - Cross-connection context that the service does not hold itself
          (see :meth:`_build_conversation_recap`)
        """
        if not self.conn or not self.active:
            return

        agent = self.agents.get(self.active)
        if not agent:
            return

        try:
            # Build context for prompt rendering
            context_vars = dict(self._system_vars)
            context_vars["active_agent"] = self.active

            # Add conversation context from message history
            if self._user_message_history:
                context_vars["recent_user_messages"] = list(self._user_message_history)
                if len(self._user_message_history) > 1:
                    context_vars["conversation_summary"] = " → ".join(self._user_message_history)

            # Add last assistant response for context continuity
            if self._last_assistant_message:
                context_vars["last_assistant_response"] = self._last_assistant_message

            # ``self.agents`` holds UnifiedAgent instances directly (see
            # update_scenario: "no adapter needed"). Older adapter-wrapped agents
            # exposed the UnifiedAgent as ``_agent``, so unwrap defensively —
            # matching _switch_to/_init_mcp_for_agent. Reaching for ``_agent``
            # unconditionally raised AttributeError on every turn, which silently
            # disabled instruction refresh and conversation recap entirely.
            ua = getattr(agent, "_agent", agent)

            # Render base instructions from agent prompt template
            base_instructions = ua.render_prompt(context_vars) or ""

            # Inject handoff instructions from scenario configuration
            # Use the cached orchestrator config (supports both file-based and session-scoped)
            config = self._orchestrator_config
            if config.scenario and ua.name:
                # Use scenario.build_handoff_instructions directly (works for session scenarios)
                handoff_instructions = config.scenario.build_handoff_instructions(ua.name)
                if handoff_instructions:
                    base_instructions = (
                        f"{base_instructions}\n\n{handoff_instructions}"
                        if base_instructions
                        else handoff_instructions
                    )
                    logger.info(
                        "[LiveOrchestrator] Injected handoff instructions | agent=%s scenario=%s len=%d",
                        ua.name,
                        config.scenario_name,
                        len(handoff_instructions),
                    )
            else:
                logger.debug(
                    "[LiveOrchestrator] No scenario or agent name for handoff instructions | scenario=%s agent=%s",
                    config.scenario_name if config.scenario else None,
                    getattr(ua, "name", None),
                )

            # Build conversation recap to append to instructions
            # This is critical for realtime models which tend to forget context
            conversation_recap = self._build_conversation_recap()

            # Combine base instructions with conversation recap
            if conversation_recap:
                updated_instructions = f"{base_instructions}\n\n{conversation_recap}"
            else:
                updated_instructions = base_instructions

            if not updated_instructions:
                return

            # Nothing changed since the last successful push, so the round-trip
            # would be a pure no-op: the same ~24KB blob back onto the wire, plus
            # a `session.updated` echo the handler then has to classify. Skip it.
            #
            # CRITICAL: return *before* touching _pending_context_session_updates.
            # No update means no echo, so crediting the counter here would leave a
            # dangling credit that the next genuine bootstrap echo would consume —
            # and that echo would then skip the audio reset it needs.
            fingerprint = (
                self.active,
                hashlib.sha256(updated_instructions.encode("utf-8")).hexdigest(),
            )
            if fingerprint == self._last_pushed_instructions:
                logger.debug(
                    "[LiveOrchestrator] Session instructions unchanged - skipping update | agent=%s",
                    self.active,
                )
                return

            # Update session with new instructions
            from azure.ai.voicelive.models import RequestSession

            # Mark this as a context-only update *before* it goes on the wire.
            # The `session.updated` echo can arrive before this coroutine
            # resumes, so incrementing afterwards would race the handler.
            self._pending_context_session_updates += 1
            try:
                await self.conn.session.update(
                    session=RequestSession(instructions=updated_instructions)
                )
            except Exception:
                # The service never applied it, so no echo is coming. Hand the
                # credit back, otherwise a later genuine bootstrap echo would be
                # misread as this one and skip the audio reset it needs.
                self._pending_context_session_updates = max(
                    0, self._pending_context_session_updates - 1
                )
                raise

            # Only record the fingerprint once the service has actually taken the
            # payload. Caching a failed push would suppress the retry and leave
            # the session running on stale instructions.
            self._last_pushed_instructions = fingerprint

            logger.debug(
                "[LiveOrchestrator] Updated session | agent=%s history_len=%d slots=%s",
                self.active,
                len(self._user_message_history),
                list(context_vars.get("slots", {}).keys()) if context_vars.get("slots") else [],
            )
        except Exception as exc:
            # A rejected session.update (unsupported voice/model, expired auth)
            # otherwise looks like "my settings silently didn't apply".
            info = classify_voice_error(
                exc,
                source="voicelive",
                model=self._model_name,
                agent=self.active,
            )
            logger.warning(
                "[LiveOrchestrator] Failed to update session context | agent=%s %s",
                self.active,
                info.log_summary(),
                exc_info=True,
            )
            await emit_voice_error(
                self._websocket_for_errors(),
                info,
                session_id=self._session_id,
                call_id=self.call_connection_id,
            )

    async def apply_live_session_settings(
        self,
        *,
        turn_detection: dict[str, Any] | None = None,
        voice: dict[str, Any] | None = None,
    ) -> bool:
        """
        Push VAD / voice tweaks to the live VoiceLive connection without a reconnect.

        VoiceLive supports partial ``session.update`` for ``turn_detection`` and
        ``voice`` (the generative model is the only thing bound at connect()).
        The active per-session agent's stored config is also mutated so the change
        survives subsequent full session updates (e.g. on the next agent switch).

        Returns True if an update was pushed, False if nothing live to update.
        """
        if not self.conn or not self.active:
            return False
        agent = self.agents.get(self.active)
        if not agent:
            return False
        ua = getattr(agent, "_agent", agent)

        # Mutate the per-session agent so the tweak persists across turns.
        if turn_detection:
            sess = dict(ua.session or {})
            td = dict(sess.get("turn_detection") or {})
            for key in ("type", "threshold", "silence_duration_ms", "prefix_padding_ms"):
                if turn_detection.get(key) is not None:
                    td[key] = turn_detection[key]
            sess["turn_detection"] = td
            ua.session = sess
        if voice and ua.voice is not None:
            # Apply every field the caller actually set. Ignoring style/pitch here
            # made those Quick Tune controls silent no-ops: the UI reported
            # success while the live session kept the previous voice settings.
            for field in ("name", "rate", "style", "pitch"):
                value = voice.get(field)
                if value:
                    setattr(ua.voice, field, value)

        try:
            from azure.ai.voicelive.models import RequestSession
        except ImportError:
            logger.warning("VoiceLive SDK unavailable; cannot push live settings")
            return False

        kwargs: dict[str, Any] = {}
        if turn_detection:
            vad = ua.build_voicelive_vad()
            if vad is not None:
                kwargs["turn_detection"] = vad
        if voice:
            voice_payload = ua.build_voicelive_voice()
            if voice_payload is not None:
                kwargs["voice"] = voice_payload

        if not kwargs:
            return False

        await self.conn.session.update(session=RequestSession(**kwargs))
        logger.info(
            "[LiveOrchestrator] Pushed live session settings | agent=%s keys=%s voice=%s",
            self.active,
            list(kwargs.keys()),
            _voice_identity(kwargs.get("voice")),
        )
        return True

    def _build_conversation_recap(self) -> str:
        """
        Build the context block that VoiceLive's own conversation state does not
        reliably cover.

        Deliberately narrow. VoiceLive keeps conversation state server-side: every
        user audio turn becomes a conversation item (the orchestrator handles
        ``conversation.item.input_audio_transcription.completed``), every assistant
        turn is an item, and tool results are pushed as ``FunctionCallOutputItem``
        in :meth:`_handle_response_done`. Re-listing any of that in the
        instructions is duplication that costs a ~24KB upload every turn, so the
        turn-by-turn transcript and the "your last response" recap are gone.

        What remains:

        - **Turns restored from a previous connection.** These *are* also injected
          as native conversation items at bootstrap — ``start()`` calls
          :meth:`_switch_to`, which calls :meth:`_inject_conversation_history`,
          and ``__init__`` has already restored them by then. So this block is
          defence in depth, not the sole carrier. It is retained because that
          injection is best-effort (its failures are swallowed at debug level) and
          only ever runs on the switch path — :meth:`_inject_conversation_history`
          has exactly one call site and never runs mid-call. Being frozen at
          restore time, it costs nothing in steady state.

          FOLLOW-UP: because the injection already covers them, the model
          currently sees these turns twice — as conversation items and as prose
          here. This block is plausibly removable; that is a separate change with
          its own verification, not a drive-by cleanup.

        - **Collected slots.** Written from tool results into MemoManager and
          re-read after a reconnect, by which point the originating
          ``function_call_output`` items are gone. Nothing re-injects these the
          way ``_inject_conversation_history`` re-injects turns, and no agent
          prompt template renders them, so this block really is their only channel.

        Both are constant or change only when a tool writes a slot, which is what
        lets the fingerprint check in :meth:`_update_session_context` short-circuit
        the per-turn push.
        """
        parts = []

        # Carried over from a previous connection only — turns spoken on this
        # connection are already conversation items on the service side.
        if self._restored_user_messages:
            parts.append("## EARLIER IN THIS CONVERSATION")
            parts.append("Before this point the user told you:")
            for i, msg in enumerate(self._restored_user_messages, 1):
                parts.append(f'  {i}. "{msg}"')
            parts.append("")
            parts.append(
                "IMPORTANT: Do NOT ask the user to repeat information they've already provided."
            )

        # Add collected slots/information
        slots = self._system_vars.get("slots", {})
        if slots:
            if parts:
                parts.append("")
            parts.append("## COLLECTED INFORMATION")
            for key, value in slots.items():
                if value:
                    parts.append(f"  - {key}: {value}")

        return "\n".join(parts) if parts else ""

    def _schedule_throttled_session_update(self) -> None:
        """
        Schedule a throttled session context refresh in the background.

        The network push itself is now change-gated in
        :meth:`_update_session_context`, so in steady state this schedules work
        that sends nothing. The throttle still earns its keep: re-rendering the
        agent's Jinja prompt is ~24KB of string work, and both
        :meth:`_refresh_session_context` and the render would otherwise run on
        every ``response.done``. It also bounds bursts when the tool-call path
        pushes an update inline at the same time.
        """
        now = time.perf_counter()
        elapsed = now - self._last_session_update_time

        # Only update if enough time has passed OR we have a pending update from transcription
        if elapsed < self._session_update_min_interval and not self._pending_session_update:
            logger.debug(
                "[LiveOrchestrator] Skipping session update - throttled (%.1fs < %.1fs)",
                elapsed,
                self._session_update_min_interval,
            )
            return

        self._pending_session_update = False
        self._last_session_update_time = now

        # Refresh context first (fast, local operation)
        self._refresh_session_context()

        # Schedule the actual session update as a background task
        # This prevents blocking the event loop
        async def _do_session_update():
            try:
                await self._update_session_context()
            except Exception:
                logger.debug("Background session update failed", exc_info=True)

        asyncio.create_task(_do_session_update())

    def _schedule_background_sync(self) -> None:
        """
        Schedule MemoManager sync in background to avoid hot path latency.

        The sync is fire-and-forget - failures are logged but don't block.
        """
        if not self._memo_manager:
            return

        def _do_sync():
            try:
                self._sync_to_memo_manager()
            except Exception:
                logger.debug("Background MemoManager sync failed", exc_info=True)

        # Schedule on next event loop iteration to not block current coroutine
        asyncio.get_event_loop().call_soon(_do_sync)

    # ═══════════════════════════════════════════════════════════════════════════
    # HANDOFF RESOLUTION
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def handoff_service(self) -> HandoffService:
        """
        Get or create the HandoffService for unified handoff resolution.

        The service is lazily created on first access and uses the cached
        orchestrator config (supports both file-based and session-scoped scenarios).
        """
        if self._handoff_service is None:
            # Use cached orchestrator config for scenario resolution
            config = self._orchestrator_config

            self._handoff_service = HandoffService(
                scenario_name=config.scenario_name,
                handoff_map=self.handoff_map,
                agents=self.agents,
                memo_manager=self._memo_manager,
                scenario=config.scenario,  # Pass scenario object for session-scoped scenarios
            )
        return self._handoff_service

    def get_handoff_target(self, tool_name: str) -> str | None:
        """
        Get the target agent for a handoff tool.

        Uses the static handoff_map. For runtime resolution with
        scenario context, use HandoffService directly.
        """
        return self._handoff_map.get(tool_name)

    @property
    def handoff_map(self) -> dict[str, str]:
        """Get the current handoff map."""
        return self._handoff_map

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════════

    async def start(self, system_vars: dict | None = None):
        """Apply initial agent session and trigger an intro response."""
        with tracer.start_as_current_span(
            "voicelive_orchestrator.start",
            kind=trace.SpanKind.INTERNAL,
            attributes=create_service_handler_attrs(
                service_name="LiveOrchestrator.start",
                call_connection_id=self.call_connection_id,
                session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
            ),
        ) as start_span:
            start_span.set_attribute("voicelive.start_agent", self.active)
            start_span.set_attribute("voicelive.agent_count", len(self.agents))
            logger.info("[Orchestrator] Starting with agent: %s", self.active)
            orch_start_ts = time.perf_counter()
            self._system_vars = dict(system_vars or {})

            # Initialize MCP servers for the active agent (non-blocking)
            t0 = time.perf_counter()
            await self._init_mcp_for_agent(self.active)
            mcp_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            await self._switch_to(self.active, self._system_vars)
            switch_ms = (time.perf_counter() - t0) * 1000

            total_ms = (time.perf_counter() - orch_start_ts) * 1000
            logger.info(
                "[VoiceLive Startup] orchestrator.start total_ms=%.1f | mcp_init_ms=%.1f switch_to_ms=%.1f | agent=%s",
                total_ms,
                mcp_ms,
                switch_ms,
                self.active,
            )
            start_span.set_attribute("voicelive.orch_start_ms", round(total_ms, 2))
            start_span.set_status(trace.StatusCode.OK)

    async def _init_mcp_for_agent(self, agent_name: str) -> None:
        """
        Initialize MCP server connections for an agent's configured servers.

        Connects to MCP servers listed in the agent's mcp_servers field.
        Tools from connected servers become available for the session.

        Args:
            agent_name: Name of the agent to initialize MCP for
        """
        if not self._memo_manager:
            return

        agent = self.agents.get(agent_name)
        if not agent or not agent.mcp_servers:
            return

        try:
            from apps.artagent.backend.registries.toolstore.mcp import get_mcp_configs_for_agent

            configs = get_mcp_configs_for_agent(agent.mcp_servers)
            if not configs:
                logger.debug(
                    "[LiveOrchestrator] No MCP servers configured for agent %s",
                    agent_name,
                )
                return

            results = await self._memo_manager.init_mcp_servers(configs)

            connected = [name for name, success in results.items() if success]
            failed = [name for name, success in results.items() if not success]

            if connected:
                logger.info(
                    "[LiveOrchestrator] MCP servers connected for %s: %s",
                    agent_name,
                    connected,
                )
            if failed:
                logger.warning(
                    "[LiveOrchestrator] MCP servers failed for %s: %s",
                    agent_name,
                    failed,
                )
        except Exception as exc:
            logger.warning(
                "[LiveOrchestrator] MCP initialization failed for %s: %s",
                agent_name,
                exc,
            )

    async def handle_event(self, event):
        """Route VoiceLive events to audio + handoff logic."""
        et = event.type

        if et == ServerEventType.SESSION_UPDATED:
            await self._handle_session_updated(event)

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            await self._handle_speech_started()

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            await self._handle_speech_stopped()

        elif et == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            await self._handle_transcription_completed(event)

        elif et == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
            await self._handle_transcription_delta(event)

        elif et == ServerEventType.RESPONSE_AUDIO_DELTA:
            if self.audio:
                await self.audio.queue_audio(event.delta)

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
            await self._handle_transcript_delta(event)

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            await self._handle_transcript_done(event)

        elif et == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            await self._execute_tool_call(
                call_id=getattr(event, "call_id", None),
                name=getattr(event, "name", None),
                args_json=getattr(event, "arguments", None),
            )

        elif et == ServerEventType.RESPONSE_DONE:
            await self._handle_response_done(event)

        elif et == ServerEventType.ERROR:
            err = getattr(event, "error", None)
            code = getattr(err, "code", None)
            message = getattr(err, "message", "unknown")
            # Benign cancel-race: a barge-in / response.cancel lands just after the
            # response already finished, so there is no active response to cancel.
            # The handler already suppresses these; mirror that here so we don't
            # emit a noisy duplicate ERROR for an expected condition.
            if code in _BENIGN_ERROR_CODES:
                logger.info("VoiceLive benign cancel-race ignored | code=%s", code)
            else:
                # code/type/param identify WHICH field the service rejected. A
                # rejected `voice` (unsupported name or style) or `model` fails the
                # whole session.update, so without these fields the symptom is just
                # "my settings didn't apply" with no way to tell why. The handler
                # owns delivery to the client; here we only enrich the log.
                info = classify_voicelive_server_error(
                    code,
                    message,
                    details=getattr(err, "param", None),
                    model=self._model_name,
                    agent=self.active,
                )
                logger.error(
                    "VoiceLive error: %s | code=%s type=%s param=%s agent=%s model=%s "
                    "classified=%s remediation=%s",
                    message,
                    code,
                    getattr(err, "type", None),
                    getattr(err, "param", None),
                    self.active,
                    self._model_name,
                    info.code if info else None,
                    info.remediation if info else None,
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _verify_session_contract(self, session_obj) -> dict[str, Any] | None:
        """Confirm the voice/model the service accepted match what we asked for.

        Emits a single KPI line per ``session.updated`` so a call can be audited
        after the fact: ``session_contract_ok`` means the selected TTS voice and
        the selected (possibly BYOM) model are the ones actually driving the
        session; ``session_contract_mismatch`` means the service quietly
        substituted or dropped one of them.

        The service-side comparison from
        :func:`verify_voicelive_session_contract` is returned verbatim (``ok``
        keeps meaning "the service accepted the voice and model we asked for")
        and enriched with the two *local* divergences that explain most
        "my tuning didn't take" reports, neither of which the echo can show:

        ``bound_agent`` / ``active_agent`` / ``agent_ok``
            The connection was established for ``bound_agent``; if a stale
            ``active_agent`` was restored from a previous connection on the same
            session, the live agent — and therefore its voice and instructions —
            is not the one that was tuned.
        ``connection_model`` / ``agent_requested_model`` / ``model_override_ignored``
            Voice Live binds the model at ``connect()`` and cannot change it
            mid-call, so an agent that asks for a different ``voicelive_model``
            is silently served by the bound one.

        ``overall_ok`` is the aggregate to render: the service contract held
        *and* neither local divergence is present.
        """
        if session_obj is None:
            return None

        agent = self.agents.get(self.active)
        if agent is None:
            return None
        ua = getattr(agent, "_agent", agent)

        try:
            requested_voice = ua.build_voicelive_voice()
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to build requested voice for verification", exc_info=True)
            return None

        result = verify_voicelive_session_contract(
            requested_voice=requested_voice,
            requested_model=self._model_name,
            session_obj=session_obj,
        )

        bound_agent = getattr(self, "_bound_start_agent", None)
        agent_ok: bool | None = None
        if bound_agent is not None:
            agent_ok = bound_agent == self.active

        agent_requested_model: str | None = None
        try:
            target_model = ua.get_model_for_mode("voicelive")
            agent_requested_model = getattr(target_model, "deployment_id", None)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to resolve per-agent model for verification", exc_info=True)

        model_override_ignored = bool(
            agent_requested_model and self._model_name and agent_requested_model != self._model_name
        )

        result.update(
            {
                "active_agent": self.active,
                "bound_agent": bound_agent,
                "agent_ok": agent_ok,
                "connection_model": self._model_name,
                "agent_requested_model": agent_requested_model,
                "model_override_ignored": model_override_ignored,
                "overall_ok": bool(
                    result["ok"] and agent_ok is not False and not model_override_ignored
                ),
            }
        )

        span = trace.get_current_span()
        if result["voice_applied"] is not None:
            span.set_attribute("voicelive.voice_applied", result["voice_applied"])
        if result["voice_requested"] is not None:
            span.set_attribute("voicelive.voice_requested", result["voice_requested"])
        span.set_attribute("voicelive.session_contract_ok", bool(result["ok"]))
        span.set_attribute("voicelive.session_contract_overall_ok", result["overall_ok"])
        if agent_ok is False:
            span.set_attribute("voicelive.bound_agent", bound_agent or "")

        if result["ok"]:
            logger.info(
                "[VoiceLive] session_contract_ok | agent=%s voice=%s model=%s sku=%s",
                self.active,
                result["voice_applied"] or result["voice_requested"],
                result["model_applied"] or result["model_requested"],
                result["model_applied_sku"] or result["model_requested_sku"] or "-",
            )
        else:
            logger.warning(
                "[VoiceLive] session_contract_mismatch | agent=%s "
                "voice_requested=%s voice_applied=%s model_requested=%s model_applied=%s "
                "— the service did not accept the selected configuration",
                self.active,
                result["voice_requested"],
                result["voice_applied"],
                result["model_requested"],
                result["model_applied"],
            )

        # Logged separately from the service contract: the session config is
        # exactly what we asked for, we are simply asking on behalf of the wrong
        # agent. Folding it into the line above would misattribute the cause.
        if agent_ok is False:
            logger.warning(
                "[VoiceLive] session_agent_drift | bound=%s active=%s — the live agent is not "
                "the one this connection was established for, so its voice and instructions "
                "are not the tuned ones",
                bound_agent,
                self.active,
            )
        if model_override_ignored:
            logger.warning(
                "[VoiceLive] session_model_override_ignored | agent=%s requested=%s bound=%s — "
                "Voice Live binds the model at connect() and cannot change it mid-call",
                self.active,
                agent_requested_model,
                self._model_name,
            )
        return result

    async def _handle_session_updated(self, event) -> None:
        """Handle SESSION_UPDATED event."""
        session_obj = getattr(event, "session", None)
        session_id = getattr(session_obj, "id", "unknown") if session_obj else "unknown"
        voice_info = getattr(session_obj, "voice", None) if session_obj else None

        # Consume exactly one context-only credit. `_update_session_context()`
        # refreshes *instructions* after every turn, and the service echoes that
        # back as `session.updated` ~200ms later — while TTS audio is still
        # draining. Treating that echo as a bootstrap would stop playback
        # mid-sentence and spam the UI with a SESSION UPDATED entry per turn.
        context_only = self._pending_context_session_updates > 0
        if context_only:
            self._pending_context_session_updates -= 1
            logger.debug("Session context refreshed: %s | voice=%s", session_id, voice_info)
        else:
            logger.info("Session ready: %s | voice=%s", session_id, voice_info)

        # Keep the contract KPI on every echo — a service-side voice/model
        # substitution is just as worth catching on a context refresh.
        contract = self._verify_session_contract(session_obj)

        if context_only:
            # Nothing was reconfigured, so there is nothing to re-bootstrap:
            # leave playback, capture, any in-flight response, and the
            # pending-greeting / handoff state exactly as they are.
            #
            # The contract is deliberately NOT broadcast here either: a
            # context-only refresh happens after every assistant turn, so
            # emitting an envelope would restore the per-turn UI spam that the
            # early-return exists to prevent. It is still logged and still
            # recorded on the span; the UI picks the contract up on the next
            # bootstrap / agent-switch echo.
            return

        if self.messenger:
            try:
                await self.messenger.send_session_update(
                    agent_name=self.active,
                    session_obj=session_obj,
                    transport=self._transport,
                    contract=contract,
                )
            except Exception:
                logger.debug("Failed to emit session update envelope", exc_info=True)

        # If a handoff response was just triggered, DON'T cancel it
        # The handoff code already called response.create() with the appropriate instructions
        if self._handoff_response_pending:
            logger.debug("[Session Updated] Skipping response.cancel() - handoff response pending")
            self._handoff_response_pending = False
            if self.audio:
                await self.audio.start_capture()
            return

        # A greeting the fallback timer already put on the wire is *our* response.
        # The bootstrap echo it races must not tear it down: with a greeting
        # genuinely in flight `_active_response_id` is set, so the guard below
        # would happily cancel it and the caller hears the opening line cut off
        # mid-word. Mirrors the handoff shortcut above.
        if self._greeting_response_pending:
            logger.debug(
                "[Session Updated] Skipping audio reset - greeting response already in flight"
            )
            self._greeting_response_pending = False
            if self.audio:
                await self.audio.start_capture()
            return

        if self.audio:
            await self.audio.stop_playback()
        # Only cancel when a response is actually in flight. Cancelling with no
        # active response makes VoiceLive emit a `response_cancel_not_active`
        # server error, which the handler treats as a hard error (StopAudio +
        # UI error) and breaks the next turn. Same guard as the barge-in path.
        if self._active_response_id:
            try:
                await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during session_ready", exc_info=True)
        if self.audio:
            await self.audio.start_capture()

        if self._pending_greeting and self._pending_greeting_agent == self.active:
            self._cancel_pending_greeting_tasks()
            try:
                await self.agents[self.active].trigger_voicelive_response(
                    self.conn,
                    say=self._pending_greeting,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[Greeting] Session-ready trigger failed; retrying via fallback", exc_info=True
                )
                self._schedule_greeting_fallback(self.active)
            else:
                self._pending_greeting = None
                self._pending_greeting_agent = None

    async def _handle_speech_started(self) -> None:
        """Handle user speech started (barge-in)."""
        logger.debug("User speech started → cancel current response")

        # Sync state to MemoManager in background - don't block barge-in response
        # This ensures any partial response context is preserved
        self._schedule_background_sync()

        if self.audio:
            await self.audio.stop_playback()
        # Only cancel when a response is actually in flight. Cancelling with no
        # active response makes VoiceLive emit a `response_cancel_not_active`
        # server error, which the handler treats as a hard error (StopAudio +
        # UI error) and breaks the next turn. This race widens when VAD fires
        # speech_started right after a turn completes (low silence_duration).
        if self._active_response_id:
            try:
                await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during barge-in", exc_info=True)
        if self.messenger and self._active_response_id:
            try:
                await self.messenger.send_assistant_cancelled(
                    response_id=self._active_response_id,
                    sender=self.active,
                    reason="user_barge_in",
                )
            except Exception:
                logger.debug("Failed to notify assistant cancellation on barge-in", exc_info=True)
        self._active_response_id = None
        # Barge-in ends the current response stream — reset the dedup guard so the
        # next response accumulates cleanly.
        self._seen_transcript_delta_ids.clear()

    async def _handle_speech_stopped(self) -> None:
        """Handle user speech stopped."""
        logger.debug("User speech stopped → start playback for assistant")
        if self.audio:
            await self.audio.start_playback()

        # Start new turn (increments turn count, resets TTFT tracking)
        self._metrics.start_turn()

    async def _handle_transcription_completed(self, event) -> None:
        """Handle user transcription completed."""
        user_transcript = getattr(event, "transcript", "")
        if user_transcript:
            logger.info("[USER] Says: %s", user_transcript)
            user_text = user_transcript.strip()
            self._last_user_message = user_text
            # Add to bounded history for better handoff context
            self._user_message_history.append(user_text)

            # Persist user turn to MemoManager for session continuity (fast, local)
            if self._memo_manager:
                try:
                    self._memo_manager.append_to_history(self.active, "user", user_text)
                except Exception:
                    logger.debug("Failed to persist user turn to history", exc_info=True)

            # Mark that we need a session update (will be done in throttled fashion)
            # Don't call _update_session_context here - it's too slow for the hot path
            # The response_done handler will do a throttled update
            self._pending_session_update = True

            await self._maybe_trigger_call_center_transfer(user_transcript)

    async def _handle_transcription_delta(self, event) -> None:
        """Handle user transcription delta."""
        user_transcript = getattr(event, "transcript", "")
        if user_transcript:
            logger.debug("[USER delta] Says: %s", user_transcript)
            # Only update _last_user_message for deltas, don't add to deque yet
            # The final message will be added in _handle_transcription_completed
            self._last_user_message = user_transcript.strip()

    async def _handle_transcript_delta(self, event) -> None:
        """Handle assistant transcript delta (streaming)."""
        # Drop re-delivered transcript deltas. The accumulator appends each delta,
        # so a duplicated event doubles every word in the streaming bubble. The
        # server event_id is unique per event, so this only drops true duplicates
        # (a legitimately repeated word arrives as a distinct event_id).
        event_id = getattr(event, "event_id", None)
        if event_id:
            if event_id in self._seen_transcript_delta_ids:
                logger.warning(
                    "[Orchestrator] Dropped duplicate assistant transcript delta | "
                    "event_id=%s response=%s agent=%s (Voice Live re-delivery)",
                    event_id,
                    getattr(event, "response_id", None),
                    self.active,
                )
                return
            self._seen_transcript_delta_ids.add(event_id)

        transcript_delta = getattr(event, "delta", "") or getattr(event, "transcript", "")

        # Track LLM TTFT for agent-level token/timing accounting. The canonical
        # TTFT telemetry (the voicelive.llm.ttft histogram + the turn-span event)
        # is emitted by the handler, so we deliberately do NOT create a duplicate
        # 0-duration span here — those previously cluttered the dependencies table.
        ttft_ms = self._metrics.record_first_token() if transcript_delta else None
        if ttft_ms is not None:
            logger.debug(
                "[Orchestrator] LLM TTFT | turn=%d ttft_ms=%.2f agent=%s",
                self._metrics.turn_count,
                ttft_ms,
                self.active,
            )

        if transcript_delta and self.messenger:
            response_id = self._response_id_from_event(event)
            if response_id:
                self._active_response_id = response_id
            else:
                response_id = self._active_response_id
            try:
                await self.messenger.send_assistant_streaming(
                    transcript_delta,
                    sender=self.active,
                    response_id=response_id,
                )
            except Exception:
                logger.debug("Failed to relay assistant streaming delta", exc_info=True)

    async def _handle_transcript_done(self, event) -> None:
        """Handle assistant transcript complete."""
        full_transcript = getattr(event, "transcript", "")
        if full_transcript:
            logger.info("[%s] Agent: %s", self.active, full_transcript)
            # Track assistant response for history persistence
            self._last_assistant_message = full_transcript

            # Persist assistant turn to MemoManager for session continuity
            if self._memo_manager:
                try:
                    self._memo_manager.append_to_history(self.active, "assistant", full_transcript)
                except Exception:
                    logger.debug("Failed to persist assistant turn to history", exc_info=True)

            if self.messenger:
                response_id = self._response_id_from_event(event)
                if not response_id:
                    response_id = self._active_response_id
                try:
                    await self.messenger.send_assistant_message(
                        full_transcript,
                        sender=self.active,
                        response_id=response_id,
                    )
                except Exception:
                    logger.debug(
                        "Failed to relay assistant transcript to session UI", exc_info=True
                    )
                if response_id and response_id == self._active_response_id:
                    self._active_response_id = None

    async def _handle_response_done(self, event) -> None:
        """Handle response complete.

        CRITICAL: When the model makes multiple tool calls in a single response,
        each tool is executed but we defer response.create() until ALL tools finish.
        This handler flushes pending tool outputs and triggers ONE response.
        """
        logger.debug("Response complete")
        response_id = self._response_id_from_event(event)
        if response_id and response_id == self._active_response_id:
            self._active_response_id = None
        # New response starts a fresh transcript stream — reset the dedup guard.
        self._seen_transcript_delta_ids.clear()

        self._emit_model_metrics(event)

        # Flush pending tool outputs if any and trigger ONE model response
        # This prevents duplicate messages when model makes multiple tool calls
        if self._pending_tool_outputs:
            logger.debug(
                "[Response Done] Flushing %d pending tool outputs",
                len(self._pending_tool_outputs),
            )

            # Create all tool output items
            for call_id, output_json in self._pending_tool_outputs:
                try:
                    output_item = FunctionCallOutputItem(
                        call_id=call_id,
                        output=output_json,
                    )
                    await self.conn.conversation.item.create(item=output_item)
                    logger.debug("Created function_call_output item for call_id=%s", call_id)
                except Exception:
                    logger.warning(
                        "Failed to create tool output item for call_id=%s", call_id, exc_info=True
                    )

            # Clear pending outputs
            self._pending_tool_outputs = []

            # Update session context with collected information BEFORE response
            await self._update_session_context()

            # Advance turn_id once for all tool calls combined
            if self.messenger:
                self.messenger.advance_turn_for_tool()

            # Trigger ONE response for all tool outputs
            with tracer.start_as_current_span(
                "voicelive.response.create_batched",
                kind=trace.SpanKind.SERVER,
                attributes=create_service_dependency_attrs(
                    source_service="voicelive_orchestrator",
                    target_service="azure_voicelive",
                    call_connection_id=self.call_connection_id,
                    session_id=(
                        getattr(self.messenger, "session_id", None) if self.messenger else None
                    ),
                ),
            ):
                await self.conn.response.create()
            logger.info("[Response Done] Triggered single response for batched tool outputs")

        # Reset the tool calls flag
        self._response_had_tool_calls = False

        # Sync state to MemoManager in background to avoid hot path latency
        self._schedule_background_sync()

        # Schedule throttled session update in background - don't block the hot path
        self._schedule_throttled_session_update()

    # ═══════════════════════════════════════════════════════════════════════════
    # AGENT SWITCHING
    # ═══════════════════════════════════════════════════════════════════════════

    async def _switch_to(self, agent_name: str, system_vars: dict):
        """Switch to a different agent and apply its session configuration."""
        previous_agent = self.active
        agent = self.agents[agent_name]

        # Emit invoke_agent summary span for the outgoing agent
        if previous_agent != agent_name and self._metrics._response_count > 0:
            self._emit_agent_summary_span(previous_agent)

        with tracer.start_as_current_span(
            "voicelive_orchestrator.switch_agent",
            kind=trace.SpanKind.INTERNAL,
            attributes=create_service_handler_attrs(
                service_name="LiveOrchestrator._switch_to",
                call_connection_id=self.call_connection_id,
                session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
            ),
        ) as switch_span:
            switch_span.set_attribute("voicelive.previous_agent", previous_agent)
            switch_span.set_attribute("voicelive.target_agent", agent_name)

            self._cancel_pending_greeting_tasks()

            system_vars = dict(system_vars or {})
            system_vars.setdefault("previous_agent", previous_agent)
            system_vars.setdefault("active_agent", agent.name)

            is_first_visit = agent_name not in self.visited_agents
            self.visited_agents.add(agent_name)
            switch_span.set_attribute("voicelive.is_first_visit", is_first_visit)

            logger.info(
                "[Agent Switch] %s → %s | Context: %s | First visit: %s",
                previous_agent,
                agent_name,
                system_vars,
                is_first_visit,
            )

            greeting = self._select_pending_greeting(
                agent=agent,
                agent_name=agent_name,
                system_vars=system_vars,
                is_first_visit=is_first_visit,
            )
            if greeting:
                self._pending_greeting = greeting
                self._pending_greeting_agent = agent_name
            else:
                self._pending_greeting = None
                self._pending_greeting_agent = None

            handoff_context = sanitize_handoff_context(system_vars.get("handoff_context"))
            if handoff_context:
                system_vars["handoff_context"] = handoff_context
                for key in (
                    "caller_name",
                    "client_id",
                    "institution_name",
                    "service_type",
                    "case_id",
                    "issue_summary",
                    "details",
                    "handoff_reason",
                    "user_last_utterance",
                ):
                    if key not in system_vars and handoff_context.get(key) is not None:
                        system_vars[key] = handoff_context.get(key)

            # Include slots and tool outputs from MemoManager for context continuity
            if self._memo_manager:
                slots = self._memo_manager.get_context("slots", {})
                if slots:
                    system_vars.setdefault("slots", slots)
                    # Also merge collected info directly for easier template access
                    system_vars.setdefault("collected_information", slots)

                tool_outputs = self._memo_manager.get_context("tool_outputs", {})
                if tool_outputs:
                    system_vars.setdefault("tool_outputs", tool_outputs)

            # Auto-load user profile if client_id is present but session_profile is missing
            await _auto_load_user_context(system_vars)

            self.active = agent_name

            try:
                if self.messenger:
                    try:
                        self.messenger.set_active_agent(agent_name)
                    except AttributeError:
                        logger.debug("Messenger does not support set_active_agent", exc_info=True)

                has_handoff = bool(system_vars.get("handoff_context"))
                switch_span.set_attribute("voicelive.is_handoff", has_handoff)

                # VoiceLive binds the generative model at connect() time; it CANNOT be
                # changed via session.update(). If this agent declares a different
                # voicelive_model than the model bound to the live connection, the override
                # is silently ignored for the rest of the call. Surface that clearly.
                try:
                    # Same unwrap as elsewhere: self.agents holds UnifiedAgent
                    # directly. Reaching for ``_agent`` raised AttributeError that
                    # the except below swallowed at debug level, so this warning —
                    # the one that tells you a per-agent voicelive_model is being
                    # ignored — could never actually fire.
                    ua = getattr(agent, "_agent", agent)
                    target_model = ua.get_model_for_mode("voicelive")
                    target_deployment = getattr(target_model, "deployment_id", None)
                    if (
                        target_deployment
                        and self._model_name
                        and target_deployment != self._model_name
                    ):
                        logger.warning(
                            "[Agent Switch] Agent '%s' requests voicelive_model='%s' but the "
                            "VoiceLive connection is bound to '%s'. VoiceLive cannot change models "
                            "mid-call, so the connection model is used. To honor a per-agent model, "
                            "make this agent the scenario's start agent.",
                            agent_name,
                            target_deployment,
                            self._model_name,
                        )
                        switch_span.set_attribute(
                            "voicelive.model_override_ignored", target_deployment
                        )
                except Exception:  # pragma: no cover - defensive
                    logger.debug("Failed to evaluate per-agent model on switch", exc_info=True)

                # For handoffs, clear the last assistant message to prevent the new agent
                # from thinking IT said the old agent's handoff statement (e.g., "I'll connect you
                # to our card specialist"). This prevents the new agent from trying to repeat
                # or complete the handoff.
                if has_handoff:
                    self._last_assistant_message = None
                    logger.debug("[Agent Switch] Cleared last assistant message for handoff")

                # For handoffs, DON'T use the handoff_message as a greeting.
                # The handoff_message is meant for the OLD agent to say ("I'll connect you to...")
                # but by the time we're here, the session has switched to the NEW agent.
                # Instead, let the new agent respond naturally as itself.
                # We'll trigger a response after session update, and the new agent will introduce itself.

                with tracer.start_as_current_span(
                    "voicelive.agent.apply_session",
                    kind=trace.SpanKind.SERVER,
                    attributes=create_service_dependency_attrs(
                        source_service="voicelive_orchestrator",
                        target_service="azure_voicelive",
                        call_connection_id=self.call_connection_id,
                        session_id=(
                            getattr(self.messenger, "session_id", None) if self.messenger else None
                        ),
                    ),
                ) as session_span:
                    session_span.set_attribute("voicelive.agent_name", agent_name)
                    session_id = (
                        getattr(self.messenger, "session_id", None) if self.messenger else None
                    )
                    t_apply = time.perf_counter()
                    # Drop any outstanding context-only credits: an agent switch
                    # is a genuine bootstrap whose echo must run the audio reset.
                    self._pending_context_session_updates = 0
                    # The new agent's instructions replace the ones we fingerprinted.
                    self._last_pushed_instructions = None
                    await agent.apply_voicelive_session(
                        self.conn,
                        system_vars=system_vars,
                        say=None,
                        session_id=session_id,
                        call_connection_id=self.call_connection_id,
                    )
                    apply_ms = (time.perf_counter() - t_apply) * 1000
                    logger.info(
                        "[VoiceLive Startup] apply_session_ms=%.1f | agent=%s",
                        apply_ms,
                        agent_name,
                    )

                # CRITICAL: Inject conversation history as text items for context retention
                # VoiceLive audio models can "forget" context - explicit text items help
                # This must happen AFTER session update but BEFORE first response
                t_hist = time.perf_counter()
                await self._inject_conversation_history()
                hist_ms = (time.perf_counter() - t_hist) * 1000
                if hist_ms > 5:
                    logger.info(
                        "[VoiceLive Startup] inject_history_ms=%.1f | items=%d",
                        hist_ms,
                        len(self._user_message_history),
                    )

                # Schedule greeting fallback if we have a pending greeting
                # This applies to both handoffs and normal agent switches
                if self._pending_greeting and self._pending_greeting_agent == agent_name:
                    self._schedule_greeting_fallback(agent_name)

                # Reset metrics for the new agent (captures summary of previous)
                self._metrics.reset_for_agent_switch(agent_name)

                switch_span.set_status(trace.StatusCode.OK)
            except Exception as ex:
                switch_span.set_status(trace.StatusCode.ERROR, str(ex))
                switch_span.add_event(
                    "agent_switch.error",
                    {"error.type": type(ex).__name__, "error.message": str(ex)},
                )
                logger.exception("Failed to apply session for agent '%s'", agent_name)
                raise

            logger.info("[Active Agent] %s is now active", self.active)

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_tool_call(
        self, call_id: str | None, name: str | None, args_json: str | None
    ) -> bool:
        """
        Execute tool call via shared tool registry and send result back to model.

        Returns True if this was a handoff (agent switch), False otherwise.
        """
        if not name or not call_id:
            logger.warning("Missing call_id or name for function call")
            return False

        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            logger.warning("Could not parse tool arguments for '%s'; using empty dict", name)
            args = {}

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        with tracer.start_as_current_span(
            f"execute_tool {name}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                # App Insights grouping: ai.session.id=call, ai.user.id=session.
                "ai.session.id": self.call_connection_id or "",
                "ai.user.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.call_connection_id or "",
                "transport.type": self._transport.upper() if self._transport else "ACS",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.EXECUTE_TOOL,
                SpanAttr.GENAI_TOOL_NAME.value: name,
                SpanAttr.GENAI_TOOL_CALL_ID.value: call_id,
                SpanAttr.GENAI_TOOL_TYPE.value: "function",
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                "tool.call_id": call_id,
                "tool.parameters_count": len(args),
                "voicelive.tool_name": name,
                "voicelive.tool_id": call_id,
                "voicelive.agent_name": self.active,
                "voicelive.is_acs": self._transport == "acs",
                "voicelive.args_length": len(args_json) if args_json else 0,
                "voicelive.tool.is_handoff": self.handoff_service.is_handoff(name),
                "voicelive.tool.is_transfer": name in TRANSFER_TOOL_NAMES,
            },
        ) as tool_span:

            if name in TRANSFER_TOOL_NAMES:
                if (
                    self._transport_supports_acs()
                    and (not args.get("call_connection_id"))
                    and self.call_connection_id
                ):
                    args.setdefault("call_connection_id", self.call_connection_id)
                if (
                    self._transport_supports_acs()
                    and (not args.get("call_connection_id"))
                    and self.messenger
                ):
                    fallback_call_id = getattr(self.messenger, "call_id", None)
                    if fallback_call_id:
                        args.setdefault("call_connection_id", fallback_call_id)
                if self.messenger:
                    sess_id = getattr(self.messenger, "session_id", None)
                    if sess_id:
                        args.setdefault("session_id", sess_id)

            # Inject session context into tool args (same pattern as SpeechCascade)
            # This allows tools to use already-loaded session data
            if self._memo_manager:
                session_profile = self._memo_manager.get_value_from_corememory("session_profile")
                if session_profile:
                    args["_session_profile"] = session_profile
                # Always inject _client_id so tools can use the verified value
                # Tools should prefer _client_id over client_id when present
                client_id = self._memo_manager.get_value_from_corememory("client_id")
                if client_id:
                    args["_client_id"] = client_id

            logger.info("Executing tool: %s with args: %s", name, args)

            notify_status = "success"
            notify_error: str | None = None

            # Use full message history for better handoff context
            last_user_message = (self._last_user_message or "").strip()
            if self.handoff_service.is_handoff(name):
                # Build conversation summary from message history
                if self._user_message_history:
                    # Use last message for immediate context
                    if last_user_message:
                        for field in (
                            "details",
                            "issue_summary",
                            "summary",
                            "topic",
                            "handoff_reason",
                        ):
                            if not args.get(field):
                                args[field] = last_user_message
                        args.setdefault("user_last_utterance", last_user_message)

                    # Include full conversation context for richer handoff
                    if len(self._user_message_history) > 1:
                        conversation_context = " | ".join(self._user_message_history)
                        args.setdefault("conversation_summary", conversation_context)
                        logger.debug(
                            "[Handoff] Including %d messages in context",
                            len(self._user_message_history),
                        )
                elif last_user_message:
                    # Fallback to single message
                    for field in ("details", "issue_summary", "summary", "topic", "handoff_reason"):
                        if not args.get(field):
                            args[field] = last_user_message
                    args.setdefault("user_last_utterance", last_user_message)

            MFA_TOOL_NAMES = {"send_mfa_code", "resend_mfa_code"}

            if self.messenger:
                try:
                    await self.messenger.notify_tool_start(call_id=call_id, name=name, args=args)
                except Exception:
                    logger.debug("Tool start messenger notification failed", exc_info=True)
                if name in MFA_TOOL_NAMES:
                    try:
                        await self.messenger.send_status_update(
                            text="Sending a verification code to your email…",
                            sender=self.active,
                            event_label="mfa_status_update",
                        )
                    except Exception:
                        logger.debug("Failed to emit MFA status update", exc_info=True)

            start_ts = time.perf_counter()
            result: dict[str, Any] = {}

            try:
                # Tool execution runs under the enclosing `execute_tool {name}`
                # span, which already carries the tool name, args, and timing — no
                # separate child span is needed.
                result = await execute_tool(name, args)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                # CRITICAL: Do NOT re-raise here. This exception bubbles up through
                # handle_event() into the handler's top-level _event_loop(), whose
                # broad except clause treats ANY exception as fatal and shuts down
                # the entire VoiceLive session (self._shutdown.set()). A single
                # failed tool call must not kill the call — it must be reported
                # back to the model as a tool error so the conversation continues.
                notify_status = "error"
                notify_error = str(exc)
                tool_span.set_status(trace.StatusCode.ERROR, str(exc))
                tool_span.add_event(
                    "tool.execution_error",
                    {"error.type": type(exc).__name__, "error.message": str(exc)},
                )
                logger.exception(
                    "Tool execution raised an exception | tool=%s call_id=%s", name, call_id
                )
                result = {"success": False, "error": notify_error}
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status="error",
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            error=notify_error,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)

            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            tool_span.set_attribute("execution.duration_ms", elapsed_ms)
            tool_span.set_attribute("voicelive.tool.elapsed_ms", elapsed_ms)

            error_payload: str | None = None
            execution_success = True
            if isinstance(result, dict):
                for key in ("success", "ok", "authenticated"):
                    if key in result and not result[key]:
                        notify_status = "error"
                        execution_success = False
                        break
                if notify_status == "error":
                    err_val = result.get("message") or result.get("error")
                    if err_val:
                        error_payload = str(err_val)

            tool_span.set_attribute("execution.success", execution_success)
            tool_span.set_attribute("result.type", type(result).__name__ if result else "None")
            tool_span.set_attribute("voicelive.tool.status", notify_status)

            # Persist slots and tool outputs from result to MemoManager
            # This ensures collected information is available in subsequent turns
            if isinstance(result, dict) and self._memo_manager:
                try:
                    # Update slots if tool returned any
                    if "slots" in result and isinstance(result["slots"], dict):
                        current_slots = self._memo_manager.get_context("slots", {})
                        current_slots.update(result["slots"])
                        self._memo_manager.set_context("slots", current_slots)
                        self._system_vars["slots"] = current_slots
                        self._system_vars["collected_information"] = current_slots
                        logger.info(
                            "[Tool] Updated slots from %s: %s",
                            name,
                            list(result["slots"].keys()),
                        )

                    # Store tool output for context continuity
                    tool_outputs = self._memo_manager.get_context("tool_outputs", {})
                    # Store a summary of the result, not the full payload
                    output_summary = {
                        k: v
                        for k, v in result.items()
                        if k not in ("slots", "raw_response") and not k.startswith("_")
                    }
                    if output_summary:
                        tool_outputs[name] = output_summary
                        self._memo_manager.set_context("tool_outputs", tool_outputs)
                        self._system_vars["tool_outputs"] = tool_outputs

                    # Persist authenticated identity to corememory so handoff targets
                    # can inject _client_id and render session_profile in their prompts
                    if result.get("authenticated") and result.get("client_id"):
                        cid = result["client_id"]
                        self._memo_manager.set_corememory("client_id", cid)
                        self._system_vars["client_id"] = cid
                        if result.get("caller_name"):
                            self._memo_manager.set_corememory("caller_name", result["caller_name"])
                            self._system_vars["caller_name"] = result["caller_name"]
                        logger.info(
                            "🔐 Persisted authenticated identity to corememory | client_id=%s",
                            cid[:8] + "..." if len(cid) > 8 else cid,
                        )

                    # Persist loaded profile to corememory for cross-agent availability
                    if (
                        result.get("success")
                        and result.get("profile")
                        and isinstance(result["profile"], dict)
                    ):
                        profile = result["profile"]
                        self._memo_manager.set_corememory("session_profile", profile)
                        self._system_vars["session_profile"] = profile
                        if profile.get("client_id"):
                            self._memo_manager.set_corememory("client_id", profile["client_id"])
                            self._system_vars["client_id"] = profile["client_id"]
                        if profile.get("full_name"):
                            self._memo_manager.set_corememory("caller_name", profile["full_name"])
                            self._system_vars["caller_name"] = profile["full_name"]
                        if profile.get("customer_intelligence"):
                            self._memo_manager.set_corememory(
                                "customer_intelligence", profile["customer_intelligence"]
                            )
                            self._system_vars["customer_intelligence"] = profile[
                                "customer_intelligence"
                            ]
                        if profile.get("institution_name"):
                            self._memo_manager.set_corememory(
                                "institution_name", profile["institution_name"]
                            )
                            self._system_vars["institution_name"] = profile["institution_name"]
                        logger.info(
                            "📋 Persisted user profile to corememory | client=%s name=%s",
                            profile.get("client_id", "?")[:8],
                            profile.get("full_name", "?"),
                        )
                except Exception:
                    logger.debug("Failed to persist tool results to MemoManager", exc_info=True)

            # Handle transfer tools
            if (
                name in TRANSFER_TOOL_NAMES
                and notify_status != "error"
                and isinstance(result, dict)
            ):
                takeover_message = result.get("message") or "Transferring call to destination."
                tool_span.add_event(
                    "tool.transfer_initiated",
                    {"transfer.message": takeover_message[:100] if takeover_message else ""},
                )
                if self.messenger:
                    try:
                        await self.messenger.send_status_update(
                            text=takeover_message,
                            sender=self.active,
                            event_label="acs_call_transfer_status",
                        )
                    except Exception:
                        logger.debug("Failed to emit transfer status update", exc_info=True)
                try:
                    if result.get("should_interrupt_playback", True):
                        await self.conn.response.cancel()
                except Exception:
                    logger.debug("response.cancel() failed during transfer", exc_info=True)
                if self.audio:
                    try:
                        await self.audio.stop_playback()
                    except Exception:
                        logger.debug("Audio stop playback failed during transfer", exc_info=True)
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)
                tool_span.set_status(trace.StatusCode.OK)
                return False

            # Handle handoff tools using unified HandoffService
            if self.handoff_service.is_handoff(name):
                # Use HandoffService for consistent resolution across orchestrators
                resolution = self.handoff_service.resolve_handoff(
                    tool_name=name,
                    tool_args=args,
                    source_agent=self.active,
                    current_system_vars=self._system_vars,
                    user_last_utterance=last_user_message,
                    tool_result=result if isinstance(result, dict) else None,
                )

                if not resolution.success:
                    logger.warning(
                        "Handoff resolution failed: %s | tool=%s",
                        resolution.error,
                        name,
                    )
                    notify_status = "error"
                    tool_span.set_status(trace.StatusCode.ERROR, "handoff_resolution_failed")
                    if self.messenger:
                        try:
                            await self.messenger.notify_tool_end(
                                call_id=call_id,
                                name=name,
                                status=notify_status,
                                elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                                result=result if isinstance(result, dict) else None,
                                error=resolution.error or "handoff_resolution_failed",
                            )
                        except Exception:
                            logger.debug("Tool end messenger notification failed", exc_info=True)
                    return False

                target = resolution.target_agent
                tool_span.set_attribute("voicelive.handoff.target_agent", target)
                tool_span.add_event("tool.handoff_triggered", {"target_agent": target})
                tool_span.set_attribute("voicelive.handoff.share_context", resolution.share_context)
                tool_span.set_attribute(
                    "voicelive.handoff.greet_on_switch", resolution.greet_on_switch
                )
                tool_span.set_attribute("voicelive.handoff.type", resolution.handoff_type)

                # CRITICAL: Cancel any ongoing response from the OLD agent immediately.
                # This prevents the old agent from saying "I'll connect you..." while
                # the session switches to the new agent.
                try:
                    await self.conn.response.cancel()
                    logger.debug("[Handoff] Cancelled old agent response before switch")
                except Exception:
                    pass  # No active response to cancel

                # Stop audio playback to prevent old agent's voice from continuing
                if self.audio:
                    try:
                        await self.audio.stop_playback()
                    except Exception:
                        logger.debug("[Handoff] Audio stop failed", exc_info=True)

                # Use system_vars from HandoffService resolution
                ctx = resolution.system_vars

                logger.info("[Handoff Tool] '%s' triggered | %s → %s", name, self.active, target)

                await self._switch_to(target, ctx)
                self._last_user_message = None

                if result.get("call_center_transfer"):
                    transfer_args: dict[str, Any] = {}
                    if self._transport_supports_acs() and self.call_connection_id:
                        transfer_args["call_connection_id"] = self.call_connection_id
                    if self.messenger:
                        sess_id = getattr(self.messenger, "session_id", None)
                        if sess_id:
                            transfer_args["session_id"] = sess_id
                    if transfer_args:
                        self._call_center_triggered = True
                        await self._trigger_call_center_transfer(transfer_args)
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result if isinstance(result, dict) else None,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)

                # NOTE: We intentionally do NOT send the handoff tool output back to the model.
                # The old agent's tool call was an internal action that triggered the switch.
                # Sending the output to the new agent's session would confuse it - the new
                # agent would see a tool call it didn't make and might try to "complete" it.
                # Instead, we trigger the new agent's response cleanly via additional_instructions.
                logger.debug(
                    "[Handoff] Skipping tool output injection | "
                    "call_id=%s | The new agent will respond via additional_instructions",
                    call_id,
                )

                # Trigger the new agent to respond naturally as itself
                # Build context about the handoff for the new agent's instruction
                handoff_ctx = ctx.get("handoff_context", {})
                user_question = (
                    handoff_ctx.get("question")
                    or handoff_ctx.get("details")
                    or last_user_message
                    or "general inquiry"
                )
                handoff_summary = (
                    result.get("handoff_summary", "") if isinstance(result, dict) else ""
                )
                previous_agent = self._system_vars.get("previous_agent", "previous agent")

                # Get handoff mode from context (set by build_handoff_system_vars)
                greet_on_switch = ctx.get("greet_on_switch", True)

                # Trigger the new agent to respond immediately (no background task)
                # The agent's system prompt already contains discrete/announced handoff instructions
                # via is_handoff and greet_on_switch template variables.
                #
                # CRITICAL: Use additional_instructions (which APPENDS to system prompt)
                # instead of ResponseCreateParams(instructions=...) which OVERRIDES it!
                # The agent's prompt template has discrete handoff behavior built in.
                try:
                    # Build additional instruction to append (not override) the system prompt
                    if greet_on_switch:
                        # Announced mode: greeting will be spoken, then address request
                        additional_instruction = (
                            f'The customer\'s request: "{user_question}". '
                            f"Address their request directly after your greeting."
                        )
                        if handoff_summary:
                            additional_instruction += f" Context: {handoff_summary}"
                    else:
                        # Discrete mode: system prompt already has discrete handoff instructions
                        # Just provide the user's question as context - don't override behavior
                        additional_instruction = (
                            f'The customer\'s request: "{user_question}". '
                            f"Respond immediately without any greeting or introduction."
                        )

                        # CRITICAL FIX: For discrete handoffs, inject the user's question as
                        # an explicit conversation item. This gives the model a concrete user
                        # message to respond to, not just additional_instructions context.
                        # Without this, the model may not generate a response because there's
                        # no actual user turn in the conversation to respond to.
                        if user_question and user_question != "general inquiry":
                            try:
                                text_part = InputTextContentPart(text=user_question)
                                user_item = UserMessageItem(content=[text_part])
                                await self.conn.conversation.item.create(item=user_item)
                                logger.debug(
                                    "[Handoff] Injected user question as conversation item: %s",
                                    user_question[:50] if user_question else "none",
                                )
                            except Exception:
                                logger.debug(
                                    "[Handoff] Failed to inject user question item", exc_info=True
                                )

                    # Trigger response synchronously - no fire-and-forget background task
                    # This ensures the handoff response is reliably triggered
                    #
                    # Use conn.response.create() with additional_instructions parameter
                    # This APPENDS to the session's system prompt rather than overriding it
                    #
                    # Advance turn_id to create a new message segment for the new agent
                    # This ensures the handoff response appears as a fresh message
                    if self.messenger:
                        self.messenger.advance_turn_for_tool()

                    # CRITICAL: Clear pending greeting state BEFORE calling response.create()
                    # The _switch_to() method sets _pending_greeting, and when session_ready
                    # event arrives (from session.update()), _handle_session_ready() would try
                    # to trigger another response via trigger_voicelive_response(). This causes
                    # "Conversation already has an active response" error.
                    # We handle the handoff response here with additional_instructions, so we
                    # must prevent the competing greeting mechanism from also triggering.
                    self._cancel_pending_greeting_tasks()
                    self._pending_greeting = None
                    self._pending_greeting_agent = None

                    # CRITICAL: Set flag to prevent _handle_session_updated from cancelling
                    # this response. The SESSION_UPDATED event from session.update() arrives
                    # async and would cancel our handoff response without this guard.
                    self._handoff_response_pending = True

                    with tracer.start_as_current_span(
                        "voicelive.handoff.response_create",
                        kind=trace.SpanKind.SERVER,
                        attributes=create_service_dependency_attrs(
                            source_service="voicelive_orchestrator",
                            target_service="azure_voicelive",
                            call_connection_id=self.call_connection_id,
                            session_id=(
                                getattr(self.messenger, "session_id", None)
                                if self.messenger
                                else None
                            ),
                        ),
                    ):
                        await self.conn.response.create(
                            additional_instructions=additional_instruction
                        )
                    logger.info(
                        "[Handoff] Triggered new agent '%s' | greet=%s | question=%s",
                        target,
                        greet_on_switch,
                        user_question[:50] if user_question else "none",
                    )
                except Exception as e:
                    logger.warning("[Handoff] Failed to trigger response: %s", e)
                    self._handoff_response_pending = False  # Reset flag on failure

                tool_span.set_status(trace.StatusCode.OK)
                return True

            else:
                # Business tool - queue output for batched response at RESPONSE_DONE
                # This prevents duplicate messages when model makes multiple tool calls
                #
                # CRITICAL: Do NOT call response.create() here! The model may have
                # multiple tool calls in a single response. We queue all outputs and
                # trigger ONE response in _handle_response_done().
                output_json = json.dumps(result)
                self._pending_tool_outputs.append((call_id, output_json))
                self._response_had_tool_calls = True
                logger.debug(
                    "[Business Tool] Queued output for call_id=%s | pending_count=%d",
                    call_id,
                    len(self._pending_tool_outputs),
                )

                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result if isinstance(result, dict) else None,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)
                tool_span.set_status(trace.StatusCode.OK)
                return False

    # ═══════════════════════════════════════════════════════════════════════════
    # GREETING HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _select_pending_greeting(
        self,
        *,
        agent: UnifiedAgent,
        agent_name: str,
        system_vars: dict,
        is_first_visit: bool,
    ) -> str | None:
        """
        Return a contextual greeting the agent should deliver once the session is ready.

        Delegates to HandoffService.select_greeting() for consistent behavior
        across both orchestrators. The HandoffService handles:
        - Priority 1: Explicit greeting override in system_vars
        - Priority 2: Discrete handoff detection (skip greeting)
        - Priority 3: Render agent's greeting/return_greeting template
        """
        # Determine greet_on_switch from system_vars (set by HandoffService.resolve_handoff)
        greet_on_switch = system_vars.get("greet_on_switch", True)

        greeting = self.handoff_service.select_greeting(
            agent=agent,
            is_first_visit=is_first_visit,
            greet_on_switch=greet_on_switch,
            system_vars=system_vars,
        )

        if greeting:
            logger.debug(
                "[Greeting] Selected greeting for %s | first_visit=%s | len=%d",
                agent_name,
                is_first_visit,
                len(greeting),
            )
        else:
            logger.debug(
                "[Greeting] No greeting for %s | first_visit=%s | greet_on_switch=%s",
                agent_name,
                is_first_visit,
                greet_on_switch,
            )

        return greeting

    def _cancel_pending_greeting_tasks(self) -> None:
        # Whoever cancels greeting delivery also owns the in-flight guard: a
        # stale flag would let the *next* genuine bootstrap echo skip the audio
        # reset it needs. Cleared before the early return so it holds even when
        # no fallback task was ever scheduled.
        self._greeting_response_pending = False
        if not self._greeting_tasks:
            return
        for task in list(self._greeting_tasks):
            task.cancel()
        self._greeting_tasks.clear()

    def _schedule_greeting_fallback(self, agent_name: str) -> None:
        if not self._pending_greeting or not self._pending_greeting_agent:
            return

        async def _fallback() -> None:
            try:
                await asyncio.sleep(GREETING_FALLBACK_DELAY_S)
                if self._pending_greeting and self._pending_greeting_agent == agent_name:
                    logger.debug(
                        "[GreetingFallback] Triggering fallback introduction for %s", agent_name
                    )
                    # Claim the guard *before* awaiting the trigger: the echo can
                    # land while this coroutine is suspended inside response.create().
                    self._greeting_response_pending = True
                    try:
                        await self.agents[agent_name].trigger_voicelive_response(
                            self.conn,
                            say=self._pending_greeting,
                        )
                    except asyncio.CancelledError:
                        self._greeting_response_pending = False
                        raise
                    except Exception:
                        self._greeting_response_pending = False
                        logger.debug("[GreetingFallback] Failed to deliver greeting", exc_info=True)
                        return
                    self._pending_greeting = None
                    self._pending_greeting_agent = None
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("[GreetingFallback] Unexpected error in fallback task", exc_info=True)

        task = asyncio.create_task(
            _fallback(),
            name=f"voicelive-greeting-fallback-{agent_name}",
        )
        task.add_done_callback(lambda t: self._greeting_tasks.discard(t))
        self._greeting_tasks.add(task)

    # ═══════════════════════════════════════════════════════════════════════════
    # CALL CENTER TRANSFER
    # ═══════════════════════════════════════════════════════════════════════════

    async def _maybe_trigger_call_center_transfer(self, transcript: str) -> None:
        """Detect trigger phrases and initiate automatic call center transfer."""
        if self._call_center_triggered:
            return

        normalized = transcript.strip().lower()
        if not normalized:
            return

        if not any(phrase in normalized for phrase in CALL_CENTER_TRIGGER_PHRASES):
            return

        self._call_center_triggered = True
        logger.info(
            "[Auto Transfer] Triggering call center transfer due to phrase match: '%s'", transcript
        )

        args: dict[str, Any] = {}
        if self._transport_supports_acs() and self.call_connection_id:
            args["call_connection_id"] = self.call_connection_id
        if self.messenger:
            session_id = getattr(self.messenger, "session_id", None)
            if session_id:
                args["session_id"] = session_id

        await self._trigger_call_center_transfer(args)

    async def _trigger_call_center_transfer(self, args: dict[str, Any]) -> None:
        """Invoke the call center transfer tool and handle playback cleanup."""
        tool_name = "transfer_call_to_call_center"

        if self.messenger:
            try:
                await self.messenger.send_status_update(
                    text="Routing you to a call center representative…",
                    sender=self.active,
                    event_label="acs_call_transfer_status",
                )
            except Exception:
                logger.debug("Failed to emit pre-transfer status update", exc_info=True)

        try:
            result = await execute_tool(tool_name, args)
        except Exception:
            self._call_center_triggered = False
            logger.exception("Automatic call center transfer failed unexpectedly")
            if self.messenger:
                try:
                    await self.messenger.send_status_update(
                        text="We encountered an issue reaching the call center. Staying with the virtual agent for now.",
                        sender=self.active,
                        event_label="acs_call_transfer_status",
                    )
                except Exception:
                    logger.debug("Failed to emit transfer failure status", exc_info=True)
            return

        if not isinstance(result, dict) or not result.get("success"):
            self._call_center_triggered = False
            error_message = None
            if isinstance(result, dict):
                error_message = result.get("message") or result.get("error")
            logger.warning(
                "Automatic call center transfer request was rejected | result=%s", result
            )
            if self.messenger:
                try:
                    await self.messenger.send_status_update(
                        text=error_message
                        or "Unable to reach the call center right now. I'll stay on the line with you.",
                        sender=self.active,
                        event_label="acs_call_transfer_status",
                    )
                except Exception:
                    logger.debug("Failed to emit transfer rejection status", exc_info=True)
            return

        takeover_message = result.get(
            "message", "Routing you to a live call center representative now."
        )

        if self.messenger:
            try:
                await self.messenger.send_status_update(
                    text=takeover_message,
                    sender=self.active,
                    event_label="acs_call_transfer_status",
                )
            except Exception:
                logger.debug("Failed to emit transfer success status", exc_info=True)

        try:
            if result.get("should_interrupt_playback", True):
                await self.conn.response.cancel()
        except Exception:
            logger.debug(
                "response.cancel() failed during automatic call center transfer", exc_info=True
            )

        if self.audio:
            try:
                await self.audio.stop_playback()
            except Exception:
                logger.debug(
                    "Audio stop playback failed during automatic call center transfer",
                    exc_info=True,
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # TELEMETRY HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _emit_agent_summary_span(self, agent_name: str) -> None:
        """Emit an invoke_agent summary span with accumulated token usage."""
        agent = self.agents.get(agent_name)
        if not agent:
            return

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        # Use metrics for duration and token tracking
        agent_duration_ms = self._metrics.duration_ms

        with tracer.start_as_current_span(
            f"invoke_agent {agent_name}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                # App Insights grouping: ai.session.id=call, ai.user.id=session.
                "ai.session.id": self.call_connection_id or "",
                "ai.user.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.call_connection_id or "",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.INVOKE_AGENT,
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                SpanAttr.GENAI_REQUEST_MODEL.value: self._model_name,
                "gen_ai.agent.name": agent_name,
                "gen_ai.agent.id": f"{agent_name}:v1",
                "gen_ai.agent.description": getattr(
                    agent, "description", f"VoiceLive agent: {agent_name}"
                ),
                SpanAttr.GENAI_USAGE_INPUT_TOKENS.value: self._metrics.input_tokens,
                SpanAttr.GENAI_USAGE_OUTPUT_TOKENS.value: self._metrics.output_tokens,
                "voicelive.agent_name": agent_name,
                "voicelive.response_count": self._metrics._response_count,
                "voicelive.duration_ms": agent_duration_ms,
            },
        ) as agent_span:
            agent_span.add_event(
                "gen_ai.agent.session_complete",
                {
                    "agent": agent_name,
                    "input_tokens": self._metrics.input_tokens,
                    "output_tokens": self._metrics.output_tokens,
                    "response_count": self._metrics._response_count,
                    "duration_ms": agent_duration_ms,
                },
            )
            logger.debug(
                "[Agent Summary] %s complete | tokens=%d/%d responses=%d duration=%.1fms",
                agent_name,
                self._metrics.input_tokens,
                self._metrics.output_tokens,
                self._metrics._response_count,
                agent_duration_ms,
            )

    def _emit_model_metrics(self, event: Any) -> None:
        """Emit GenAI model-level metrics for App Insights Agents blade."""
        response = getattr(event, "response", None)
        if not response:
            return

        response_id = getattr(response, "id", None)

        usage = getattr(response, "usage", None)
        input_tokens = 0
        output_tokens = 0

        if usage:
            input_tokens = (
                getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", None)
                or 0
            )

        # Track tokens and response via unified metrics
        self._metrics.add_tokens(input_tokens=input_tokens, output_tokens=output_tokens)
        self._metrics.record_response()

        model = self._model_name
        status = getattr(response, "status", None)

        # Get TTFT from metrics if available
        turn_duration_ms = self._metrics.current_ttft_ms

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        span_name = model if model else "gpt-4o-realtime"

        with tracer.start_as_current_span(
            span_name,
            kind=trace.SpanKind.CLIENT,
            attributes={
                "component": "voicelive",
                "call.connection.id": self.call_connection_id or "",
                # App Insights grouping: ai.session.id=call, ai.user.id=session.
                "ai.session.id": self.call_connection_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                "ai.user.id": session_id or "",
                "transport.type": self._transport.upper() if self._transport else "ACS",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.CHAT,
                SpanAttr.GENAI_SYSTEM.value: "openai",
                SpanAttr.GENAI_REQUEST_MODEL.value: model,
                "voicelive.agent_name": self.active,
            },
        ) as model_span:
            model_span.set_attribute(SpanAttr.GENAI_RESPONSE_MODEL.value, model)

            if response_id:
                model_span.set_attribute(SpanAttr.GENAI_RESPONSE_ID.value, response_id)

            if input_tokens is not None:
                model_span.set_attribute(SpanAttr.GENAI_USAGE_INPUT_TOKENS.value, input_tokens)
            if output_tokens is not None:
                model_span.set_attribute(SpanAttr.GENAI_USAGE_OUTPUT_TOKENS.value, output_tokens)

            if turn_duration_ms is not None:
                model_span.set_attribute(
                    SpanAttr.GENAI_CLIENT_OPERATION_DURATION.value, turn_duration_ms
                )

            # Set TTFT if available from metrics
            ttft_ms = self._metrics.current_ttft_ms
            if ttft_ms is not None:
                model_span.set_attribute(SpanAttr.GENAI_SERVER_TIME_TO_FIRST_TOKEN.value, ttft_ms)

            model_span.add_event(
                "gen_ai.response.complete",
                {
                    "response_id": response_id or "",
                    "status": str(status) if status else "",
                    "input_tokens": input_tokens or 0,
                    "output_tokens": output_tokens or 0,
                    "agent": self.active,
                    "turn_number": self._metrics.turn_count,
                },
            )

            logger.debug(
                "[Model Metrics] Response complete | agent=%s model=%s response_id=%s tokens=%s/%s",
                self.active,
                model,
                response_id or "N/A",
                input_tokens or "N/A",
                output_tokens or "N/A",
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _transport_supports_acs(self) -> bool:
        return self._transport == "acs"

    @staticmethod
    def _response_id_from_event(event: Any) -> str | None:
        response = getattr(event, "response", None)
        if response and hasattr(response, "id"):
            return response.id
        return getattr(event, "response_id", None)


__all__ = [
    "LiveOrchestrator",
    "TRANSFER_TOOL_NAMES",
    "CALL_CENTER_TRIGGER_PHRASES",
    "register_voicelive_orchestrator",
    "unregister_voicelive_orchestrator",
    "get_voicelive_orchestrator",
    "get_orchestrator_registry_size",
]
