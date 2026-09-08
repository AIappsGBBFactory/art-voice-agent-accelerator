"""Close primitives shared by native handlers, not a second session owner."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from src.stateful.state_managment import MemoManager


async def cancel_and_join(tasks: Iterable[asyncio.Task], *, timeout: float = 10.0) -> None:
    """Stop owned tasks without losing references to unacknowledged work.

    Called by the retained cleanup task, not a producer. Cancelling a producer
    waiting in shield(stop) breaks a self-join cycle without cancelling cleanup.
    """
    owned = {task for task in tasks if task is not asyncio.current_task() and not task.done()}
    for task in owned:
        if not task.cancelling():
            task.cancel()
    if not owned:
        return
    done, pending = await asyncio.wait(owned, timeout=timeout)
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
