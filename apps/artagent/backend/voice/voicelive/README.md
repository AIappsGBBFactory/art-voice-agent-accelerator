# VoiceLive event and response lifecycle

`VoiceLiveSDKHandler` owns connection/start/stop and the single SDK event reader.
`LiveOrchestrator` owns native event dispatch, response batches, handoffs and
context refresh. `session.py` owns SDK projections and session/greeting sends;
neutral `UnifiedAgent` definitions contain no SDK session operations.

## Reader and tool ordering

The reader forwards audio before awaiting `handle_event`. Business tools are
offloaded through `_track_owned`; handoff and transfer run inline. MFA/DTMF
semantics also remain engine-owned. An inline control waits for preceding
business tools in its response before changing agents or transferring.
**Limitation:** that control barrier and the control tool itself can stall the
single reader. The runtime does not claim every event path is nonblocking.

Both engines call `shared/tool_policy.py` for inputs, normalized results and
synchronous identity/profile/slot effects. The shared `HandoffService` resolves
scenario routes and context permissions. Cancelling spoken continuation does
not undo completed business effects.

## One production batch contract

`_tool_batches` is keyed by provider response ID. `response.done` detaches only
that response's batch and schedules an owned finalizer; it does not wait for
business tools on the reader. A cancelled old response invalidates its batch,
not a newer response or its transcript tracking.

Each finalizer waits for its tool barrier, sends outputs/context, then creates
at most one continuation. Epoch checks across each awaited send prevent a
barge-in, new response, reconfiguration, handoff or transfer from resurrecting
stale speech. Completed effects stay in the current memo. The `None` response-ID
key supports direct callers without provider IDs using this same mechanism;
there is no alternate `_pending_tool_outputs` runtime for tests.

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
