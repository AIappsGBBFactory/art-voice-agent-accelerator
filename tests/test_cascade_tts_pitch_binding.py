"""
Cascade TTS pitch binding — regression tests.

Verifies the fix for the Cascade voice.pitch gap identified in the Quick Tune
service-binding audit (tests/test_quick_tune_service_bindings.py):
``TTSPlayback.get_agent_voice()`` returned only ``(name, style, rate)`` and no
synthesis method in ``src/speech/text_to_speech.py`` accepted a ``pitch``
kwarg at all, so an agent's configured voice pitch never reached the actual
SSML sent to Azure for a real (ACS/browser) call.

These tests exercise the REAL production functions end-to-end:
``UnifiedAgent``/``VoiceConfig`` -> ``TTSPlayback.get_agent_voice()`` ->
``TTSPlayback._synthesize`` / ``TTSPlayback._iter_synth_chunks`` (used by both
the browser and ACS transports, blocking and streaming) -> the real
``SpeechSynthesizer.synthesize_to_pcm`` / ``synthesize_to_pcm_stream`` SSML
construction. Only the actual Azure network boundary is mocked
(``speechsdk.SpeechSynthesizer`` / ``speechsdk.AudioDataStream``), so the
assertions are made against the literal SSML string that would be sent to
Azure, not against a mocked argument.
"""

from __future__ import annotations

import html
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import src.speech.text_to_speech as tts_module
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent, VoiceConfig
from apps.artagent.backend.voice.shared.context import TransportType, VoiceSessionContext
from apps.artagent.backend.voice.tts import playback as playback_module
from apps.artagent.backend.voice.tts.playback import TTSPlayback
from fastapi.websockets import WebSocketState

# =============================================================================
# Azure SDK network-boundary fakes
#
# These replace ONLY the classes that would otherwise open a real network
# connection (speechsdk.SpeechSynthesizer / speechsdk.AudioDataStream).
# Every other line of synthesize_to_pcm / synthesize_to_pcm_stream --
# SSML string construction, attribute escaping, style/rate/pitch handling --
# runs for real.
# =============================================================================

CAPTURED_SSML: list[str] = []


class _FakeAsyncOp:
    """Stand-in for the SDK's ``XxxAsync()`` result object; ``.get()`` is sync here."""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _FakeAudioDataStream:
    """Stand-in for ``speechsdk.AudioDataStream``; yields exactly one chunk then stops."""

    def __init__(self, result):
        self._result = result
        self._remaining_reads = 1
        self.status = tts_module.speechsdk.StreamStatus.AllData
        self.cancellation_details = None

    def read_data(self, buffer) -> int:
        if self._remaining_reads <= 0:
            return 0
        self._remaining_reads -= 1
        return len(buffer)


class _CapturingSpeechSynthesizer:
    """Stand-in for ``speechsdk.SpeechSynthesizer`` capturing the SSML it is asked to speak."""

    def __init__(self, speech_config=None, audio_config=None):
        self.speech_config = speech_config

    def speak_ssml_async(self, ssml: str) -> _FakeAsyncOp:
        CAPTURED_SSML.append(ssml)
        result = SimpleNamespace(
            reason=tts_module.speechsdk.ResultReason.SynthesizingAudioCompleted,
            audio_data=b"PCM-BYTES",
        )
        return _FakeAsyncOp(result)

    def start_speaking_ssml_async(self, ssml: str) -> _FakeAsyncOp:
        CAPTURED_SSML.append(ssml)
        return _FakeAsyncOp(SimpleNamespace())

    def stop_speaking_async(self) -> _FakeAsyncOp:
        return _FakeAsyncOp(None)


@pytest.fixture(autouse=True)
def _patch_azure_sdk_boundary(monkeypatch):
    """Replace only the network boundary; SSML construction stays real."""
    CAPTURED_SSML.clear()
    monkeypatch.setattr(tts_module.speechsdk, "SpeechSynthesizer", _CapturingSpeechSynthesizer)
    monkeypatch.setattr(tts_module.speechsdk, "AudioDataStream", _FakeAudioDataStream)
    yield


def _make_synth() -> tts_module.SpeechSynthesizer:
    """Real SpeechSynthesizer; a fake key keeps _create_speech_config() fully offline
    (speechsdk.SpeechConfig(subscription=..., region=...) never touches the network)."""
    return tts_module.SpeechSynthesizer(key="fake-test-key", region="eastus", enable_tracing=False)


# =============================================================================
# 1. SpeechSynthesizer.synthesize_to_pcm -- blocking (non-streaming) path
# =============================================================================
class TestSynthesizeToPcmPitchSSML:
    def test_true_mai_voice_identifier_reaches_ssml(self) -> None:
        synth = _make_synth()
        synth.synthesize_to_pcm(text="Hello there", voice="en-US-Harper:MAI-Voice-2")
        assert '<voice name="en-US-Harper:MAI-Voice-2">' in CAPTURED_SSML[0]

    def test_representative_pitch_reaches_prosody_tag(self) -> None:
        synth = _make_synth()

        audio = synth.synthesize_to_pcm(
            text="Hello there",
            voice="en-US-JennyNeural",
            style="cheerful",
            rate="+12%",
            pitch="-15%",
        )

        assert audio == b"PCM-BYTES"
        assert len(CAPTURED_SSML) == 1
        ssml = CAPTURED_SSML[0]
        assert '<prosody rate="+12%" pitch="-15%">Hello there</prosody>' in ssml
        assert '<mstts:express-as style="cheerful">' in ssml

    def test_default_pitch_is_omitted_and_byte_compatible_with_pre_fix_output(self) -> None:
        """Callers that never pass pitch (every call site before this fix) must
        get exactly the same SSML as before -- no ``pitch`` attribute at all."""
        synth = _make_synth()

        synth.synthesize_to_pcm(text="Hi", voice="en-US-JennyNeural", style="chat", rate="+3%")

        ssml = CAPTURED_SSML[0]
        assert '<prosody rate="+3%">Hi</prosody>' in ssml
        assert "pitch=" not in ssml

    def test_configured_but_unset_plus_zero_percent_pitch_is_also_omitted(self) -> None:
        """VoiceConfig's own "unset" sentinel is "+0%" (matches the sentinel
        VoiceLive's build_voicelive_voice() already uses for this field), so
        an agent that never touched the pitch control must not gain a no-op
        ``pitch="+0%"`` attribute on every single call."""
        synth = _make_synth()

        synth.synthesize_to_pcm(
            text="Hi", voice="en-US-JennyNeural", style="chat", rate="+3%", pitch="+0%"
        )

        assert "pitch=" not in CAPTURED_SSML[0]

    def test_pitch_value_is_escaped_for_safe_xml_attribute_embedding(self) -> None:
        """pitch is a free-text VoiceConfigSchema field with no format
        validation, so a value containing XML metacharacters must not be
        able to break out of the attribute or inject markup."""
        synth = _make_synth()
        malicious_pitch = '"><voice name="hacked"><prosody pitch="'

        synth.synthesize_to_pcm(
            text="Hi", voice="en-US-JennyNeural", rate="+0%", pitch=malicious_pitch
        )

        ssml = CAPTURED_SSML[0]
        assert html.escape(malicious_pitch, quote=True) in ssml
        assert malicious_pitch not in ssml
        assert '<voice name="hacked">' not in ssml

    def test_pooled_synthesizer_does_not_leak_pitch_across_consecutive_calls(self) -> None:
        """The same SpeechSynthesizer instance (as reused from the pool across
        sessions) must never carry a prior call's pitch into the next one."""
        synth = _make_synth()

        synth.synthesize_to_pcm(text="First", voice="en-US-JennyNeural", pitch="-25%")
        synth.synthesize_to_pcm(text="Second", voice="en-US-JennyNeural")  # no pitch this time

        assert 'pitch="-25%"' in CAPTURED_SSML[0]
        assert "pitch=" not in CAPTURED_SSML[1]


# =============================================================================
# 2. SpeechSynthesizer.synthesize_to_pcm_stream -- streaming path
# =============================================================================
class TestSynthesizeToPcmStreamPitchSSML:
    def test_representative_pitch_reaches_prosody_tag(self) -> None:
        synth = _make_synth()

        chunks = list(
            synth.synthesize_to_pcm_stream(
                text="Hello there",
                voice="en-US-JennyNeural",
                style="cheerful",
                rate="+12%",
                pitch="-15%",
            )
        )

        assert b"".join(chunks)
        assert len(CAPTURED_SSML) == 1
        assert '<prosody rate="+12%" pitch="-15%">Hello there</prosody>' in CAPTURED_SSML[0]

    def test_default_pitch_is_omitted(self) -> None:
        synth = _make_synth()

        list(synth.synthesize_to_pcm_stream(text="Hi", voice="en-US-JennyNeural"))

        assert "pitch=" not in CAPTURED_SSML[0]


# =============================================================================
# 3. End-to-end via TTSPlayback: real UnifiedAgent -> get_agent_voice() ->
#    _synthesize / _iter_synth_chunks -> real SpeechSynthesizer SSML.
#    Covers browser+ACS (both route through the same helpers) and both
#    streaming and non-streaming synthesis.
# =============================================================================
def _agent(pitch: str = "+0%", *, rate: str = "+8%", style: str = "cheerful") -> UnifiedAgent:
    return UnifiedAgent(
        name="Tester",
        tool_names=[],
        voice=VoiceConfig(name="en-US-JennyNeural", style=style, rate=rate, pitch=pitch),
    )


def _playback_for(agent: UnifiedAgent, synth: tts_module.SpeechSynthesizer) -> TTSPlayback:
    ctx = VoiceSessionContext(session_id="pitch-e2e")
    ctx.current_agent = agent
    ctx.tts_client = synth  # session-owned client; _get_tts_client() returns it directly
    return TTSPlayback(ctx, app_state=SimpleNamespace(speech_executor=None))


class TestTTSPlaybackEndToEndPitch:
    """get_agent_voice() now resolves a 4th (pitch) element, and both the
    blocking and streaming synth helpers forward it into real SSML."""

    def test_get_agent_voice_resolves_agent_pitch(self) -> None:
        agent = _agent(pitch="-20%")
        playback = _playback_for(agent, _make_synth())

        resolved = playback.get_agent_voice()

        assert resolved == ("en-US-JennyNeural", "cheerful", "+8%", "-20%")

    @pytest.mark.asyncio
    async def test_non_streaming_synthesize_carries_agent_pitch_into_real_ssml(self) -> None:
        synth = _make_synth()
        agent = _agent(pitch="-20%")
        playback = _playback_for(agent, synth)
        voice_name, style, rate, pitch = playback.get_agent_voice()

        pcm = await playback._synthesize(
            synth, "Hello", voice_name, style, rate, 16000, pitch=pitch
        )

        assert pcm == b"PCM-BYTES"
        assert '<prosody rate="+8%" pitch="-20%">Hello</prosody>' in CAPTURED_SSML[-1]

    @pytest.mark.asyncio
    async def test_streaming_synth_carries_agent_pitch_into_real_ssml(self) -> None:
        synth = _make_synth()
        agent = _agent(pitch="+18%")
        playback = _playback_for(agent, synth)
        voice_name, style, rate, pitch = playback.get_agent_voice()

        chunks = [
            chunk
            async for chunk in playback._iter_synth_chunks(
                synth, "Hello", voice_name, style, rate, 16000, pitch=pitch
            )
        ]

        assert b"".join(chunks)
        assert '<prosody rate="+8%" pitch="+18%">Hello</prosody>' in CAPTURED_SSML[-1]

    @pytest.mark.asyncio
    async def test_default_agent_pitch_produces_no_pitch_attribute_through_the_full_chain(
        self,
    ) -> None:
        """An agent that never touched the pitch control (VoiceConfig's own
        default, "+0%") must reach real synthesis with no ``pitch`` attribute
        at all -- the exact pre-fix SSML shape, preserved end-to-end."""
        synth = _make_synth()
        agent = _agent(pitch="+0%")
        playback = _playback_for(agent, synth)
        voice_name, style, rate, pitch = playback.get_agent_voice()

        await playback._synthesize(synth, "Hello", voice_name, style, rate, 16000, pitch=pitch)

        assert "pitch=" not in CAPTURED_SSML[-1]

    @pytest.mark.asyncio
    async def test_pooled_synth_does_not_leak_pitch_between_two_agents_sessions(self) -> None:
        """Same pooled SpeechSynthesizer instance serving two different
        agents/sessions back-to-back must not carry the first agent's pitch
        (or lack of one) into the second call -- no shared mutable state."""
        synth = _make_synth()

        agent_a = _agent(pitch="-25%")
        playback_a = _playback_for(agent_a, synth)
        voice_a, style_a, rate_a, pitch_a = playback_a.get_agent_voice()
        await playback_a._synthesize(synth, "First", voice_a, style_a, rate_a, 16000, pitch=pitch_a)

        agent_b = _agent(pitch="+0%")  # different session, default (no) pitch override
        playback_b = _playback_for(agent_b, synth)
        voice_b, style_b, rate_b, pitch_b = playback_b.get_agent_voice()
        await playback_b._synthesize(
            synth, "Second", voice_b, style_b, rate_b, 16000, pitch=pitch_b
        )

        assert 'pitch="-25%"' in CAPTURED_SSML[0]
        assert "pitch=" not in CAPTURED_SSML[1]

    @pytest.mark.asyncio
    async def test_stream_synth_to_browser_and_acs_both_forward_pitch(self) -> None:
        """Both transports call the same _stream_synth_to_* helpers with the
        pitch keyword argument; verify neither dropped it."""
        synth = _make_synth()
        agent = _agent(pitch="-9%")
        playback = _playback_for(agent, synth)
        ws = MagicMock()
        ws.send_json = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.application_state = WebSocketState.CONNECTED
        playback._context._websocket = ws
        voice_name, style, rate, pitch = playback.get_agent_voice()

        browser_ok = await playback._stream_synth_to_browser(
            synth, "Browser text", voice_name, style, rate, None, "run-browser", pitch=pitch
        )
        acs_ok = await playback._stream_synth_to_acs(
            synth, "ACS text", voice_name, style, rate, False, None, "run-acs", pitch=pitch
        )

        assert browser_ok is True
        assert acs_ok is True
        assert 'pitch="-9%">Browser text' in CAPTURED_SSML[0]
        assert 'pitch="-9%">ACS text' in CAPTURED_SSML[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("transport", [TransportType.BROWSER, TransportType.ACS])
async def test_public_playback_preserves_explicit_pitch_without_a_voice_name(
    monkeypatch, streaming, transport
):
    monkeypatch.setattr(playback_module, "_STREAMING_ENABLED", streaming)
    playback = _playback_for(_agent(pitch="-25%"), _make_synth())
    playback.context.transport = transport
    playback.context._websocket = SimpleNamespace(
        send_json=AsyncMock(),
        client_state=WebSocketState.CONNECTED,
        application_state=WebSocketState.CONNECTED,
    )
    pitch = '"+5%&'
    assert await playback.speak("Hello", voice_pitch=pitch)
    assert f'pitch="{html.escape(pitch, quote=True)}"' in CAPTURED_SSML[0]
    assert 'pitch="-25%"' not in CAPTURED_SSML[0]
    assert not playback.context.tts_client.has_active_synthesis
    await playback.aclose()


def test_pitch_refresh_reads_only_the_current_named_override(monkeypatch):
    original = _agent(pitch="-5%")
    edited = _agent(pitch="-25%")
    unrelated = UnifiedAgent(name="Other", voice=VoiceConfig(pitch="+50%"))
    monkeypatch.setattr(
        playback_module,
        "get_session_agent",
        lambda sid, name=None: edited if name == "Tester" else unrelated,
    )
    playback = _playback_for(original, _make_synth())
    assert playback.get_agent_voice()[3] == "-25%"
    assert original.voice.pitch == "-5%"


def test_initial_tts_binding_preserves_the_resolved_scenario_agent(monkeypatch):
    monkeypatch.setattr(playback_module, "get_session_agent", lambda *args: None)
    scenario_agent = _agent(pitch="-25%")
    playback = _playback_for(scenario_agent, _make_synth())
    playback._app_state.unified_agents = {"Tester": _agent(pitch="+3%")}
    playback.set_active_agent("Tester")
    assert playback.context.current_agent is scenario_agent
    assert playback.get_agent_voice()[3] == "-25%"
