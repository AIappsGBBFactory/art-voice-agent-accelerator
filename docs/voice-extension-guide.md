# Extending the voice runtime

This is an ownership guide, not a new orchestration framework. Supported pairs
remain browser/ACS with Cascade or VoiceLive, and Genesys with VoiceLive only.
Paths below are relative to `apps/artagent/backend/` unless explicitly rooted.

## Change tool identity, profile or slot policy

Edit `voice/shared/tool_policy.py`. `tool_arguments` validates JSON-object inputs
and injects session-owned caller context. `normalize_tool_result` preserves
external dictionary schemas. `apply_tool_result` commits tool outputs, slots,
authenticated identity and successful profile fields synchronously, before
notification or spoken-continuation awaits. Failed operations may still collect
slots; authentication and successful-profile effects retain their existing
independent conditions rather than acquiring a new blanket authorization gate.

Both native loops use these functions. Engine files still own provider protocol,
MFA/DTMF actions, transfer ordering and continuation. A new domain-specific tool
still uses the existing toolstore registry. Route/target/context-sharing policy
belongs to `voice/shared/handoff_service.py` and scenario declarations, not a
second tool-name-to-agent decision inside either engine.

Exercise `tests/test_voice_tool_policy_contract.py` and native handoff/tool tests:
mixed business/handoff batches must commit business effects first, interruptions
must not erase committed effects, and an old response must not complete a newer
batch. A cancelled tool that never returns does not promise a business result.

Cascade carries `HandoffResolution.system_vars` into the actual target prompt
and the target's subsequent live turns, not just its greeting. Transport metadata
and the session's durable business profile are not substituted for that resolved
prompt scope. Scenario context variables remain authoritative; do not reconstruct
the target context from raw model arguments or add another sharing filter.

VoiceLive collects controls until the complete response batch is known, publishes
business outputs before routing, and keeps that work off the reader. Test both
argument-arrival orders and cancellation during tool execution and SDK session
updates. Logical scenario/agent replacement advances ownership immediately, even
when an old finalizer is detached and there is no active response ID.

For native handoff await changes, use the existing `_HandoffTransition` epoch
and `_run_handoff_transition` sequence. Claim ownership before the first await,
snapshot history once, and check ownership before each subsequent submission.
Only that transition initiates its handoff response; startup greeting delivery
must not compete with it. Acknowledgement and completion can arrive in either
order, and cleanup releases only the matching owner. Do not reintroduce a shared
handoff-pending Boolean. Extend `test_voicelive_handoff_transition.py` with a
held provider await plus replacement/acknowledgement, rather than setting a
private protection flag to simulate a successful handoff.

An executed tool's completion notification has its own lifetime: report it once
even if routing is superseded during cancel, playback, session application,
replay, or response creation. Keep the actual tool outcome and use the
notification-only `handoff_transition` metadata to distinguish routing status.
This is a single notification attempt through the existing messenger, not
durable exactly-once delivery or an atomic provider transition.

## Add a model, voice, speech or scenario field

Add the declared field/default to the existing dataclass in
`registries/agentstore/base.py` or `registries/scenariostore/loader.py`.
`registries/definitions.py` derives validation, projection and builder schema
fields from those declarations. YAML file resolution/default merging remains
the loader's job; the resulting record uses the same codec as persistence and
builder conversions. API classes add only editor constraints, presets or aliases.
Do not create another field-copy/default map.

For API aliases such as `prompt`/`tools` or flat turn-detection controls, update
the thin alias projection, not the neutral definition. Builder creation keeps
its intentional model/voice presets; explicit separate legacy/Cascade/VoiceLive
models survive editing. Explicit empty containers and nullable fields are not
generically replaced by defaults. YAML inheritance and editor presets are
intentional boundary-specific behavior, not identical input formats.
In particular, mode-model presets apply only when a builder field is omitted.
An explicit `cascade_model: null` or `voicelive_model: null` survives API
projection/parse/build and retains the generic model fallback.

For Quick Tune, use `src/orchestration/session_agents.session_agent_for_edit`.
Resolve the actual current native agent before looking up its override; an
unrelated customized agent is never a fallback for a known identity. The helper
installs a deep-owned definition in the live registry before mutation, shared
with the persisted view. New nested definition fields inherit that isolation
without another manually maintained cloning map.

`source_dir` round-trips in canonical storage. It is not a client-writable builder
field because it can locate executable custom tools. An update of the same
server-known agent preserves its trusted provenance. SDK conversion and sends
belong to `voice/voicelive/session.py`, not `UnifiedAgent`.

Exercise builder endpoint, scenario, session-agent roundtrip and SDK payload
tests. Include explicit empty/null values, multiple agents/scenarios, BYOM,
MCP references, provenance and refresh from an empty worker cache. Provider
support for a setting still requires the appropriate native consumer change.

## Change native lifetime or persistence

Keep the lifecycle owner in the relevant handler. There is no shared manager
superclass: `voice/shared/close.py` supplies bounded joins and the strict final
snapshot/flush sequence. Retained/shielded close owns cleanup independently of
its callers. Join in-progress startup and producers, then snapshot; do not let
a `stopping` boolean make a concurrent caller return early.

An owned event/tool/pacer task may initiate stop. Cancellation releases its
self-join cycle without cancelling cleanup. Never repeatedly cancel a producer
while its `finally` is already awaiting native stop. Unconfirmed native stop
means no lease reuse and no claim of a stable final snapshot. Still drain
submitted writes and attempt independent safe cleanup. A failed close stays
failed, even after late native completion; automatic retry/recycling is absent.
The Cascade route worker also retains its close task and uses the bounded shared
join. Its processing task shields the response task so parent cancellation cannot
re-cancel a response already cleaning up. A route timeout reaches the handler's
pending-write drain and safe independent cleanup without releasing either lease.

Async hydration uses `MemoManager.from_redis_async`. ACS retains the existing
call-key lookup followed by canonical `memo.session_id` assignment; there is no
Redis key migration. Live mutation uses `src/orchestration/session_memory.py`
to find the current memo in the existing app/engine registries. Async builder
and scenario boundaries prime the existing definition views before mutation.
Synchronous registry compatibility APIs remain for non-async callers; synchronous
reads inside an event loop use the primed view rather than blocking on Redis.

Exercise `tests/test_voice_close_contract.py`, native stop-acknowledgement,
`tests/test_voice_endpoint_close.py`, browser teardown, Genesys codec/pacing and MemoManager tests. Include strict
write/flush failures, state-projection failure, concurrent/cancelled/self-close,
late audio, partial startup and unacknowledged native work.

Outer browser/media/Genesys cleanup also retains and shields its completion.
Safe session/socket stages still run after native failure; ACS/media no longer
logs the native failure and then reports an OK cleanup span. Local registry
removal checks the expected lifetime so an old close cannot remove a replacement
connection's context. This is an in-process cleanup guard, not distributed CAS.

VoiceLive scenario updates must use the orchestrator's owned task set. ACS
warmup consumption belongs inside retained startup, not before the handler
exists. Its consumer must supply an owned cleanup set; abandoned warmups are
disposed there and joined without cancellation before final persistence.
Completed disposal failures are retained until close observes them. Unconsumed
preconnection warmups still live in the existing application warmup registry;
this does not introduce a new application-wide shutdown coordinator.

## Removed paths and retained compatibility

| Removed path | Consumer/behavior replacement |
| --- | --- |
| 1,068-line `SessionAgentManager` | No production/sample consumers; production session-agent registry, builder and codec contracts cover overrides, roundtrip, activation, isolation and reset. Experiment metadata remains ordinary metadata; unused manager audit/experiment mutators are not a parallel API. |
| Aggregate `SpeechCascadeHandler` | No production/sample owner; `VoiceHandler` owns lifetime. `ThreadBridge`, SDK/turn workers, barge-in and provider primitives remain. |
| Cascade factory/continuation/state wrappers | Unified routing uses `CascadeOrchestratorAdapter.create()` and `process_turn()` with the current memo and explicit turn scope. |
| Cascade TTS forwarding methods | Both streaming and greeting paths use `TTSTextProcessor` directly; text behavior tests target that implementation. |
| VoiceLive `_pending_tool_outputs` | Response-ID batches serve event and direct/control callers. Tests use the real dispatcher/finalizer contract. |
| SDK methods on `UnifiedAgent` | Native callers and payload/greeting tests call `voice/voicelive/session.py`. |
| Loader's duplicate handoff-map implementation | Thin public alias to the definition module's existing helper. |

WebSocket TTS helpers remain public because `samples/labs/dev/gpt_flow.py`
consumes them. The low-level ThreadBridge/SDK/audio components are not obsolete
facades. Historical documentation under `docs/legacy/` is not a current API guide.

## Explicit limits

Ordering is per MemoManager instance/event loop, not distributed CAS, not even
a process-wide transaction. Independent offline writers or workers can still
overwrite whole-state snapshots. Redis acknowledgement does not guarantee
replication, disk persistence or atomic `HSET` plus `EXPIRE`. See
[the storage contract](memo-persistence.md).

Native threads cannot be safely killed. Quarantined resources are not
automatically recovered. VoiceLive session/audio callbacks and transcript-triggered
automatic transfer can still await on the event reader; model-issued controls
and their business barriers no longer do. An already submitted SDK operation
cannot be retracted, but superseded completion cannot create another response.
Transfer cleanup also rechecks ownership before cancelling or stopping playback;
its result notification remains independent of spoken continuation.
Definition caches are working views, not a second durable
catalog. No external framework, dependencies, Genesys/Cascade integration or
live-service validation is introduced by this consolidation.
