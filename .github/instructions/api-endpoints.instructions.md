---
applyTo: "**/api/**/*.py,**/endpoints/**/*.py,**/handlers/**/*.py"
---

# API Endpoint Standards

## Router Setup
```python
from fastapi import APIRouter, Request, HTTPException, Depends
from utils.ml_logging import get_logger

router = APIRouter()
logger = get_logger(__name__)
```

## Endpoint Pattern
```python
@router.get("/path", response_model=ResponseSchema, tags=["Category"])
async def endpoint_name(request: Request) -> ResponseSchema:
    """Brief description of what this endpoint does."""
    # Access shared resources via request.app.state
    # Return Pydantic model, not dict
```

## Request/Response
- Use Pydantic schemas from `api/v1/schemas/` for all request/response models
- Extend `BaseModel` from `api/v1/models/base.py` for new models
- Never return raw dicts — always use response_model

## Dependency Injection
- Use `Depends()` for auth, sessions, clients
- Access app state: `request.app.state.redis_client`
- WebSocket: use `container_from_ws(ws)`, not direct state access

## Error Responses
```python
# Standard error format
raise HTTPException(status_code=404, detail="Resource not found")

# With logging
logger.error(f"Failed to fetch resource {id}: {e}")
raise HTTPException(status_code=500, detail=str(e))
```

## WebSocket Error Responses

Never let a voice WebSocket die with a bare `raise` — the client sees an opaque
1006 close and the user just hears silence. Classify the failure and surface it.

```python
from apps.artagent.backend.voice.shared.errors import (
    classify_voice_error,
    emit_voice_error,
    fail_websocket_session,
)

# Non-fatal: tell the client, keep the session alive.
info = classify_voice_error(exc, source="llm", model=model_name)
await emit_voice_error(ws, info, session_id=session_id)

# Fatal: tell the client, then close with a descriptive reason (close code 4500).
await fail_websocket_session(ws, exc, session_id=session_id, source="voicelive")
```

`source` is one of `llm`, `tts`, `stt`, `voicelive`, `config`, `connection`.

This emits an `error` envelope whose payload the frontend renders as an error
card:

```json
{
  "type": "error",
  "payload": {
    "code": "DeploymentNotFound",
    "message": "The model deployment 'gpt-4o-mini' was not found.",
    "remediation": "Check that the agent's model/deployment name matches...",
    "details": "Error code: 404 - {...}",
    "source": "llm",
    "fatal": true
  }
}
```

## Tags for OpenAPI
- `Health` — health/readiness endpoints
- `Calls` — call management
- `Agents` — agent operations
- `Voice` — voice/speech operations
