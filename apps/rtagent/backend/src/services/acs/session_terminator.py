from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional, Dict, Any

from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from azure.communication.callautomation import CallAutomationClient

from utils.ml_logging import get_logger

logger = get_logger("services.acs.session_terminator")


class TerminationReason(Enum):
    """Reasons for intentionally ending a session."""
    HUMAN_HANDOFF = auto()
    NORMAL = auto()
    ERROR = auto()
    IDLE_TIMEOUT = auto()


@dataclass(frozen=True)
class TerminationResult:
    """
    Outcome of a terminate_session attempt.

    :param acs_hangup_attempted: Whether we attempted to hang up ACS.
    :param acs_hangup_succeeded: Whether ACS hangup completed without error.
    :param websocket_closed: Whether the WebSocket was closed successfully.
    """
    acs_hangup_attempted: bool
    acs_hangup_succeeded: bool
    websocket_closed: bool


async def _hangup_acs_call(
    *,
    acs_client: CallAutomationClient,
    call_connection_id: str,
    attempts: int = 3,
    base_backoff_s: float = 0.25,
    timeout_s: float = 3.0,
) -> bool:
    """
    Best-effort hang-up with retries + timeout.

    :param acs_client: An initialized CallAutomationClient.
    :param call_connection_id: The ACS call connection id.
    :param attempts: Max retry attempts.
    :param base_backoff_s: Initial backoff in seconds (exponential).
    :param timeout_s: Per-attempt timeout seconds.
    :return: True if hangup succeeded, False otherwise.
    """
    for i in range(1, attempts + 1):
        try:
            await asyncio.wait_for(
                acs_client.get_call_connection(call_connection_id).hang_up(
                    is_for_everyone=True
                ),
                timeout=timeout_s,
            )
            logger.info(
                "ACS hangup succeeded",
                extra={"call_connection_id": call_connection_id, "attempt": i},
            )
            return True
        except Exception as exc:
            logger.warning(
                "ACS hangup failed",
                extra={
                    "call_connection_id": call_connection_id,
                    "attempt": i,
                    "error": repr(exc),
                },
            )
            if i < attempts:
                await asyncio.sleep(base_backoff_s * (2 ** (i - 1)))
    return False


def _get_disconnect_event(ws: WebSocket, call_connection_id: Optional[str]) -> Optional[asyncio.Event]:
    """
    Retrieve (or create) an asyncio.Event that will be set when ACS disconnects.
    Your ACS webhook should set this event on 'CallDisconnected'.
    """
    if not call_connection_id:
        return None
    try:
        store: Dict[str, asyncio.Event] = getattr(ws.app.state, "acs_disconnect_events", None)  # type: ignore[attr-defined]
        if store is None:
            store = {}
            ws.app.state.acs_disconnect_events = store  # type: ignore[attr-defined]
        return store.setdefault(call_connection_id, asyncio.Event())
    except Exception as exc:
        logger.debug("Failed to access acs_disconnect_events store", extra={"error": repr(exc)})
        return None


async def _wait_for_acs_disconnect(
    *,
    ws: WebSocket,
    acs_client: Optional[CallAutomationClient],
    call_connection_id: Optional[str],
    max_wait_s: float = 10.0,
    poll_interval_s: float = 0.5,
) -> bool:
    """
    Wait (best-effort) for ACS call to be fully disconnected before closing WS.

    Strategy:
    1) If an event exists (set by your ACS webhook on CallDisconnected), await it.
    2) Else, if we have an ACS client, poll a lightweight call API and treat 404/NotFound
       or clear disconnection signals as 'disconnected'.
    3) Time out after max_wait_s and proceed (return False).

    :return: True if we detected disconnection, False on timeout/unknown.
    """
    if not call_connection_id:
        return True  # Nothing to wait on.

    # 1) Event-driven (preferred)
    ev = _get_disconnect_event(ws, call_connection_id)
    if ev is not None:
        try:
            await asyncio.wait_for(ev.wait(), timeout=max_wait_s)
            logger.info("ACS disconnect event observed", extra={"call_connection_id": call_connection_id})
            return True
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for ACS disconnect event", extra={"call_connection_id": call_connection_id})

    # 2) Fallback: polling (best-effort; API names vary by SDK version)
    if acs_client:
        deadline = asyncio.get_event_loop().time() + max_wait_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                # Try a cheap call that fails once the call is gone.
                conn = acs_client.get_call_connection(call_connection_id)
                # Many versions support get_participants(); if the call is gone you'll get a 404/NotFound.
                await conn.get_participants()  # type: ignore[attr-defined]
                # If it didn't throw, call may still be up. Wait and retry.
                await asyncio.sleep(poll_interval_s)
                continue
            except Exception as exc:
                # Heuristic: treat not found/404 as "disconnected"
                msg = str(exc).lower()
                if "not found" in msg or "404" in msg or "gone" in msg or "disconnected" in msg:
                    logger.info("ACS disconnect inferred by polling", extra={"call_connection_id": call_connection_id})
                    return True
                # Other transient errors: keep waiting a bit
                await asyncio.sleep(poll_interval_s)
        logger.warning("Timeout waiting for ACS disconnect (polling)", extra={"call_connection_id": call_connection_id})

    return False


async def _send_session_end(ws: WebSocket, reason: TerminationReason) -> None:
    """Send a final session_end envelope if the socket is still connected."""
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_json(
                {
                    "type": "session_end",
                    "reason": reason.name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
    except Exception as exc:
        logger.debug("Failed to send session_end", extra={"error": repr(exc)})


async def terminate_session(
    ws: WebSocket,
    *,
    is_acs: bool,
    call_connection_id: Optional[str],
    reason: TerminationReason = TerminationReason.NORMAL,
    acs_client: Optional[CallAutomationClient] = None,
    wait_for_disconnect_s: float = 10.0,
) -> TerminationResult:
    """
    Best-effort shutdown of ACS call and WebSocket.

    **Important**: The WebSocket will not be closed until the ACS call is disconnected
    (either via event or polling), or until `wait_for_disconnect_s` elapses.

    :param ws: FastAPI WebSocket connection object.
    :param is_acs: True if the session is associated with ACS.
    :param call_connection_id: The ACS call connection id, if available.
    :param reason: The reason for termination.
    :param acs_client: Optional explicit CallAutomationClient. If not provided,
                       the function attempts to read `ws.app.state.acs_caller.client`.
    :param wait_for_disconnect_s: Max seconds to wait for ACS to disconnect before closing WS.
    :return: TerminationResult indicating what succeeded.
    """
    logger.info(
        "Session termination requested",
        extra={
            "reason": reason.name,
            "is_acs": is_acs,
            "call_connection_id_present": bool(call_connection_id),
        },
    )

    # Resolve ACS client from app state if not passed
    resolved_acs_client: Optional[CallAutomationClient] = acs_client
    if is_acs and call_connection_id and resolved_acs_client is None:
        try:
            resolved_acs_client = ws.app.state.acs_caller.client  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning(
                "ACS client not available from app state",
                extra={"error": repr(exc)},
            )

    acs_attempted = False
    acs_succeeded = False

    # 1) Try to hang up ACS (best-effort)
    if is_acs and call_connection_id and resolved_acs_client:
        acs_attempted = True
        try:
            await asyncio.sleep(10) 
            acs_succeeded = await _hangup_acs_call(
                acs_client=resolved_acs_client,
                call_connection_id=call_connection_id,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected failure during ACS hangup",
                extra={"error": repr(exc)},
            )

    # 2) Wait for ACS to actually disconnect (event > polling > timeout)
    disconnected = True
    if is_acs and call_connection_id:
        disconnected = await _wait_for_acs_disconnect(
            ws=ws,
            acs_client=resolved_acs_client,
            call_connection_id=call_connection_id,
            max_wait_s=wait_for_disconnect_s,
        )
        logger.info(
            "ACS disconnect wait complete",
            extra={"call_connection_id": call_connection_id, "disconnected": disconnected},
        )

    # 3) Notify client we're ending (after ACS is done, to avoid premature UI closure)
    await _send_session_end(ws, reason)

    # 4) Close the WebSocket (idempotent)
    ws_closed = False
    try:
        if ws.application_state in (WebSocketState.CONNECTED, WebSocketState.CONNECTING):
            await ws.close(code=1000)
            ws_closed = True
            logger.info("WebSocket closed cleanly")
        else:
            ws_closed = True
            logger.debug("WebSocket already closed")
    except Exception as exc:
        logger.warning("WebSocket close failed", extra={"error": repr(exc)})

    return TerminationResult(
        acs_hangup_attempted=acs_attempted,
        acs_hangup_succeeded=acs_succeeded,
        websocket_closed=ws_closed,
    )