"""
Quick Tune / Advanced Builder field-binding audit.

Traces representative, *changed* values for every field exposed by
``QuickTuneAgentEditor.jsx`` and ``ScenarioFlowEditor.jsx`` through
``frontend/utils/quickTune.js`` -> transport schemas -> ``build_session_agent``
-> the stored ``UnifiedAgent`` / ``ScenarioConfig`` -> the Cascade and
VoiceLive consumers -> real Azure SDK model construction.

Scope is intentionally narrow: this file targets bindings NOT already
covered by ``test_quick_tune_agent_precision.py`` (session persistence /
live-push semantics), ``test_cascade_session_speech_settings.py`` (STT
VAD/segmentation/candidate_languages reaching the pooled recognizer),
``test_voicelive_byom_config.py`` (BYOM dataclass + connect-time query),
and ``test_scenario_authoring_runtime.py`` (scenario-scoped VoiceLive
startup model, handoff instructions, cached routing). Those are treated
as already-verified and are not repeated here.

Every test uses the *real* production function (``UnifiedAgent.build_voicelive_voice``,
``UnifiedAgent.build_voicelive_vad``, ``UnifiedAgent.apply_voicelive_session``,
``CascadeOrchestratorAdapter._prepare_streaming_params``, ``TTSPlayback.get_agent_voice``
+ ``TTSPlayback._synthesize``, ``apply_scenario_overrides``,
``ScenarioConfig.get_generic_handoff_config``) and, where a real Azure SDK
model is constructed (``azure.ai.voicelive.models``), asserts against the
real serialized model rather than a stub. Only the network boundary
(``conn.session.update``, the pooled TTS synthesizer) is mocked.

These assertions cover supported SDK registration after the binding fixes.
They do not establish live Azure acceptance or model/region availability.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.registries.agentstore.base import (
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.registries.scenariostore.loader import (
    AgentOverride,
    HandoffConfig,
    ScenarioConfig,
    apply_scenario_overrides,
)
from apps.artagent.backend.voice.shared.context import VoiceSessionContext
from apps.artagent.backend.voice.shared.handoff_service import HandoffService
from apps.artagent.backend.voice.speech_cascade.orchestrator import CascadeOrchestratorAdapter
from apps.artagent.backend.voice.tts.playback import TTSPlayback
from azure.ai.voicelive.models import (
    AzureSemanticVad,
    AzureStandardVoice,
    RequestSession,
    ServerVad,
)


# =============================================================================
# 1. VOICE — VoiceLive real SDK construction
#    UI: QuickTuneAgentEditor.jsx voice name/rate + "Fine controls" style/pitch
#    Path: DynamicAgentConfig.voice -> build_session_agent (agent_builder.py:1204-1211)
#          -> UnifiedAgent.voice -> UnifiedAgent.build_voicelive_voice() (base.py:934-967)
#          -> azure.ai.voicelive.models.AzureStandardVoice
# =============================================================================
class TestVoiceLiveVoiceBinding:
    """PASS: name/rate/style/pitch all reach the real AzureStandardVoice model."""

    def test_style_pitch_rate_reach_real_azure_standard_voice(self) -> None:
        agent = UnifiedAgent(
            name="Tester",
            tool_names=[],
            voice=VoiceConfig(
                name="en-US-JennyNeural",
                type="azure-standard",
                style="cheerful",
                pitch="-15%",
                rate="+12%",
            ),
        )

        voice_payload = agent.build_voicelive_voice()

        # base.py:966-967 only omits a field when it is exactly the "+0%" default;
        # style/pitch/rate here are all non-default, so all three must survive.
        assert isinstance(voice_payload, AzureStandardVoice)
        assert dict(voice_payload) == {
            "type": "azure-standard",
            "name": "en-US-JennyNeural",
            "style": "cheerful",
            "pitch": "-15%",
            "rate": "+12%",
        }

    def test_default_rate_and_pitch_are_omitted_but_name_always_present(self) -> None:
        agent = UnifiedAgent(
            name="Tester", tool_names=[], voice=VoiceConfig(name="en-US-AvaMultilingualNeural")
        )

        voice_payload = agent.build_voicelive_voice()

        assert isinstance(voice_payload, AzureStandardVoice)
        payload = dict(voice_payload)
        assert "rate" not in payload  # "+0%" is the skip sentinel (base.py:966)
        assert "pitch" not in payload
        # NOTE: VoiceConfigSchema's style default is "chat" (agent_builder.py:63),
        # not "+0%", so style is never skipped by the same sentinel check and is
        # always sent — even when the user never touched it in Quick Tune.
        assert payload["style"] == "chat"


# =============================================================================
# 2. TURN DETECTION (VAD) — VoiceLive real SDK construction
#    UI: QuickTuneAgentEditor.jsx "Fine controls" speech sensitivity / prefix
#        padding sliders (session.turn_detection_threshold / prefix_padding_ms)
#        and the read-only turn-detection-type chip.
#    Path: build_session_agent (agent_builder.py:1233-1238) -> UnifiedAgent.session
#          -> UnifiedAgent.build_voicelive_vad() (base.py:975-1000)
#          -> azure.ai.voicelive.models.AzureSemanticVad / ServerVad
# =============================================================================
class TestVoiceLiveTurnDetectionBinding:
    """PASS: threshold/silence_duration_ms/prefix_padding_ms + type selection
    all reach the real SDK VAD models, for both supported turn_detection_type
    values."""

    @pytest.mark.parametrize(
        "vad_type,expected_cls",
        [("azure_semantic_vad", AzureSemanticVad), ("server_vad", ServerVad)],
    )
    def test_representative_vad_values_reach_real_sdk_model(self, vad_type, expected_cls) -> None:
        agent = UnifiedAgent(
            name="Tester",
            tool_names=[],
            session={
                "turn_detection": {
                    "type": vad_type,
                    "threshold": 0.42,
                    "silence_duration_ms": 650,
                    "prefix_padding_ms": 180,
                }
            },
        )

        vad = agent.build_voicelive_vad()

        assert isinstance(vad, expected_cls)
        assert dict(vad) == {
            "type": vad_type,
            "threshold": 0.42,
            "silence_duration_ms": 650,
            "prefix_padding_ms": 180,
        }


# =============================================================================
# 3. apply_voicelive_session — end-to-end session.update payload
#    Real UnifiedAgent.apply_voicelive_session with a mocked connection (the
#    only mocked boundary is the network: conn.session.update).
# =============================================================================
class TestApplyVoiceliveSessionPayload:
    """Verify supported settings against the actual SDK session-update model.

    These are serialization/registration checks, not live Azure acceptance.
    Model identity and BYOM remain connect-time settings; reasoning and Top P
    are not fields on the VoiceLive RequestSession contract.
    """

    @staticmethod
    def _agent(**session_overrides) -> UnifiedAgent:
        session = {
            "modalities": ["TEXT", "AUDIO"],
            "input_audio_format": "PCM16",
            "output_audio_format": "PCM16",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.35,
                "silence_duration_ms": 900,
                "prefix_padding_ms": 150,
            },
            "tool_choice": "auto",
            "input_audio_transcription_settings": {
                "model": "azure-speech",
                "language": "es-ES",
                "custom_speech": {"endpoint_id": "custom-123"},
                "phrase_list": ["Contoso", "routing number"],
            },
        }
        session.update(session_overrides)
        return UnifiedAgent(
            name="Tester",
            prompt_template="Hello {{agent_name}}",
            tool_names=[],
            voice=VoiceConfig(
                name="en-US-JennyNeural",
                type="azure-standard",
                style="cheerful",
                pitch="-15%",
                rate="+12%",
            ),
            voicelive_model=ModelConfig(
                deployment_id="gpt-realtime",
                temperature=0.9,
                max_tokens=999,
                reasoning_effort="high",
            ),
            session=session,
        )

    @staticmethod
    def _mock_conn() -> SimpleNamespace:
        return SimpleNamespace(
            session=SimpleNamespace(update=AsyncMock()),
            response=SimpleNamespace(cancel=AsyncMock()),
        )

    @pytest.mark.asyncio
    async def test_voice_and_vad_reach_real_request_session(self) -> None:
        agent = self._agent()
        conn = self._mock_conn()

        await agent.apply_voicelive_session(conn, session_id=None)

        conn.session.update.assert_awaited_once()
        session_payload = conn.session.update.call_args.kwargs["session"]
        assert isinstance(session_payload, RequestSession)
        assert dict(session_payload.voice) == {
            "type": "azure-standard",
            "name": "en-US-JennyNeural",
            "style": "cheerful",
            "pitch": "-15%",
            "rate": "+12%",
        }
        assert dict(session_payload.turn_detection) == {
            "type": "server_vad",
            "threshold": 0.35,
            "silence_duration_ms": 900,
            "prefix_padding_ms": 150,
        }

    @pytest.mark.asyncio
    async def test_all_supported_transcription_options_reach_session(
        self,
    ) -> None:
        agent = self._agent()
        conn = self._mock_conn()

        await agent.apply_voicelive_session(conn, session_id=None)

        session_payload = conn.session.update.call_args.kwargs["session"]
        transcription = session_payload.input_audio_transcription
        assert transcription.model == "azure-speech"
        assert transcription.language == "es-ES"
        assert transcription.custom_speech == {"endpoint_id": "custom-123"}
        assert transcription.phrase_list == ["Contoso", "routing number"]

    @pytest.mark.asyncio
    async def test_supported_model_controls_reach_session(self) -> None:
        agent = self._agent()
        conn = self._mock_conn()

        await agent.apply_voicelive_session(conn, session_id=None)

        session_payload = conn.session.update.call_args.kwargs["session"]
        assert session_payload.temperature == 0.9
        assert session_payload.max_response_output_tokens == 999
        assert "reasoning_effort" not in dict(session_payload)
        # Model identity is intentionally NOT part of session.update — it is
        # bound only at connect() time via deployment_id (by design, see
        # voicelive/handler.py:1098-1106); this assertion documents that
        # contract rather than flagging it as a gap.
        assert session_payload.model is None

    @pytest.mark.asyncio
    async def test_invalid_voicelive_temperature_is_not_silently_clamped(self) -> None:
        agent = self._agent()
        agent.voicelive_model.temperature = 1.5
        conn = self._mock_conn()
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            await agent.apply_voicelive_session(conn)
        conn.session.update.assert_not_awaited()


# =============================================================================
# 4. CASCADE TTS — voice rate, style, and pitch reach the pooled synthesizer.
#    UI: QuickTuneAgentEditor.jsx "Fine controls" -> voice.pitch/style + the
#        top-level voice.rate slider (shared with VoiceLive).
#    Path: build_session_agent (agent_builder.py:1204-1211) -> UnifiedAgent.voice
#          -> TTSPlayback.get_agent_voice() -> TTSPlayback._synthesize
#          -> synth.synthesize_to_pcm(..., style=..., rate=..., pitch=...)
# =============================================================================
class TestCascadeVoiceBinding:
    """Name, rate, style, and pitch reach the request-local synthesis call.

    Literal SSML construction, escaping, and pooled-client isolation are covered
    by test_cascade_tts_pitch_binding.py.
    """

    @staticmethod
    def _tts_playback(agent: UnifiedAgent) -> TTSPlayback:
        ctx = VoiceSessionContext(session_id="cascade-pitch-test")
        ctx.current_agent = agent
        return TTSPlayback(ctx, app_state=SimpleNamespace(speech_executor=None))

    def test_get_agent_voice_returns_every_configured_voice_option(self) -> None:
        agent = UnifiedAgent(
            name="Tester",
            tool_names=[],
            voice=VoiceConfig(
                name="en-US-JennyNeural", rate="+12%", style="cheerful", pitch="-15%"
            ),
        )
        tts = self._tts_playback(agent)

        resolved = tts.get_agent_voice()

        assert resolved == ("en-US-JennyNeural", "cheerful", "+12%", "-15%")

    @pytest.mark.asyncio
    async def test_synth_call_receives_rate_style_and_pitch(self) -> None:
        agent = UnifiedAgent(
            name="Tester",
            tool_names=[],
            voice=VoiceConfig(
                name="en-US-JennyNeural", rate="+12%", style="cheerful", pitch="-15%"
            ),
        )
        tts = self._tts_playback(agent)
        voice_name, style, rate, pitch = tts.get_agent_voice()

        synth = Mock()
        synth.synthesize_to_pcm = Mock(return_value=b"PCM-BYTES")

        result = await tts._synthesize(synth, "hello world", voice_name, style, rate, pitch, 16000)

        assert result == b"PCM-BYTES"
        call_kwargs = synth.synthesize_to_pcm.call_args.kwargs
        assert call_kwargs["voice"] == "en-US-JennyNeural"
        assert call_kwargs["style"] == "cheerful"
        assert call_kwargs["rate"] == "+12%"
        assert call_kwargs["pitch"] == "-15%"


# =============================================================================
# 5. CASCADE MODEL ADVANCED SETTINGS — supported options reach the request.
#    UI: Advanced Builder model config (ModelConfigSchema fields not exposed
#        directly in Quick Tune, but round-tripped through it per
#        editableAgent()/liveSettingsPatch in quickTune.js).
#    Path: build_session_agent (agent_builder.py:1134-1156 _model_from_schema)
#          -> ModelConfig -> CascadeOrchestratorAdapter._prepare_streaming_params
#          (orchestrator.py:2234-2320) -> client.chat.completions.create(**params)
#          (orchestrator.py:1684, api_params = streaming_params)
# =============================================================================
class TestCascadeModelAdvancedSettings:
    """Supported settings reach the actual request; unsupported sampling is rejected.

    Endpoint dispatch, Responses event conversion, version overrides, and invalid
    options are covered in test_cascade_model_request_binding.py.
    """

    @staticmethod
    def _model_config(**overrides) -> ModelConfig:
        base = dict(
            deployment_id="gpt-4o",
            temperature=0.55,
            top_p=0.8,
            max_tokens=555,
            reasoning_effort=None,
            include_reasoning=False,
            verbosity=0,
            store=True,
            metadata={"trace": "abc"},
            response_format={"type": "json_object"},
            min_p=None,
            typical_p=None,
            api_version="2025-01-01-preview",
        )
        base.update(overrides)
        return ModelConfig(**base)

    def test_temperature_top_p_and_token_limit_reach_the_actual_llm_call(self) -> None:
        model_config = self._model_config()
        messages = [{"role": "user", "content": "hi"}]

        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", messages, None
        )

        assert params["model"] == "gpt-4o"
        assert params["temperature"] == 0.55
        assert params["top_p"] == 0.8
        assert params["max_tokens"] == 555

    def test_supported_advanced_options_reach_the_actual_llm_call(self) -> None:
        model_config = self._model_config(
            deployment_id="gpt-5", model_family="gpt-5", reasoning_effort="high", verbosity=2
        )
        messages = [{"role": "user", "content": "hi"}]

        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-5", messages, None
        )

        assert params["reasoning_effort"] == "high"
        assert params["verbosity"] == "high"
        assert params["store"] is True
        assert params["metadata"] == {"trace": "abc"}
        assert params["response_format"] == {"type": "json_object"}

    def test_reasoning_model_receives_requested_effort(
        self,
    ) -> None:
        model_config = self._model_config(
            deployment_id="gpt-5", model_family="gpt-5", reasoning_effort="low"
        )
        messages = [{"role": "user", "content": "hi"}]

        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-5", messages, None
        )

        assert "max_completion_tokens" in params
        assert params["reasoning_effort"] == "low"
        assert "verbosity" not in params


# =============================================================================
# 6. SCENARIO — global_template_vars / agent_defaults precedence
#    UI: ScenarioDraftComposer.jsx "Scenario context" fields write
#        scenario.global_template_vars (quickTune.js has no dedicated helper;
#        the composer patches the scenario object directly).
#    Path: DynamicScenarioConfig.global_template_vars (scenario_builder.py
#          schema) -> update_session_scenario (scenario_builder.py:711-796,
#          builds ScenarioConfig 1:1) -> scenariostore.loader.apply_scenario_overrides
#          (loader.py:565-590) -> UnifiedAgent.template_vars used by render_prompt
#          (base.py:593-624, "defaults < template_vars < filtered runtime context")
# =============================================================================
class TestScenarioGlobalTemplateVarsPrecedence:
    """PASS: precedence is agent.template_vars < scenario.global_template_vars
    < scenario.agent_defaults.template_vars, and agent_defaults.voice_name/
    voice_rate override the per-agent voice — all real, unmocked dataclasses."""

    def test_global_template_vars_and_agent_defaults_merge_with_correct_precedence(self) -> None:
        agent_a = UnifiedAgent(
            name="A",
            tool_names=[],
            template_vars={"bank_name": "AgentBank", "tier": "gold"},
            voice=VoiceConfig(name="en-US-AvaMultilingualNeural", rate="+0%"),
        )
        scenario = ScenarioConfig(
            name="s",
            agents=["A"],
            global_template_vars={"bank_name": "ScenarioBank", "hours": "9-5"},
            agent_defaults=AgentOverride(
                template_vars={"bank_name": "OverrideBank"},
                voice_name="en-US-GuyNeural",
                voice_rate="-10%",
            ),
        )

        result = apply_scenario_overrides(scenario, {"A": agent_a})

        assert result["A"].template_vars == {
            "bank_name": "OverrideBank",  # agent_defaults wins
            "tier": "gold",  # untouched agent-level var survives
            "hours": "9-5",  # scenario-level var is added
        }
        assert result["A"].voice.name == "en-US-GuyNeural"
        assert result["A"].voice.rate == "-10%"
        # Session-safe copy: the source agent passed in must be untouched.
        assert agent_a.template_vars == {"bank_name": "AgentBank", "tier": "gold"}
        assert agent_a.voice.name == "en-US-AvaMultilingualNeural"

    def test_merged_template_vars_actually_change_the_rendered_prompt(self) -> None:
        agent_a = UnifiedAgent(
            name="A",
            tool_names=[],
            prompt_template="Welcome to {{ bank_name }}, hours {{ hours }}.",
            template_vars={"bank_name": "AgentBank"},
        )
        scenario = ScenarioConfig(
            name="s",
            agents=["A"],
            global_template_vars={"bank_name": "ScenarioBank", "hours": "9-5"},
        )

        result = apply_scenario_overrides(scenario, {"A": agent_a})

        assert result["A"].render_prompt({}) == "Welcome to ScenarioBank, hours 9-5."
        # The un-overridden source agent renders its own (different) prompt.
        assert "AgentBank" in agent_a.render_prompt({})


def test_named_handoff_tools_use_session_scenario_route_settings() -> None:
    agents = {name: UnifiedAgent(name=name) for name in ("Entry", "Silent", "Announced")}
    scenario = ScenarioConfig(
        name="Unpublished session-scoped scenario",
        agents=list(agents),
        handoffs=[
            HandoffConfig(
                from_agent="Entry",
                to_agent="Silent",
                tool="handoff_silent",
                type="discrete",
                share_context=False,
                context_vars={"topic": "private routing"},
            ),
            HandoffConfig(
                from_agent="Entry",
                to_agent="Announced",
                tool="handoff_announced",
                type="announced",
                share_context=True,
            ),
        ],
    )
    service = HandoffService(
        scenario_name=scenario.name,
        scenario=scenario,
        agents=agents,
        handoff_map=scenario.build_handoff_map(),
    )
    silent = service.resolve_handoff("handoff_silent", {}, "Entry", {})
    announced = service.resolve_handoff("handoff_announced", {}, "Entry", {})
    assert silent.success and announced.success
    assert silent.target_agent == "Silent"
    assert silent.handoff_type == "discrete"
    assert silent.share_context is False
    assert silent.greet_on_switch is False
    assert announced.target_agent == "Announced"
    assert announced.handoff_type == "announced"
    assert announced.share_context is True


# =============================================================================
# 7. SCENARIO — handoff type / share_context / tool resolve per-target,
#    not globally, for the ScenarioFlowEditor.jsx route fields.
#    UI: ScenarioFlowEditor.jsx handoff_condition / from_agent / to_agent /
#        tool / type (announced|discrete) / share_context.
#    Path: HandoffConfigSchema (scenario_builder.py schema) -> update_session_scenario
#          (scenario_builder.py:772-786, builds loader.HandoffConfig 1:1) ->
#          ScenarioConfig.get_generic_handoff_config (loader.py:314-350), the
#          method HandoffService actually calls for the generic handoff_to_agent
#          tool (voice/shared/handoff_service.py:658).
# =============================================================================
class TestScenarioHandoffRoutingBinding:
    """PASS: two outgoing edges from the same source agent, with different
    ``type``/``share_context``/``handoff_condition`` per target, resolve
    independently — a route to B never leaks A's route-to-C settings."""

    def test_two_routes_from_same_agent_resolve_independently(self) -> None:
        scenario = ScenarioConfig(
            name="routes",
            agents=["A", "B", "C"],
            handoffs=[
                HandoffConfig(
                    from_agent="A",
                    to_agent="B",
                    tool="handoff_to_agent",
                    type="discrete",
                    share_context=False,
                    handoff_condition="cond-b",
                ),
                HandoffConfig(
                    from_agent="A",
                    to_agent="C",
                    tool="handoff_to_agent",
                    type="announced",
                    share_context=True,
                    handoff_condition="cond-c",
                ),
            ],
        )

        cfg_b = scenario.get_generic_handoff_config("A", "B")
        cfg_c = scenario.get_generic_handoff_config("A", "C")

        assert cfg_b is not None and cfg_b.type == "discrete" and cfg_b.share_context is False
        assert cfg_b.handoff_condition == "cond-b"
        assert cfg_b.greet_on_switch is False

        assert cfg_c is not None and cfg_c.type == "announced" and cfg_c.share_context is True
        assert cfg_c.handoff_condition == "cond-c"
        assert cfg_c.greet_on_switch is True

    def test_target_with_no_defined_edge_is_not_silently_allowed_without_generic_handoff(
        self,
    ) -> None:
        # Only A->B is defined and generic_handoff defaults to disabled
        # (GenericHandoffConfig.enabled default), so a handoff_to_agent call
        # aimed at an undefined target must be rejected (None), not silently
        # default-allowed with made-up type/share_context.
        scenario = ScenarioConfig(
            name="routes",
            agents=["A", "B", "C"],
            handoffs=[
                HandoffConfig(from_agent="A", to_agent="B", tool="handoff_to_agent"),
            ],
        )

        assert scenario.get_generic_handoff_config("A", "C") is None
