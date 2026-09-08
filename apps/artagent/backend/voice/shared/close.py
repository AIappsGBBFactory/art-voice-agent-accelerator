"""Close primitives shared by native handlers, not a second session owner."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from src.stateful.state_managment import MemoManager


async def cancel_and_join(
    tasks: Iterable[asyncio.Task], *, timeout: float = 10.0, cancel: bool = True
) -> None:
    """Stop owned tasks without losing references to unacknowledged work.

    Called by the retained cleanup task, not a producer. Cancelling a producer
    waiting in shield(stop) breaks a self-join cycle without cancelling cleanup.
    Pass cancel=False for cleanup work that must finish instead of being cancelled.
    That also observes retained completed cleanup failures; completed producer
    failures belong to their execution caller, not a new shutdown attempt.
    """
    owned = {
        task
        for task in tasks
        if task is not asyncio.current_task() and (not cancel or not task.done())
    }
    done = {task for task in owned if task.done()}
    pending = owned - done
    for task in pending:
        if cancel and not task.cancelling():
            task.cancel()
    if pending:
        stopped, pending = await asyncio.wait(pending, timeout=timeout)
        done.update(stopped)
    errors = [task.exception() for task in done if not task.cancelled() and task.exception()]
    if pending:
        errors.append(TimeoutError(f"{len(pending)} session task(s) did not acknowledge stop"))
    if errors:
        raise ExceptionGroup("Session producer shutdown failed", errors)


async def finish_persistence(
    memo: MemoManager | None, redis: Any, *, quiesced: bool = True
) -> None:
    """Strict final snapshot then drain; never claim stability with live producers."""
    if memo is None:
        return
    try:
        if quiesced and redis is not None:
            await memo.persist_to_redis_async(redis, raise_on_failure=True)
    finally:
        await memo.flush_pending_persist(raise_on_failure=True)
