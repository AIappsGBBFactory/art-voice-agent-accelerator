# VoiceLive Orchestrator — Event & Response Lifecycle

Developer reference for the VoiceLive engine's event intake and tool/response
lifecycle. Scope: `apps/artagent/backend/voice/voicelive/`.

## Files

| File | Responsibility |
|------|----------------|
| `handler.py` | `VoiceLiveSDKHandler` — connection lifecycle, the single SDK event reader (`_event_loop`), start/stop, barge-in forwarding, background tasks. |
| `orchestrator.py` | `LiveOrchestrator` — event routing (`handle_event`), tool dispatch/execution, response continuation, agent handoff/transfer, session-context refresh. |
| `dtmf_processor.py` | DTMF digit collection. |
| `metrics.py` / `tool_helpers.py` / `settings.py` | Telemetry, tool emit helpers, engine settings. |

## The single-reader constraint

VoiceLive delivers **every** server event on one stream:

```python
async for event in self._connection:      # handler._event_loop
    self._forward_event_to_acs(event)      # audio out first
    await self._orchestrator.handle_event(event)
```

Because intake is serial, anything `handle_event` awaits inline delays intake of
the *next* event — including speech-start, audio, and interrupt. `handle_event`
must therefore return quickly.

## Business-tool offload (F12)

A function call is routed by `_dispatch_tool_call`:

- **Handoff / transfer tools run inline.** They are control operations whose
  ordering relative to the session/response mutations they trigger
  (`response.cancel`, `_switch_to`, `apply_voicelive_session`) must be
  preserved. **Known limitation:** a slow handoff/transfer tool still stalls
  intake for its duration. This is documented, not silently worked around;
  isolating it requires a coordinated response-ordering contract with the shared
  handoff owner and is out of this workstream's scope.
- **Business tools are offloaded** to an owned task. All business tools of one
  response share a single `_ToolBatch`; each task appends its
  `(call_id, output_json)` to `batch.outputs`. Intake continues immediately.

### One continuation per response

`_handle_response_done` never awaits tools on the reader. It:

1. marks the batch `response_done`,
2. bumps the response epoch if the service reported the response `CANCELLED`,
3. schedules exactly **one** owned finalizer (`_finalize_tool_batch`),
4. detaches the batch and returns.

The finalizer awaits the tool barrier **off-reader**, then emits a single
`response.create()` via `_flush_tool_outputs_and_continue` (context update first,
continuation second).

The legacy inline `_pending_tool_outputs` flush is retained for direct-call unit
tests; production always takes the batch path.

## Response epoch — rejecting stale continuations

`_response_epoch` counts response *generations*. A batch captures the epoch at
creation. The epoch is bumped whenever the in-flight response is invalidated:

| Site | Reason |
|------|--------|
| `_handle_speech_started` | barge-in — a new user utterance supersedes the pending turn |
| `_handle_session_updated` (cancel branch) | a genuine reconfigure cancelled the response |
| transfer branch (`response.cancel`) | call is being transferred |
| handoff branch (`response.cancel`) | the new agent owns the turn now |
| `_handle_response_done` (status `CANCELLED`) | the model turn was torn down |

If the live epoch has advanced by the time the finalizer runs, the **spoken
continuation is dropped** rather than restarting speech. The tools' **durable
effects** (memo writes, `notify_tool_end` acknowledgements) already ran inside
the tasks and are intentionally preserved — only the stale spoken turn is
discarded.

## Task ownership & teardown

Off-reader work (business-tool tasks, batch finalizers, the throttled
context-update task) is spawned through `_track_owned`, which records the task in
`self._owned_tasks`.

- `cleanup()` (sync) cancels owned tasks as a safety net and clears the active batch.
- `cancel_and_join_tasks()` (async) cancels **and joins** them. The handler calls
  it from `stop()` **before** closing the connection, so a task mid-way through
  `conn.response.create()` is torn down first and cannot race the socket close.

## Partial-start-safe stop (F5) & the persistence barrier

`start()` adopts/opens the connection, registers the orchestrator, and spawns the
event task **before** it sets `_running = True`. `stop()` therefore keys teardown
off **resource presence**, not `_running`, so a failure anywhere in the startup
window still unwinds the connection, the orchestrator registry entry, and any
unclaimed warm (`_prepared_connection`) socket. A `_stopping` re-entry guard makes
a second/concurrent `stop()` a no-op.

`stop()` follows the storage **close contract** — quiesce producers, then snapshot:

1. `unregister_voicelive_orchestrator` (stop scenario-update callbacks)
2. DTMF cleanup
3. cancel + join the event reader (`_event_task`)
4. `orchestrator.cancel_and_join_tasks()` (owned tool tasks / finalizers)
5. **final strict snapshot** — `_sync_to_memo_manager()` then
   `persist_to_redis_async()`, gated on `was_running`
6. close connection / prepared connection, `orchestrator.cleanup()`

The snapshot is captured **after** producers are quiesced: persisting earlier
races an in-flight tool finalizer still writing corememory
(`client_id` / `session_profile`), so the snapshot could miss the write.

### Storage integration hook (dependent, coordinator-owned)

The persist block in `stop()` is the single integration point for the
session-persistence slice:

- **Hydration** enters VoiceLive pre-built as `websocket.state.cm` (populated by
  the endpoint/media handler, out of this workstream's scope). The orchestrator
  consumes it once in `__init__` via `_sync_from_memo_manager()`.
- **Final flush**: `persist_to_redis_async()` is the ordered **strict barrier**;
  a `await memo_manager.flush_pending_persist(raise_on_failure=False)` slots into
  a `finally` immediately after it — before the connection / Redis / loop
  release. It is intentionally **not** wired yet (kept independent of the storage
  branch; no `getattr` shims).

## Tests

```bash
pytest tests/test_voicelive_tool_offload.py \
       tests/test_voicelive_partial_start_cleanup.py \
       tests/test_voicelive_barge_in.py \
       tests/test_voicelive_warmup.py \
       tests/test_voicelive_memory.py \
       tests/test_handoff_orchestrator_states.py \
       tests/test_tool_helpers_emit.py \
       tests/test_voicelive_session_update_dedup.py \
       tests/test_voicelive_session_updated_echo.py \
       tests/test_voicelive_greeting_race.py
```

- `test_voicelive_tool_offload.py` — off-reader batching, one continuation per
  multi-tool batch, stale/cancelled-continuation drop with preserved durable
  effect, teardown cancels in-flight tool tasks.
- `test_voicelive_partial_start_cleanup.py` — `stop()` unwinds every
  partial-acquisition state, is idempotent, and still tears down a running session.
