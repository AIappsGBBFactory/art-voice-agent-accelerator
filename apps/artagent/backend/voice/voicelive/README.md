# VoiceLive event and response lifecycle

`VoiceLiveSDKHandler` owns connection/start/stop and the single SDK event reader.
`LiveOrchestrator` owns native event dispatch, response batches, handoffs and
context refresh. `session.py` owns SDK projections and session/greeting sends;
neutral `UnifiedAgent` definitions contain no SDK session operations.

## Reader and tool ordering

The reader forwards audio before awaiting `handle_event`. Business tools are
offloaded through `_track_owned`. Model-issued handoff/transfer intents are
collected until `response.done` closes batch membership, regardless of which
tool's arguments arrive first. The owned finalizer waits for all business work,
publishes its outputs, then runs controls off-reader. It stops at the first
terminal transition; failed controls can report an output and continue the old
agent. Tools are never retried because speech was superseded. MFA/DTMF semantics
remain engine-owned.

Session/audio callbacks and transcript-triggered automatic transfer are still
reader operations, outside model response batching. The runtime does not claim
every event path is nonblocking.

Both engines call `shared/tool_policy.py` for inputs, normalized results and
synchronous identity/profile/slot effects. The shared `HandoffService` resolves
scenario routes and context permissions. Cancelling spoken continuation does
not undo completed business effects.

## One production batch contract

`_tool_batches` is keyed by provider response ID. `response.done` detaches only
that response's batch and schedules an owned finalizer; it does not wait for
business tools on the reader. A cancelled old response invalidates its batch,
not a newer response or its transcript tracking.

Each finalizer produces at most one business continuation or control transition.
Epoch checks across each awaited send and control transition prevent a
barge-in, new response, reconfiguration, handoff or transfer from resurrecting
stale speech. Completed effects stay in the current memo. The `None` response-ID
key supports direct callers without provider IDs using this same mechanism;
there is no alternate `_pending_tool_outputs` runtime for tests.

Logical scenario and agent replacements invalidate ownership before provider
awaits, including when an old batch is already detached and no response ID is
active. Ordinary VAD/context acknowledgements retain their existing behavior.
A provider operation already submitted cannot be retracted; a stale completion
cannot schedule further handoff speech or cancel/stop a replacement response.
Transfer completion notifications still report committed tool outcomes.

### Handoff transition ownership

`_HandoffTransition` is one native epoch's state, not a registry or a second
orchestrator. `_run_handoff_transition` claims it before cancellation/playback,
then applies the target, replays a captured history snapshot, and requests the
handoff response. Startup greeting/fallback delivery is never armed for that
transition. An acknowledgement during apply, replay, or response creation cannot
start a competing greeting or tear down its response.

The transition moves from `applying` to `responding` to `complete`; acknowledgement
is recorded independently because it can arrive at any phase. Its first
`response.created` invalidates older batches while retaining this response's
acknowledgement protection. Logical replacement and close invalidate ownership.
Failure releases only the matching transition, never a replacement's protection.
History values are captured before the transition's first await, and replay checks
its epoch before every new item submission, including the assistant item.

Tool execution and routing are separate outcomes. One completion `finally`
encloses start notification, invocation and routing for every tool; branch-local
terminal notifications are not separate owners. A settled result/status is retained
even if routing is superseded or fails. If invocation is cancelled before a result
settles, the terminal attempt reports `cancelled` with `outcome: unknown` and an
explicit warning that effects may have occurred and automatic retry is unsafe.
The existing error payload prevents the wire helper from defaulting this unknown
outcome to success. This does not claim rollback or erase simulated/remote effects.
Cancellation is re-raised; notification failure cannot replace it or a settled
execution error. Handoffs retain
notification-only `handoff_transition.status` (`switched`, `superseded`,
`rejected`, `failed`, or `response_failed`) and `target_agent` metadata. This does
not change the registered tool's result or retry its side effects. Notification
delivery still follows the existing messenger/socket contract, not a durable
exactly-once delivery guarantee. Context-update credits and normal startup
acknowledgement/fallback behavior remain separate and unchanged.

Quick Tune resolves the current native identity before any default session agent.
`session_agents.session_agent_for_edit` installs the matching owned definition
before either API or native tuning mutates it. Nested voice, session, speech,
model and BYOM data are copied together; the application catalog and other
sessions remain read-only. The live registry and persisted session view use the
same owned instance.

## Session updates and notifications

Context-only `session.updated` acknowledgements do not restart audio or add chat
messages. Instruction fingerprints and a session-update lock suppress unchanged
uploads, including concurrent refreshes. Full agent and scenario updates invalidate
the fingerprint and retain the native transition-ownership checks.

The messenger announces the initial agent once; later `agent_change` events own
transition notices. Changed requested-vs-applied contracts still reach the UI in
`session_updated` envelopes with `announce_agent: false`, refreshing the configuration
panel without another chat row. Identical contracts for the current agent are skipped.

## Start, close and memory

`start()` retains its startup task; cancellation/error unwinds partial resources.
`stop()` retains and shields cleanup for all callers, even before `_running`
becomes true. It unregisters live callbacks, joins startup, DTMF, reader,
background, tool, finalizer and greeting work, then projects final native state.

The common [close contract](../README.md#caller-facing-close-contract) requires a
strict final snapshot and a strict pending flush. Projection failure still
drains submitted persistence. Native failure skips the stable-snapshot claim
but does not skip safe connection/prepared-socket cleanup. References to
unacknowledged producers remain retained; repeated stop reports the same failure.

Browser and ACS/media startup await MemoManager hydration and prime definitions.
The existing application/orchestrator registries expose the same current memo
to live builder, scenario, event and profile mutations. No second memo catalog
or distributed persistence lock is introduced.

## Focused tests

```sh
pytest tests/test_voicelive* tests/test_voice_tool_policy_contract.py \
  tests/test_voice_close_contract.py tests/test_handoff_orchestrator_states.py
```

Coverage includes native batching and controls, interruptions across awaits,
response/session-update deduplication, tuned agents, staged greetings,
concurrent/self-initiated/partial close and strict persistence failure.

Live scenario reconfiguration is also an owned task; it no longer bypasses
close with an untracked thread-safe scheduling future. Without a running loop,
sync definition edits log that a provider update cannot be scheduled and do not
allocate an unawaited coroutine.

ACS warmup consumption occurs inside retained startup. Timed-out or cancelled
consumption transfers disposal into the handler's retained cleanup set while
cold-start fallback stays fast. Close joins disposal without cancelling it; a
deadline failure quarantines it. Prepared connections have retained/shielded
close and cannot be claimed after closing begins. Recorded warmup/disposal
failures remain visible at stop even if cold-start fallback established a call.
Warmup configuration primes the same async definition contract as cold startup.
