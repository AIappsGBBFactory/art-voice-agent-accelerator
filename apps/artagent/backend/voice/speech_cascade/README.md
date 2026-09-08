# Cascade runtime ownership

`VoiceHandler` owns the browser/ACS Cascade session. Its existing transport
integration and the VoiceLive runtime remain separate; this is not an event bus
or a replacement agent framework.

## Turn and callback ownership

Typed text is submitted without awaiting model generation or interruption cleanup
in the browser receive loop. A tracked submission task applies text barge-in, then
enqueues a `SpeechEvent.FINAL`. The same `RouteTurnThread` asyncio worker processes
typed and recognized input, emits the final user transcript once, allocates/preserves
the canonical turn ID, and owns the response task. STT partial IDs, recognition
anchors, tool segment IDs, and turn telemetry keep their existing semantics.

The historical `SpeechSDKThread` name is import-compatible. Recognition already
runs on Speech SDK threads; `prepare_thread()` is a compatibility hook, not a
second Python thread. Provider start/stop calls still use the appropriate SDK
operations. Start work in an executor is joined even if startup is cancelled.

`ThreadBridge` captures the owning event loop before accepting events. SDK threads
only mutate a locked, bounded inbox. A coalesced loop callback drains it and is the
only place that mutates the asyncio speech queue. Late callbacks are rejected once
the bridge is closed.

| Buffer | Capacity | Overflow/backpressure |
| --- | --- | --- |
| Speech queue | 50 events per VoiceHandler | Evict the oldest partial for a non-partial event; otherwise reject the newest event and log a warning |
| SDK inbox | Speech queue capacity (50 if unbounded) | Same partial-first policy; at most one pending drain callback |
| SDK callback inbox / active tasks | 50 each | Reject newest callback at capacity and log; close cancels and awaits tracked tasks |
| LLM-to-TTS queue | 8 sentence chunks | Async producer awaits capacity; cancellation stops and joins the producer |
| TTS PCM bridge | 8 SDK chunks | Blocking producer uses bounded, cancellation-aware puts; consumer never blocks the event loop |

Overflow never falls back to an unbounded task or a blocking asyncio queue put
from an SDK thread. Speech queues are not intended as durable transcript storage.

## Model and speech producers

Cascade borrows `AoaiClientManager.get_async_client()` from the websocket's
application state. The application AOAI lifecycle step awaits `aclose()` on
shutdown. Existing synchronous `get_client()` consumers are unchanged.
Standalone `process_turn()` callers can inject `async_client`; otherwise a client
is scoped to the complete turn, including tool recursion and handoffs.

The model stream is an owned asyncio task. The task inherits the turn's telemetry
context, closes the HTTP stream on completion/cancellation, and is awaited before
the turn finishes. A 90-second streaming deadline includes downstream TTS waits.
There is no per-model-call `AzureOpenAIManager` or detached synchronous iterator.
Handoff detection suppresses queued pre-handoff text as well as later deltas.

Each Speech TTS operation has its own `threading.Event`, which is never cleared
for reuse. `cancel()` also invalidates a playback generation: clearing the shared
session cancel flag for the next turn cannot revive older audio. Audio writes and
transport stop messages share a send lock, including browser `audio_stop` and ACS
`StopAudio`. Buffered-playback tracking, voices/prosody, greetings, return greetings,
and the pre-speech guard are preserved.

The Speech provider registers each active PCM synthesizer per instance. Stop
reaches the actual synthesizer serving `AudioDataStream.read_data`, not just the
optional local speaker. Generator cleanup awaits provider stop acknowledgement.
The async bridge explicitly closes its generator on early consumer exit and joins
the executor operation before relinquishing its pool lease.

## Shutdown and failure paths

`VoiceHandler.stop()` shares one shielded shutdown task among callers. It closes
the callback bridge, stops recognition, cancels/awaits response and auxiliary
tasks, and awaits `TTSPlayback.aclose()` before releasing leases. A failure of one
pool release does not prevent attempting the other. Failures during construction,
configuration, STT acquisition, or partial startup roll back acquired resources;
rollback always uses `release_for_session(session_id, resource)`.

STT shutdown calls the production recognizer's blocking `stop()`, which waits for
`stop_continuous_recognition_async().get()` before reporting success. The async
owner runs this once in retained worker work with a 10-second acknowledgement
deadline. Timeout or caller cancellation does not cancel that native work.
Repeated wrapper callers await the same operation; native failures propagate and
late failures are observed. Callback suppression alone is not stop acknowledgement.
If shutdown fails, `VoiceHandler.stop()` retains its failed result and withholds
the speech leases, even if native work completes later.

TTS waits at most 30 seconds for another streaming chunk and 10 seconds for
producer stop acknowledgement. If a provider cannot quiesce, cleanup raises and
does not return a still-active client to the pool. Fix the provider/service failure
rather than reusing that resource. Native work cannot safely be killed by cancelling
its asyncio Future.

MemoManager hydration and ordered persistence remain the storage workstream's
contract. This component introduces no alternative session-state model.
