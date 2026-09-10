"""Resolve the live session's memory before considering a Redis snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.stateful.state_managment import MemoManager

if TYPE_CHECKING:
    from fastapi import WebSocket
    from src.pools.session_manager import ThreadSafeSessionManager
    from src.redis.manager import AzureRedisManager

_sessions: ThreadSafeSessionManager | None = None


def bind_session_manager(manager: ThreadSafeSessionManager | None) -> None:
    """Reference the existing application session registry, not a second cache."""
    global _sessions
    _sessions = manager


def live_memo(session_id: str) -> MemoManager | None:
    """Event-loop-only lookup, including the existing ACS call-key alias."""
    if _sessions is not None:
        context = _sessions.get_session_context_nowait(session_id)
        if context is not None:
            return context.memory_manager

    from apps.artagent.backend.src.orchestration.unified import _adapters
    from apps.artagent.backend.voice.voicelive.orchestrator import (
        get_voicelive_orchestrator,
    )

    cascade = _adapters.get(session_id)
    if cascade is not None and cascade.memo_manager is not None:
        return cascade.memo_manager
    live = get_voicelive_orchestrator(session_id)
    return live.memo_manager if live is not None else None


async def session_memo(session_id: str, redis_mgr: AzureRedisManager | None) -> MemoManager:
    """Hydrate only offline sessions; real hydration failures are not empty state."""
    memo = live_memo(session_id)
    if memo is not None:
        return memo
    if redis_mgr is None:
        return MemoManager(session_id=session_id)
    return await MemoManager.from_redis_async(session_id, redis_mgr)


async def prime_session_definitions(
    session_id: str | None, *, memo: MemoManager | None = None
) -> None:
    """Refresh the existing definition views at async API/session boundaries."""
    if session_id is None:
        return
    import time

    from apps.artagent.backend.src.orchestration import session_agents, session_scenarios

    redis = session_agents._redis_manager or session_scenarios._redis_manager
    if memo is None and redis is None:
        return
    if memo is None:
        memo = await session_memo(session_id, redis)
    session_agents._load_agents_from_redis(session_id, memo=memo)
    session_scenarios._load_scenarios_from_redis(session_id, memo=memo)
    session_agents._session_load_times[session_id] = time.monotonic()
    session_scenarios._session_load_times[session_id] = time.monotonic()


async def release_session_memory(
    session_id: str, memo: MemoManager | None, websocket: WebSocket
) -> None:
    """Remove only this completed lifetime, never a replacement connection."""
    from apps.artagent.backend.src.orchestration.unified import _adapters

    adapter = _adapters.get(session_id)
    if adapter is not None and adapter.memo_manager is memo:
        _adapters.pop(session_id, None)
    if _sessions is not None:
        context = _sessions.get_session_context_nowait(session_id)
        if (
            context is not None
            and context.memory_manager is memo
            and context.websocket is websocket
        ):
            await _sessions.remove_session(context.session_id, expected_context=context)
