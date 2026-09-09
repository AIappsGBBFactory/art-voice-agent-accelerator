"""VoiceLive SDK operations over neutral agent definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent

logger = get_logger("voice.voicelive.session")


def _build_voicelive_tools_with_handoffs(
    agent: UnifiedAgent, session_id: str | None = None
) -> list[Any]:
    from apps.artagent.backend.voice.shared.config_resolver import resolve_orchestrator_config
    from apps.artagent.backend.voice.shared.handoff_service import HandoffService
    from apps.artagent.backend.voice.shared.tool_policy import agent_tool_schemas
    from azure.ai.voicelive.models import FunctionTool

    config = resolve_orchestrator_config(session_id=session_id) if session_id else None
    scenario = config.scenario if config else None
    agents = config.agents if config else {agent.name: agent}
    service = HandoffService(
        scenario=scenario, agents=agents, handoff_map=config.handoff_map if config else {}
    )
    schemas = agent_tool_schemas(
        agent, scenario=scenario, agents=agents, is_handoff=service.is_handoff
    )
    return [
        FunctionTool(**schema["function"]) for schema in schemas if schema.get("type") == "function"
    ]


def build_voicelive_voice(agent: UnifiedAgent) -> Any | None:
    """
    Build VoiceLive voice configuration from this agent's voice settings.

    Returns:
        Provider voice configuration, or None when no voice is configured.
    """
    from azure.ai.voicelive.models import AzureStandardVoice

    try:
        from azure.ai.voicelive.models import AzureCustomVoice
    except ImportError:
        AzureCustomVoice = None

    if not agent.voice.name:
        return None

    voice_type = agent.voice.type.lower().strip()

    if voice_type in {"azure-custom", "azure_custom"}:
        if AzureCustomVoice and agent.voice.endpoint_id:
            return AzureCustomVoice(
                name=agent.voice.name,
                endpoint_id=agent.voice.endpoint_id,
            )
        logger.warning("Custom voice unavailable or missing endpoint; using standard voice")
        return AzureStandardVoice(name=agent.voice.name)

    if voice_type in {"azure-standard", "azure_standard", "azure"}:
        optionals = {}
        for key in ("style", "pitch", "rate"):
            val = getattr(agent.voice, key, None)
            if val is not None and val != "+0%":
                optionals[key] = val
        return AzureStandardVoice(name=agent.voice.name, **optionals)

    # Default to standard voice
    return AzureStandardVoice(name=agent.voice.name)


def build_voicelive_vad(agent: UnifiedAgent) -> Any | None:
    """
    Build VoiceLive VAD (turn detection) configuration.

    Returns:
        TurnDetection object (AzureSemanticVad or ServerVad), or None.
    """
    from azure.ai.voicelive.models import AzureSemanticVad, ServerVad

    cfg = agent.session.get("turn_detection") if agent.session else None
    if not cfg:
        return None

    vad_type = (cfg.get("type") or "semantic").lower()

    common_kwargs: dict[str, Any] = {}
    if "threshold" in cfg:
        common_kwargs["threshold"] = float(cfg["threshold"])
    if "prefix_padding_ms" in cfg:
        common_kwargs["prefix_padding_ms"] = int(cfg["prefix_padding_ms"])
    if "silence_duration_ms" in cfg:
        common_kwargs["silence_duration_ms"] = int(cfg["silence_duration_ms"])

    if vad_type in ("semantic", "azure_semantic", "azure_semantic_vad"):
        return AzureSemanticVad(**common_kwargs)
    elif vad_type in ("server", "server_vad"):
        return ServerVad(**common_kwargs)

    return AzureSemanticVad(**common_kwargs)


def get_voicelive_modalities(agent: UnifiedAgent) -> list[Any]:
    """
    Get VoiceLive modality enums from session config.

    Returns:
        List of Modality enums (TEXT, AUDIO).
    """
    from azure.ai.voicelive.models import Modality

    values = agent.session.get("modalities") if agent.session else None
    vals = [v.lower() for v in (values or ["TEXT", "AUDIO"])]
    out = []
    for v in vals:
        if v in ("text", "TEXT"):
            out.append(Modality.TEXT)
        elif v in ("audio", "AUDIO"):
            out.append(Modality.AUDIO)
    return out


def get_voicelive_audio_formats(agent: UnifiedAgent) -> tuple[Any, Any]:
    """
    Get input and output audio format enums for VoiceLive.

    Returns:
        Tuple of (InputAudioFormat, OutputAudioFormat).
    """
    from azure.ai.voicelive.models import InputAudioFormat, OutputAudioFormat

    in_fmt_str = (agent.session.get("input_audio_format") or "PCM16").lower()
    out_fmt_str = (agent.session.get("output_audio_format") or "PCM16").lower()

    in_fmt = InputAudioFormat.PCM16 if in_fmt_str == "pcm16" else InputAudioFormat.PCM16
    out_fmt = OutputAudioFormat.PCM16 if out_fmt_str == "pcm16" else OutputAudioFormat.PCM16

    return in_fmt, out_fmt


async def apply_voicelive_session(
    agent: UnifiedAgent,
    conn,
    *,
    system_vars: dict[str, Any] | None = None,
    say: str | None = None,
    session_id: str | None = None,
    call_connection_id: str | None = None,
) -> None:
    """
    Apply this agent's configuration to a VoiceLive session.

    Updates voice, VAD settings, instructions, and tools on the connection.
    Automatically injects the handoff_to_agent tool when the scenario has
    generic handoffs enabled or when the agent has outgoing edges defined.

    Args:
        conn: VoiceLive connection object
        system_vars: Runtime variables for prompt rendering
        say: Optional greeting text to trigger after session update
        session_id: Session ID for tracing
        call_connection_id: Call connection ID for tracing
    """
    from azure.ai.voicelive.models import (
        AudioInputTranscriptionOptions,
        RequestSession,
    )
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(
        f"invoke_agent {agent.name}",
        kind=SpanKind.INTERNAL,
        attributes={
            "component": "voicelive",
            "ai.user.id": session_id or "",
            "gen_ai.agent.name": agent.name,
            "gen_ai.agent.description": agent.description or "",
        },
    ) as span:
        # Render instructions
        system_vars = system_vars or {}
        system_vars.setdefault("active_agent", agent.name)
        instructions = agent.render_prompt(system_vars)

        # Build session components
        voice_payload = build_voicelive_voice(agent)
        vad = build_voicelive_vad(agent)
        modalities = get_voicelive_modalities(agent)
        in_fmt, out_fmt = get_voicelive_audio_formats(agent)
        tools = _build_voicelive_tools_with_handoffs(agent, session_id)

        logger.debug(
            "[%s] Applying session | voice=%s",
            agent.name,
            getattr(voice_payload, "name", None) if voice_payload else None,
        )

        # Voice is the field most likely to be silently dropped (SDK missing,
        # empty name, or a type the builder doesn't map), and the symptom —
        # "the TTS voice I picked isn't used" — is otherwise indistinguishable
        # from the service ignoring it. Log the exact request so it can be
        # diffed against the session.updated echo.
        if voice_payload is None:
            logger.warning(
                "[%s] voice_not_applied | configured=%r type=%r — no voice will be "
                "sent on session.update, the service default will be used",
                agent.name,
                getattr(agent.voice, "name", None),
                getattr(agent.voice, "type", None),
            )
        else:
            logger.info(
                "[%s] voice_requested | name=%s type=%s style=%s rate=%s",
                agent.name,
                getattr(voice_payload, "name", None),
                getattr(voice_payload, "type", None),
                getattr(voice_payload, "style", None),
                getattr(voice_payload, "rate", None),
            )

        # Build transcription settings
        transcription_cfg = agent.session.get("input_audio_transcription_settings") or {}
        transcription_kwargs: dict[str, Any] = {}
        if transcription_cfg.get("model"):
            transcription_kwargs["model"] = transcription_cfg["model"]
        if transcription_cfg.get("language"):
            transcription_kwargs["language"] = transcription_cfg["language"]

        input_audio_transcription = (
            AudioInputTranscriptionOptions(**transcription_kwargs) if transcription_kwargs else None
        )

        # Build session update kwargs
        kwargs: dict[str, Any] = dict(
            modalities=modalities,
            instructions=instructions,
            input_audio_format=in_fmt,
            output_audio_format=out_fmt,
            turn_detection=vad,
        )

        if input_audio_transcription:
            kwargs["input_audio_transcription"] = input_audio_transcription

        if voice_payload:
            kwargs["voice"] = voice_payload

        if tools:
            kwargs["tools"] = tools
            tool_choice = agent.session.get("tool_choice", "auto") if agent.session else "auto"
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

        # Apply session
        session_payload = RequestSession(**kwargs)
        await conn.session.update(session=session_payload)

        logger.info("[%s] Session updated successfully", agent.name)
        span.set_status(Status(StatusCode.OK))

        # Trigger greeting if provided
        if say:
            logger.info(
                "[%s] Triggering greeting: %s",
                agent.name,
                say[:50] + "..." if len(say) > 50 else say,
            )
            await trigger_voicelive_response(agent, conn, say=say)


async def trigger_voicelive_response(
    agent: UnifiedAgent,
    conn,
    *,
    say: str | None = None,
    cancel_active: bool = True,
) -> None:
    """
    Trigger a response from the agent on a VoiceLive connection.

    Args:
        conn: VoiceLive connection object
        say: Text for the agent to say verbatim
        cancel_active: If True, cancel any active response first
    """
    from azure.ai.voicelive.models import (
        ClientEventResponseCreate,
        ResponseCreateParams,
    )

    if not say:
        return

    # Cancel any active response first to avoid conflicts
    if cancel_active:
        await conn.response.cancel()

    # Create response with explicit instruction to say the greeting verbatim
    verbatim_instruction = (
        f"Say exactly the following greeting to the user, word for word. "
        f"Do not add anything before or after. Do not modify the wording:\n\n"
        f'"{say}"'
    )

    try:
        await conn.send(
            ClientEventResponseCreate(
                response=ResponseCreateParams(
                    instructions=verbatim_instruction,
                )
            )
        )
        logger.debug("[%s] Triggered verbatim greeting response", agent.name)
    except Exception as e:
        logger.warning("trigger_voicelive_response failed: %s", e)
        raise
