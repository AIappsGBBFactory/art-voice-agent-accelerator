# Voice runtime ownership

The runtime has two native engines and three channel integrations, not a generic
event bus. Agent definitions, tool effects, routing policy and close postconditions
are shared; provider execution remains native.

| Channel | Cascade | VoiceLive |
| --- | --- | --- |
| Browser | `VoiceHandler` | `VoiceLiveSDKHandler` |
| ACS | `VoiceHandler` | `VoiceLiveSDKHandler` |
| Genesys AudioHook | Not supported | `GenesysVoiceLiveHandler` |

## Where changes belong

| Concern | Owner |
| --- | --- |
| Tool argument validation, identity/profile/slot effects, exposed handoff schemas | `shared/tool_policy.py` |
| Scenario route selection and context-sharing permissions | `shared/handoff_service.py` |
| Agent/scenario definition projection and validation | `../registries/definitions.py` and existing dataclasses |
| VoiceLive SDK session settings and greeting requests | `voicelive/session.py` |
| Cascade turn/model/TTS sequencing | `speech_cascade/orchestrator.py` |
| VoiceLive response-ID batches and continuation epochs | `voicelive/orchestrator.py` |
| Native lifecycle ownership | `handler.py`, `voicelive/handler.py`, `genesys/handler.py` |
| Bounded task joins and strict final snapshot/flush | `shared/close.py` |
| Current memo lookup and async definition priming | `../src/orchestration/session_memory.py` |
| STT callback ingress and serialized turns | `speech_cascade/handler.py` (`ThreadBridge`, SDK and turn workers) |
| Speech synthesis, streaming and cancellation | `tts/playback.py` and `src/speech/` |
| Markdown cleanup and sentence boundaries | `speech_cascade/tts_processor.py` |

## Caller-facing close contract

Use `await handler.stop()` in a `finally`. Concurrent and later callers await the
same retained, shielded cleanup task and observe the same completion or failure.
Cancelling a caller does not cancel cleanup. A closed handler cannot restart.
An owned producer that initiates close can itself receive cancellation while the
retained cleanup finishes; a supervisor can await `stop()` again.

Cleanup joins startup and native producers before capturing the final memo.
With Redis configured, it awaits `persist_to_redis_async(..., raise_on_failure=True)`
and always awaits `flush_pending_persist(raise_on_failure=True)`. Local-only
sessions skip the Redis snapshot but still drain submitted work.

Unacknowledged native work is retained/quarantined: no stable final snapshot and
no speech lease recycling are claimed. Already-submitted persistence is still
drained and independent safe cleanup is attempted. Persistence failure after
producer quiescence does not leak otherwise safe leases. Failed cleanup is not
silently retried; late provider completion does not turn its retained failure
into success. Endpoint cleanup is separately retained: browser keeps analytics
and socket work independent; ACS/media and Genesys also attempt safe session and
socket cleanup and propagate failures rather than labelling a failed stop OK.
Registry entries are detached without releasing quarantined native leases.

## Extension and component references

- [Human extension guide](../../../../docs/voice-extension-guide.md)
- [MemoManager ordering and limits](../../../../docs/memo-persistence.md)
- [Cascade native ownership](speech_cascade/README.md)
- [VoiceLive reader and response lifecycle](voicelive/README.md)
- [Genesys audio and protocol ownership](genesys/README.md)

The unused `SessionAgentManager`, aggregate `SpeechCascadeHandler`, deprecated
Cascade continuation/factory wrappers, and test-only VoiceLive pending-output
path are removed. Low-level SDK/thread/audio components remain supported.
Public WebSocket TTS helpers remain because the development sample
`samples/labs/dev/gpt_flow.py` still consumes them; they are not a second engine.
