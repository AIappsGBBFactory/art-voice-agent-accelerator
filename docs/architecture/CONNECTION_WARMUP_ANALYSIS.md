# Connection Warmup Analysis for Azure Speech & Azure OpenAI

> **Status:** Proposal  
> **Date:** 2025-12-04  
> **Scope:** Service connection initialization optimization for low-latency voice applications

---

## Executive Summary

This document analyzes the current initialization patterns for Azure Speech (STT/TTS) and Azure OpenAI services in the real-time voice agent, identifies cold-start latency sources, and proposes strategies for connection warming to ensure optimal performance on new connections.

---

## 1. Current Architecture Analysis

### 1.1 Startup Flow (`main.py`)

The application initializes services in a sequential lifecycle:

```python
# Startup order from main.py lifespan()
1. core       → Redis, ConnectionManager, SessionManager
2. speech     → OnDemandResourcePool for STT and TTS (factories only)
3. aoai       → AzureOpenAI client attachment
4. services   → CosmosDB, ACS caller, PhraseListManager
5. agents     → UnifiedAgent discovery and loading
6. events     → Event handlers registration
```

**Key Finding:** The `speech` stage creates `OnDemandResourcePool` instances with **factory functions only** - no actual Azure Speech SDK connections are established until the first call.

### 1.2 Azure OpenAI Client Initialization

**Current Pattern ([src/aoai/client.py](../../src/aoai/client.py)):**

```python
# Lazy initialization pattern
_client_instance = None

def get_client():
    global _client_instance
    if _client_instance is None:
        _client_instance = create_azure_openai_client()
    return _client_instance
```

**Cold-Start Impact:**
- First LLM request incurs ~200-500ms for connection establishment
- Token refresh for Azure AD auth adds ~100-200ms on first call
- HTTP/2 connection negotiation adds ~50-100ms

### 1.3 Azure Speech Service Initialization

**STT ([src/speech/speech_recognizer.py](../../src/speech/speech_recognizer.py)):**

```python
def start(self):
    # Network connection happens HERE, not in __init__
    self.prepare_start()
    self.speech_recognizer.start_continuous_recognition_async().get()
```

**TTS ([src/speech/text_to_speech.py](../../src/speech/text_to_speech.py)):**

```python
def __init__(self, ...):
    # Only creates SpeechConfig - NO network connection
    self.cfg = self._create_speech_config()
    self._speaker = None  # Lazy - created on first use
```

**Cold-Start Impact:**
- First STT: ~300-600ms for WebSocket connection to Speech service
- First TTS: ~200-400ms for synthesis endpoint connection
- Token fetch (Azure AD): ~100-300ms if using managed identity

### 1.4 On-Demand Pool Pattern

**Current Implementation ([src/pools/on_demand_pool.py](../../src/pools/on_demand_pool.py)):**

```python
class OnDemandResourcePool:
    async def prepare(self) -> None:
        """Mark the provider as ready; no prewarming performed."""
        self._ready.set()  # Just sets a flag - NO resource creation

    async def acquire_for_session(self, session_id, timeout=None):
        """Return a cached resource for the session or create a new one."""
        # Resource is created HERE on first access
        resource = await self._factory()
```

**Impact:** Every new session incurs full cold-start latency for both STT and TTS.

---

## 2. Latency Sources Identified

| Component | Cold-Start Latency | Cause |
|-----------|-------------------|-------|
| **Azure OpenAI** | 200-500ms | HTTP/2 connection, TLS handshake, token acquisition |
| **Azure Speech STT** | 300-600ms | WebSocket connection, audio stream initialization |
| **Azure Speech TTS** | 200-400ms | Synthesis endpoint connection, voice model loading |
| **Azure AD Token** | 100-300ms | Token fetch for managed identity auth |
| **Voice Model** | 100-200ms | First synthesis for a new voice loads neural model |

**Total First-Call Latency:** 700-1500ms (worst case for new session)

---

## 3. Existing Warmup Mechanisms

### 3.1 TTS Voice Warm-up (Per-Session)

**Location:** [apps/rtagent/backend/voice/speech_cascade/tts_sender.py#L160-L195](../../apps/rtagent/backend/voice/speech_cascade/tts_sender.py#L160)

```python
# Voice warm-up (one-time per voice signature)
warm_signature = (voice_name, style, eff_rate)
prepared_voices: set = getattr(synth, "_prepared_voices", None)

if warm_signature not in prepared_voices:
    warm_partial = partial(
        synth.synthesize_to_pcm,
        text=" .",  # Minimal text to load voice model
        voice=voice_name,
        sample_rate=TTS_SAMPLE_RATE_UI,
        style=style,
        rate=eff_rate,
    )
    await loop.run_in_executor(executor, warm_partial)
    prepared_voices.add(warm_signature)
```

**Limitation:** This only warms after the TTS client is already acquired - doesn't address the initial connection latency.

### 3.2 STT Push Stream Pre-initialization

**Location:** [apps/rtagent/backend/voice/speech_cascade/handler.py#L343-L368](../../apps/rtagent/backend/voice/speech_cascade/handler.py#L343)

```python
def _pre_initialize_recognizer(self) -> None:
    """Pre-initialize push_stream to prevent audio data loss."""
    if hasattr(self.recognizer, "create_push_stream"):
        self.recognizer.create_push_stream()
```

**Limitation:** Creates local audio stream but doesn't establish network connection to Azure.

---

## 4. Proposed Warmup Strategies

### 4.1 Strategy: Background Connection Pool Warming

**Concept:** Pre-establish connections during startup, not on first request.

```python
# Proposed addition to main.py lifespan()

async def start_speech_pools() -> None:
    # ... existing pool creation ...
    
    # NEW: Background warm-up task
    async def warmup_pool():
        try:
            # Create one warm STT instance
            stt = await app.state.stt_pool.acquire(timeout=10.0)
            stt.prepare_start()  # Establishes WebSocket connection
            await app.state.stt_pool.release(stt)
            
            # Create one warm TTS instance  
            tts = await app.state.tts_pool.acquire(timeout=10.0)
            # Synthesize minimal audio to establish connection
            tts.synthesize_to_pcm(" .", sample_rate=16000)
            await app.state.tts_pool.release(tts)
            
            logger.info("Speech pools warmed successfully")
        except Exception as e:
            logger.warning("Speech pool warm-up failed (non-blocking): %s", e)
    
    # Run warmup in background (don't block startup)
    asyncio.create_task(warmup_pool())
```

**Pros:**
- Reduces first-call latency by 300-600ms
- Non-blocking startup
- Warm connection ready for first session

**Cons:**
- Connections may timeout if no calls arrive
- Additional startup cost (~500ms background)

### 4.2 Strategy: Proactive Token Refresh

**Concept:** Fetch Azure AD tokens during startup, not on first use.

```python
# Proposed addition to auth_manager.py

class SpeechTokenManager:
    async def warm_token(self) -> None:
        """Pre-fetch token during startup to avoid first-call latency."""
        try:
            self.get_token(force_refresh=True)
            logger.debug("Speech token pre-fetched successfully")
        except Exception as e:
            logger.warning("Token pre-fetch failed: %s", e)

# Usage in main.py
async def start_speech_pools():
    # Warm the token manager
    if not os.getenv("AZURE_SPEECH_KEY"):
        token_mgr = get_speech_token_manager()
        await asyncio.to_thread(token_mgr.warm_token)
```

**Pros:**
- Eliminates 100-300ms token latency
- Simple implementation
- Applicable to both Speech and OpenAI

**Cons:**
- Token has limited lifetime (~10 min default)
- Need refresh logic for long-running instances

### 4.3 Strategy: Dedicated Warm Connection Pool

**Concept:** Maintain a small pool of pre-connected, idle resources.

```python
# Proposed WarmableResourcePool

class WarmableResourcePool(OnDemandResourcePool[T]):
    """Resource pool with pre-warming capabilities."""
    
    def __init__(
        self,
        *,
        factory: Callable[[], Awaitable[T]],
        min_warm: int = 1,  # Minimum pre-warmed instances
        warm_interval_sec: float = 60.0,  # Re-warm interval
        **kwargs
    ):
        super().__init__(factory=factory, **kwargs)
        self._min_warm = min_warm
        self._warm_interval = warm_interval_sec
        self._warm_pool: list[T] = []
        self._warm_task: Optional[asyncio.Task] = None
    
    async def prepare(self) -> None:
        await super().prepare()
        self._warm_task = asyncio.create_task(self._warmup_loop())
    
    async def _warmup_loop(self) -> None:
        """Background task to maintain warm connections."""
        while True:
            try:
                while len(self._warm_pool) < self._min_warm:
                    resource = await self._factory()
                    await self._warm_resource(resource)
                    self._warm_pool.append(resource)
                    logger.debug("Warmed resource for pool: %s", self._name)
            except Exception as e:
                logger.warning("Warmup failed for %s: %s", self._name, e)
            
            await asyncio.sleep(self._warm_interval)
    
    async def _warm_resource(self, resource: T) -> None:
        """Override to implement resource-specific warming."""
        pass
    
    async def acquire_for_session(self, session_id, timeout=None):
        """Prefer warm resources, fall back to cold creation."""
        if self._warm_pool:
            resource = self._warm_pool.pop(0)
            self._metrics.allocations_cached += 1
            return resource, AllocationTier.DEDICATED
        
        return await super().acquire_for_session(session_id, timeout)
```

**Pros:**
- Guarantees warm resource availability
- Handles connection refresh automatically
- Scales with min_warm configuration

**Cons:**
- Increased memory/resource usage
- Complexity in managing warm pool lifecycle
- Need graceful handling of stale connections

### 4.4 Strategy: Azure OpenAI Connection Warming

**Concept:** Make a minimal API call during startup to establish HTTP/2 connection.

```python
# Proposed addition to aoai/client.py

async def warm_openai_connection(client: AzureOpenAI, deployment: str) -> bool:
    """Warm the OpenAI connection with a minimal request."""
    try:
        # Use a tiny prompt that exercises the connection
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=deployment,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0,
        )
        logger.info("OpenAI connection warmed successfully")
        return True
    except Exception as e:
        logger.warning("OpenAI warm-up failed: %s", e)
        return False

# Usage in main.py
async def start_aoai_client():
    client = AzureOpenAIClient()
    app.state.aoai_client = client
    
    # Background warm-up
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    asyncio.create_task(warm_openai_connection(client, deployment))
```

**Pros:**
- Eliminates 200-500ms first-call latency
- HTTP/2 connection reused for all subsequent calls
- Minimal token cost (1 output token)

**Cons:**
- Small cost per deployment restart
- May fail if deployment is misconfigured

### 4.5 Strategy: Health Check-Based Warming

**Concept:** Use the existing `/api/v1/readiness` probe to trigger warming.

```python
# Proposed enhancement to health.py

async def _check_speech_configuration_fast(stt_pool, tts_pool) -> ServiceCheck:
    # ... existing validation ...
    
    # NEW: Trigger warm-up if pools are cold
    if stt_pool and not getattr(stt_pool, "_warmed", False):
        asyncio.create_task(_warm_stt_pool(stt_pool))
    if tts_pool and not getattr(tts_pool, "_warmed", False):
        asyncio.create_task(_warm_tts_pool(tts_pool))
    
    # ... return check result ...

async def _warm_stt_pool(pool) -> None:
    """Warm STT pool on first readiness check."""
    try:
        stt, _ = await pool.acquire_for_session("warmup", timeout=10.0)
        stt.prepare_start()
        await pool.release_for_session("warmup", stt)
        pool._warmed = True
        logger.info("STT pool warmed via readiness check")
    except Exception as e:
        logger.warning("STT warmup failed: %s", e)
```

**Pros:**
- Integrates with existing Kubernetes probes
- Warming happens before first real traffic
- Observable via health check responses

**Cons:**
- Delayed warming until first probe
- May extend readiness probe time

---

## 5. Recommended Implementation Plan

### Phase 1: Quick Wins (Low Effort, High Impact)

1. **Token Pre-fetch** - Add to startup lifespan
   - Impact: -100-300ms first-call latency
   - Effort: ~30 min implementation

2. **OpenAI Connection Warm** - Background task after client creation
   - Impact: -200-500ms first LLM call
   - Effort: ~1 hour implementation

### Phase 2: Speech Service Optimization (Medium Effort)

3. **TTS Factory Warming** - Synthesize minimal audio during startup
   - Impact: -200-400ms first TTS call
   - Effort: ~2 hours implementation

4. **STT Push Stream Pre-connect** - Call `prepare_start()` proactively
   - Impact: -300-600ms first STT session
   - Effort: ~2 hours implementation

### Phase 3: Production-Grade Pool (Higher Effort)

5. **WarmableResourcePool** - Replace OnDemandResourcePool
   - Impact: Consistent low latency across all sessions
   - Effort: ~1 day implementation + testing

---

## 6. Metrics & Observability

### Proposed Telemetry

```python
# Add to startup spans
span.set_attribute("warmup.stt_ms", stt_warmup_duration)
span.set_attribute("warmup.tts_ms", tts_warmup_duration)
span.set_attribute("warmup.aoai_ms", aoai_warmup_duration)
span.set_attribute("warmup.token_ms", token_warmup_duration)

# Add to per-session spans
span.set_attribute("session.first_stt_ms", first_stt_latency)
span.set_attribute("session.first_tts_ms", first_tts_latency)
span.set_attribute("session.first_llm_ms", first_llm_latency)
span.set_attribute("session.resource_tier", allocation_tier.value)
```

### Dashboard Queries

```kusto
// Cold-start vs warm session latency
traces
| where name contains "process_turn" or name contains "tts_synthesis"
| extend session_type = iff(customDimensions.resource_tier == "COLD", "cold", "warm")
| summarize avg(duration), percentile(duration, 95) by session_type
```

---

## 7. Configuration Options

```python
# Proposed environment variables

# Enable/disable connection warming
ENABLE_CONNECTION_WARMUP = os.getenv("ENABLE_CONNECTION_WARMUP", "true")

# Warm pool sizes
WARM_POOL_STT_MIN = int(os.getenv("WARM_POOL_STT_MIN", "1"))
WARM_POOL_TTS_MIN = int(os.getenv("WARM_POOL_TTS_MIN", "1"))

# Warm refresh interval (seconds)
WARM_POOL_REFRESH_SEC = float(os.getenv("WARM_POOL_REFRESH_SEC", "60"))

# Startup warmup timeout
STARTUP_WARMUP_TIMEOUT_SEC = float(os.getenv("STARTUP_WARMUP_TIMEOUT_SEC", "10"))
```

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Warm connections timeout before use | Medium | Low | Background refresh loop |
| Increased startup time | Low | Medium | Make warming non-blocking |
| Resource exhaustion with warm pool | Low | Medium | Limit warm pool size |
| Token expiry during warmup | Low | Low | Refresh logic already exists |
| Cost increase from warm requests | Low | Low | Minimal tokens used |

---

## 9. Next Steps

1. **Review & Approve** - Discuss trade-offs with team
2. **Implement Phase 1** - Quick wins (token + OpenAI warming)
3. **Measure Baseline** - Capture current cold-start latencies
4. **Implement Phase 2** - Speech service warming
5. **Measure Improvement** - Compare to baseline
6. **Implement Phase 3** - Full warmable pool (if needed)

---

## Appendix A: Related Files

| File | Purpose |
|------|---------|
| [main.py](../../apps/rtagent/backend/main.py) | Application lifecycle & startup |
| [on_demand_pool.py](../../src/pools/on_demand_pool.py) | Resource pool implementation |
| [speech_recognizer.py](../../src/speech/speech_recognizer.py) | STT client |
| [text_to_speech.py](../../src/speech/text_to_speech.py) | TTS client |
| [client.py](../../src/aoai/client.py) | Azure OpenAI client |
| [auth_manager.py](../../src/speech/auth_manager.py) | Speech token management |
| [handler.py](../../apps/rtagent/backend/voice/speech_cascade/handler.py) | Speech cascade handler |
| [tts_sender.py](../../apps/rtagent/backend/voice/speech_cascade/tts_sender.py) | TTS sending with voice warmup |
| [health.py](../../apps/rtagent/backend/api/v1/endpoints/health.py) | Health check endpoints |

---

## Appendix B: Current vs Proposed Timing

```
Current Flow (First Call):
┌─────────────────────────────────────────────────────────────────┐
│ Call Arrives → Create STT → Connect → Create TTS → Connect     │
│     0ms         100ms        400ms      500ms       700ms       │
│                                                                 │
│ → Fetch Token → LLM Request → Response                          │
│     800ms          1000ms       1500ms                          │
└─────────────────────────────────────────────────────────────────┘
Total: ~1500ms to first response

Proposed Flow (With Warming):
┌─────────────────────────────────────────────────────────────────┐
│ [Startup: Token+Connections pre-warmed in background]          │
│                                                                 │
│ Call Arrives → Use Warm STT → Use Warm TTS → LLM Request       │
│     0ms           50ms           100ms          300ms           │
│                                                                 │
│ → Response                                                      │
│     800ms                                                       │
└─────────────────────────────────────────────────────────────────┘
Total: ~800ms to first response (47% improvement)
```

---

*Document prepared for architecture review. Feedback and iteration welcome.*
