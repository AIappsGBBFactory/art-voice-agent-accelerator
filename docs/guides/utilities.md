# Utilities and Infrastructure Services

Supporting utilities and infrastructure services provide the foundation for the Real-Time Voice Agent's scalability, resilience, and configurability.

## Resource Pool Management

### Speech Resource Pools

The platform uses `WarmableResourcePool` for managing TTS and STT clients:

```python
from src.pools import WarmableResourcePool, AllocationTier

# Create TTS pool with pre-warming
tts_pool = WarmableResourcePool(
    factory=create_tts_client,
    name="tts_pool",
    warm_pool_size=3,              # Pre-warm 3 clients
    enable_background_warmup=True, # Keep pool filled
    session_awareness=True,        # Per-session caching
)

await tts_pool.prepare()  # Initialize and pre-warm
```

### Allocation Tiers

| Tier | Source | Latency | Use Case |
|------|--------|---------|----------|
| `DEDICATED` | Session cache | 0ms | Same session requesting again |
| `WARM` | Pre-warmed queue | <50ms | First request with warmed pool |
| `COLD` | Factory creation | ~200ms | Pool empty, on-demand creation |

### Usage Pattern

```python
# Session-aware acquisition (recommended)
synth, tier = await pool.acquire_for_session(session_id)
# ... use synth ...
await pool.release_for_session(session_id)

# Anonymous acquisition
synth = await pool.acquire(timeout=2.0)
await pool.release(synth)
```

> **See Also**: [Resource Pools Documentation](../architecture/speech/resource-pools.md)

---

## Agent Framework Tools

### Tool Registry

Tools are registered centrally and referenced by agents:

```python
from apps.artagent.backend.agents.tools.registry import register_tool

# Define and register a tool
register_tool(
    "search_knowledge_base",
    schema,           # OpenAI function calling schema
    executor,         # Async function
    tags={"rag"},     # Optional tags for filtering
)
```

### Available Tool Categories

| Module | Purpose | Example Tools |
|--------|---------|---------------|
| `banking.py` | Account operations | `get_account_summary`, `refund_fee` |
| `auth.py` | Identity verification | `verify_client_identity`, `send_mfa_code` |
| `handoffs.py` | Agent transfers | `handoff_concierge`, `handoff_fraud_agent` |
| `knowledge_base.py` | RAG search | `search_knowledge_base` |
| `escalation.py` | Human escalation | `escalate_human`, `transfer_call_to_call_center` |

### Knowledge Base Tool

The `search_knowledge_base` tool provides semantic search:

```python
# Tool usage in agent
result = await execute_tool("search_knowledge_base", {
    "query": "What is the fee refund policy?",
    "collection": "policies",
    "top_k": 5,
})

# Returns:
# {
#     "success": True,
#     "results": [
#         {"title": "Fee Refund Policy", "content": "...", "score": 0.92},
#         ...
#     ],
#     "source": "cosmos_vector"  # or "mock" if Cosmos not configured
# }
```

---

## State Management

### Memory Manager

Session state and conversation history:

```python
from src.stateful.state_managment import MemoManager

# Load or create session
memory_manager = MemoManager.from_redis(session_id, redis_mgr)

# Conversation history
memory_manager.append_to_history("user", "Hello")
memory_manager.append_to_history("assistant", "Hi there!")

# Context storage
memory_manager.set_context("target_number", "+1234567890")

# Persist to Redis
await memory_manager.persist_to_redis_async(redis_mgr)
```

### Redis Session Management

```python
from src.redis.manager import AzureRedisManager

redis_mgr = AzureRedisManager(
    host="your-redis.redis.cache.windows.net",
    credential=DefaultAzureCredential()
)

# Session data with TTL
await redis_mgr.set_value_async(f"session:{session_id}", data, expire=3600)
```

---

## Observability

### OpenTelemetry Tracing

```python
from utils.telemetry_config import configure_tracing

configure_tracing(
    service_name="voice-agent-api",
    service_version="v1.0.0",
    otlp_endpoint=OTEL_EXPORTER_OTLP_ENDPOINT
)
```

### Structured Logging

```python
from utils.ml_logging import get_logger

logger = get_logger("api.v1.media")

logger.info(
    "Session started",
    extra={
        "session_id": session_id,
        "call_connection_id": call_connection_id,
    }
)
```

### Latency Tracking

```python
from src.tools.latency_tool import LatencyTool

latency_tool = LatencyTool(memory_manager)

latency_tool.start("greeting_ttfb")
await send_greeting_audio()
latency_tool.stop("greeting_ttfb")
```

---

## Authentication

### Azure Entra ID Integration

```python
from azure.identity import DefaultAzureCredential

# Keyless authentication for all Azure services
credential = DefaultAzureCredential()
```

### WebSocket Authentication

```python
from apps.artagent.backend.src.utils.auth import validate_acs_ws_auth

try:
    await validate_acs_ws_auth(websocket, required_scope="media.stream")
except AuthError:
    await websocket.close(code=4001, reason="Authentication required")
```

---

## Related Documentation

- [Resource Pools](../architecture/speech/resource-pools.md) - Pool configuration and troubleshooting
- [Agent Framework](../../apps/artagent/backend/agents/README.md) - Creating and configuring agents
- [Streaming Modes](../architecture/speech/README.md) - SpeechCascade vs VoiceLive
