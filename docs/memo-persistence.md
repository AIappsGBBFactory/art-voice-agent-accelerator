# MemoManager persistence lifetime

`src/stateful/state_managment.py` owns a session's in-process persistence queue.
It does not introduce a shared singleton, another storage system, or a distributed
lock. This contract applies equally to Cascade, VoiceLive, and their existing
channels. Handler integration is described below.

## Restore without blocking startup

```python
memo = await MemoManager.from_redis_async(session_id, redis_mgr)
```

The exact new factory signature is:

```python
@classmethod
async def from_redis_async(
    cls, session_id: str, redis_mgr: AzureRedisManager
) -> MemoManager:
    ...
```

It uses the existing executor-backed Redis async read, retains the manager for
later calls, and decodes memory/history exactly like `from_redis_with_manager`.
An absent hash or missing field keeps the same initialization defaults; legacy
list-shaped history is still decoded by `ChatHistory.from_json`. Redis read
failure, malformed JSON, and caller cancellation propagate. The additive Redis
keyword `get_session_data_async(key, *, raise_on_failure=False)` lets restoration
request strict errors without changing other read callers' default behavior.
The synchronous `from_redis` and `from_redis_with_manager` factories remain
available and keep their existing manager-retention behavior.

## One writer, immutable snapshots, explicit barriers

| Operation | Contract |
| --- | --- |
| `await memo.persist_background(redis_mgr=None, ttl_seconds=None)` | Captures both JSON fields immediately, without an intervening await, then schedules persistence. Adjacent pending background requests coalesce only when Redis manager identity and TTL match. Missing manager or unserializable state raises at submission. |
| `memo.schedule_persist(redis_mgr=None, ttl_seconds=None)` | Same background submission from a synchronous callback running on the owning event loop. Captures and queues before returning, so an immediate flush includes it. Requires a running loop; rejects a foreign loop while the writer is active. |
| `await memo.persist_to_redis_async(redis_mgr, ttl_seconds=None, *, raise_on_failure=False)` | Captures a direct snapshot and waits for its ordered write and requested expiry. Never coalesces a direct snapshot or coalesces background requests across it. Returns `True`/`False`; strict mode raises the error. |
| `await memo.flush_pending_persist(*, raise_on_failure=False)` | Waits for the requests submitted before entry and reports their failures. Does not capture currently unsaved state or stop new submissions. Returns `True`/`False`; strict mode raises the first observed failure after the entire boundary finishes. |
| `memo.cancel_pending_persist()` | Withdraws only not-started background snapshots. Returns whether any were withdrawn. Does not cancel an active write or a direct request. Withdrawal is reported as failure by flush, not as durability. |
| `memo.persist_to_redis(redis_mgr, ttl_seconds=None)` | Compatible synchronous path when there is no outstanding async writer. Rejects overlap rather than blocking the event loop on its own writer or allowing reordering. |

Each instance submits at most one Redis write/expiry sequence at a time. A newer
background snapshot can replace a pending background snapshot, but cannot cancel
an already-started write. Direct requests remain FIFO durability barriers. Several
unawaited direct requests can queue; callers should await durability-critical
operations instead of building an unbounded direct queue.

Snapshots are serialized on the owning event loop before yielding and contain
both complete local core memory and history. Later nested-dictionary or history
changes cannot mutate an already-submitted snapshot. State must not be mutated
from other threads. Updating configuration on a hydrated, current MemoManager
preserves unrelated tool outputs and conversation history; replacing its entire
context with a configuration-only dictionary still loses those local fields.

## Cancellation, errors, and end-of-call state

Direct and flush callers await shielded completion futures. Cancelling either
caller raises `asyncio.CancelledError` promptly, while the internal writer and
executor-backed Redis operation remain owned by the MemoManager. Cancellation
does **not** retract a Redis command. A later flush can await the original write.
Do not cancel the private writer task or shut down the loop before flushing.
Forced internal writer termination is reported as unconfirmed durability and
permanently rejects additional writes on that instance: silently restarting
could let a new writer overtake an executor operation that is still running.

Write errors are logged when they occur, retained through later successful
writes, and acknowledged by a completed flush covering their submission boundary.
This includes errors already returned to a direct caller and explicit pending
withdrawals. Flush waits for every captured request before returning a failure.
Concurrent flushes waiting on a failed request each observe that failure;
completed failure records are cleared when a covering flush acknowledges them.
A cancelled flush does not acknowledge errors. A subsequent empty flush can
succeed after errors were acknowledged; that is not a retry of failed writes.
Forced-writer failure remains terminal and is never acknowledged as recovery.

`persist()` keeps its compatible `None` return and best-effort behavior; use the
checked direct method when completed tool effects or end-of-call state must be
durable. `set_live_context_value` now returns `False`, not `True`, after a failed
write. Redis's existing async write wrapper still logs and returns `False` for
backend exceptions, which MemoManager strict mode exposes as `RuntimeError`.
Exceptions raised directly by an async backend are propagated in strict mode.

After stopping all state producers, capture the final state and drain:

```python
try:
    await memo.persist_to_redis_async(redis_mgr, raise_on_failure=True)
finally:
    await memo.flush_pending_persist(raise_on_failure=True)
```

Run this before releasing Redis or closing the loop, in a lifecycle scope that
is allowed to finish. Repeated cancellation of that cleanup scope still stops
its waiter; retain the MemoManager and flush from the supervising cleanup scope.
The `finally` also drains and surfaces earlier background failures if the final
direct write fails or its waiter is cancelled. Application error handling must
decide whether and when to retry; flush never retries or invents a final snapshot.
External deadlines can cancel a waiter without cancelling writes, but cannot
promise durability by that deadline.

## Storage compatibility and limits

Storage remains the `session:{session_id}` Redis hash with JSON strings in
`corememory` and `chat_history`. Writes containing core memory merge owned fields
against the current hash and use an atomic compare-and-store operation. Other
hash fields are preserved. Non-memory hash writes retain the existing `HSET`
behavior, including successful updates that return zero new fields. No session
key migration or new storage dependency is introduced.

Truthy `ttl_seconds` still applies `EXPIRE` after the write; `None` and zero skip
expiry. Skipping expiry does not remove a pre-existing Redis TTL. Expiry is part
of the same ordered operation and must succeed before it reports success.
The snapshot write and `EXPIRE` are separate commands, not an atomic transaction: expiry
failure can leave updated data with the previous TTL. Normal Redis socket/retry
limits apply; a successful barrier means Redis acknowledged the operation, not
a stronger disk-replication or failover guarantee.

Ordering is **per MemoManager instance on its owning event loop**, not a
process-wide ordering guarantee. Active call mutations still use the same
current instance: arbitrary conversation/history changes from independent
writers are not semantically merged. Authoring writes have the narrower
cross-worker ownership contract below. Configuration-only writers must not
manufacture an empty MemoManager and persist it over live state.

## Authoring ownership and atomic drafts

The ordered writer captures `authoring_fields`, `registry_updates`, and
submission-time runtime changes alongside each immutable snapshot. Registry
edits update only explicitly named agent/scenario entries; they do not replace
conversation history from an author's older snapshot. Ordinary conversation
writes preserve committed authoring-owned fields and cannot replay a stale
scenario selection or resurrect deleted definitions.

An internal `__authoring_revision` identifies published authoring state. Scenario
activation clears superseded pending handoff/context state, while deliberate
runtime handoffs remain possible through tracked runtime changes. This does not
make unrelated conversation writers safe to run concurrently.

`src/orchestration/session_drafts.py` reads a strict, session-scoped snapshot and
atomically publishes the complete draft's agents, scenario, and activation before
notifying runtime caches. Redis CAS receipts distinguish lost acknowledgements
from uncommitted operations; receipt retention is 120 seconds against a 30-second
retry budget. Retrying a previously committed operation does not reactivate it
over a newer authoring operation. Registry read-through, canonical casing, and
explicit deletion remain supported.

Use the existing async registry/publication helpers for authoring. Normal turn
and close persistence must not claim authoring ownership or bypass the current
MemoManager's ordered write/flush lifecycle.

## Consumer integration

Cascade `VoiceHandler`, browser/media VoiceLive hydration and Genesys startup
now await hydration. ACS retains its existing call-key lookup and canonical
`memo.session_id` assignment; this is not a key migration. Builder, scenario,
event and demo-profile async writers resolve the same live memo through the
existing application/engine registries. Offline sessions hydrate asynchronously;
real read failures are not converted into empty local sessions.

All three native handlers share retained/shielded close ownership and
`voice/shared/close.py`: stop startup/producers, strictly snapshot, and strictly
flush in `finally`. Cancelled/concurrent callers cannot abandon cleanup or return
early as though it finished. Unacknowledged native work prevents a stable-snapshot
claim and lease reuse; submitted persistence is still drained and independent
safe cleanup is attempted. Native state-projection failure also drains submitted
writes. Persistence failure after quiescence does not leak safe speech leases.
The Cascade route worker uses the same bounded producer join inside a retained
close task. A response held in cancellation cleanup cannot block entry to the
handler's pending-write drain. It remains referenced and is not cancelled again
by its processing parent; a failed route close cannot be restarted or used to
justify a final snapshot or lease reuse.

Async definition mutation/removal entry points prime existing definition views
before editing. Sync compatibility APIs remain, but in-event-loop sync reads use
the primed view rather than synchronous Redis hydration. These views and the
existing application registry are not distributed locks; cross-worker
authoring consistency comes from the scoped ownership/CAS contract above.
See [the extension guide](voice-extension-guide.md) for ownership and limits.

The existing registry and unified-orchestrator background callers pass Redis
explicitly. `CallEventHandlers.handle_dtmf_tone_received` and its private
`_update_dtmf_sequence` / `_validate_sequence` helpers now await checked ordered
persistence. Digit ordering, clear, PIN validation, and local-only behavior are
unchanged. Persistence errors propagate, and cancelling a handler's waiter does
not discard its queued tone snapshot. The separately registered
`DTMFValidationLifecycle` handler is unchanged by this migration.

`PersistentLatency.stop` in `src/tools/latency_helpers.py` remains synchronous and
returns its `StageSample`. On the owning event loop it uses `schedule_persist`:
submission completes before return, without `create_task` delaying capture past
an immediate flush. Off-loop standalone callers retain synchronous persistence
when no async writer is outstanding. Submission/off-loop write errors propagate;
on-loop write errors surface in the final flush. The method must not be called
from a foreign thread while the MemoManager is in active use on another loop.

## Focused regression suite

```bash
python -m pytest tests/test_memo_optimization.py tests/test_memo_persistence.py \
    tests/test_redis_manager.py tests/test_session_agent_redis_roundtrip.py \
    tests/test_session_agent_contract.py tests/test_voice_close_contract.py \
    tests/test_authoring_persistence_ownership.py tests/test_scenario_draft_authoring.py \
    tests/test_voice_endpoint_close.py \
    tests/test_acs_events_handlers.py \
    tests/test_dtmf_validation.py tests/test_dtmf_validation_failure_cancellation.py \
    -q -o addopts=-ra
```

The controlled Redis client exercises production MemoManager methods, production
Redis hash operations, and actual executor threads. It releases newer writes
before older ones to expose forbidden overlap, and covers coalescing, direct
barriers, waiter/flush cancellation, failure reporting, final-state flush, TTL,
full-state preservation, restoration parity, and the separate-instance limit.
Real DTMF and latency callback paths also run behind an outstanding executor
write, including immediate flush, cancellation/failure handling, and off-loop
synchronous latency compatibility.
The ownership suite also starts an isolated local Redis instance for CAS and
lost-acknowledgement races. No Azure service is used by these unit tests.
