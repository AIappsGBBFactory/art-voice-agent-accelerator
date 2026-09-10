"""Bounded, read-only prompt previews for Quick Tune."""

from __future__ import annotations

from typing import Annotated, Any

from apps.artagent.backend.api.v1.schemas.prompt_preview import (
    MAX_PREVIEW_REQUEST_BYTES,
    PromptPreviewRequest,
    PromptPreviewResponse,
)
from azure.core.exceptions import AzureError
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from redis.exceptions import RedisError
from utils.ml_logging import get_logger

logger = get_logger("v1.prompt_preview")


class _PreviewRoute(APIRoute):
    """Limit streamed bodies and avoid FastAPI echoing invalid credential-bearing input."""

    def get_route_handler(self) -> Any:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Any:
            payload = bytearray()
            async for chunk in request.stream():
                if len(payload) + len(chunk) > MAX_PREVIEW_REQUEST_BYTES:
                    raise HTTPException(
                        status_code=413, detail="Prompt preview request is too large."
                    )
                payload.extend(chunk)
            request._body = bytes(payload)
            try:
                return await handler(request)
            except (RequestValidationError, RecursionError) as exc:
                raise HTTPException(
                    status_code=422, detail="Invalid prompt preview request."
                ) from exc

        return bounded


router = APIRouter(route_class=_PreviewRoute)


@router.post("/prompt-preview", response_model=PromptPreviewResponse, tags=["Agents"])
async def prompt_preview(
    body: PromptPreviewRequest,
    request: Request,
    session_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> PromptPreviewResponse:
    """Render draft Jinja against a sanitized session snapshot without changing anything."""
    from apps.artagent.backend.src.services.prompt_preview import preview_prompt

    try:
        return await preview_prompt(body, session_id=session_id, app_state=request.app.state)
    except (RuntimeError, RedisError, AzureError, OSError, ValueError, TypeError, KeyError) as exc:
        # Storage/authentication failures and malformed snapshots must not echo values.
        logger.error("Prompt preview could not read the requested session snapshot.")
        raise HTTPException(
            status_code=503, detail="Prompt preview context is unavailable. Refresh and retry."
        ) from exc
