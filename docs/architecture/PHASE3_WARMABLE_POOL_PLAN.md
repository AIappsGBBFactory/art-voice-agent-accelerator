# Phase 3: WarmableResourcePool Implementation Plan

> **Status:** Phase 3a ✅ | Phase 3b ✅ | Phase 3c ✅ | Phase 3d Pending  
> **Date:** 2025-12-04  
> **Prerequisite:** Phase 1 & Phase 2 Complete ✅

---

## Executive Summary

Phase 3 implements a `WarmableResourcePool` to replace `OnDemandResourcePool` for Speech services, providing consistent low-latency resource allocation through pre-warmed connection pools with background maintenance.

**Phase 3a (Cleanup) is now complete.** The following files were removed:
- ❌ `src/pools/aoai_pool.py` - Anti-pattern (OpenAI clients don't benefit from pooling)
- ❌ `src/pools/dedicated_tts_pool.py` - Dead code (never wired up)
- ❌ `src/pools/voice_live_pool.py` - Orphaned (no imports)
- ❌ `src/pools/async_pool.py` - Replaced (`AllocationTier` moved to `on_demand_pool.py`)

---

## Part 1: Technical Debt Audit

### 1.1 Pool Implementations Inventory (Post-Cleanup)

| File | Class | Status | Notes |
|------|-------|--------|-------|
| `on_demand_pool.py` | `OnDemandResourcePool` | ✅ **ACTIVE** | Primary pool, now includes `AllocationTier` enum |
| `connection_manager.py` | `ConnectionManager` | ✅ **ACTIVE** | WebSocket connection tracking |
| `session_manager.py` | Session management | ✅ **ACTIVE** | Session lifecycle |
| `session_metrics.py` | Session metrics | ✅ **ACTIVE** | Telemetry |
| `websocket_manager.py` | WebSocket utilities | ✅ **ACTIVE** | WS helpers |

### 1.2 Redundant Pattern Analysis (Historical Reference)

```
src/pools/
├── on_demand_pool.py      # Simple factory wrapper (USED)
├── async_pool.py          # Complex pool with session awareness (NOT USED directly)
├── dedicated_tts_pool.py  # TTS-specific reimplementation (NOT USED)
├── voice_live_pool.py     # Voice Live agent pool (ORPHANED)
└── aoai_pool.py           # Azure OpenAI pool (ANTI-PATTERN - NOT USED)
```

**Issue:** `async_pool.py` and `dedicated_tts_pool.py` implement nearly identical functionality:
- Session-aware allocation
- Multi-tier strategy (dedicated/warm/cold)
- Background pre-warming
- Cleanup loops

**Recommendation:** Consolidate into a single `WarmableResourcePool` that serves as the unified implementation.

### 1.3 Anti-Pattern: OpenAI Client Pooling (`aoai_pool.py`)

**Why this is problematic:**

1. **OpenAI clients are stateless** - The `AzureOpenAI` client is just an HTTP client wrapper. It doesn't maintain persistent connections that benefit from pooling.

2. **HTTP/2 connection reuse is automatic** - The underlying `httpx` client already reuses connections via connection pooling at the transport layer.

3. **No SDK concurrency limits** - Unlike Azure Speech SDK (which has per-instance stream limits), OpenAI clients can handle concurrent requests.

4. **Memory overhead** - Creating 10 OpenAI client instances pre-emptively wastes memory:
   ```python
   AOAI_POOL_SIZE = int(os.getenv("AOAI_POOL_SIZE", "10"))  # 10 clients!
   ```

5. **Complexity without benefit** - The `AOAIClientPool` adds:
   - Session allocation tracking
   - Client metrics
   - Load balancing logic
   - All for no performance gain

**Evidence of non-use:**
```bash
# grep for actual imports in production code
grep -r "from src.pools.aoai_pool import" --include="*.py" | grep -v test | grep -v docs
# Result: NONE
```

**Recommendation:** Delete `aoai_pool.py`. The Phase 1 warmup (`warm_openai_connection`) is sufficient for HTTP/2 connection establishment.

### 1.4 Unused Pool Files

#### `dedicated_tts_pool.py`

- **Created:** Appears to be an earlier attempt at per-session TTS allocation
- **Problem:** `tts_health.py` references `app.state.tts_pool`, which is an `OnDemandResourcePool`, not a `DedicatedTtsPoolManager`
- **Status:** Dead code that never got integrated

#### `voice_live_pool.py`

- **Created:** For Voice Live SDK agent pre-warming
- **Problem:** No imports found outside the file itself
- **Status:** Orphaned - may have been superseded by different architecture

#### `async_pool.py`

- **Created:** Attempted unified pool with session awareness
- **Problem:** `OnDemandResourcePool` imports only `AllocationTier` enum from it
- **Status:** Over-engineered, never adopted

---

## Part 2: Recommended Cleanup Actions

### Action 1: Delete Unused Pool Files

```bash
# Files to delete:
rm src/pools/aoai_pool.py           # Anti-pattern, never used
rm src/pools/dedicated_tts_pool.py  # Superseded by OnDemandResourcePool
rm src/pools/voice_live_pool.py     # Orphaned, no imports
```

**Risk:** Low - none of these files are imported in production code.

### Action 2: Simplify `async_pool.py`

Either:
- **Option A:** Delete entirely, move `AllocationTier` to `on_demand_pool.py`
- **Option B:** Rename to `pool_types.py` and keep only the enum/dataclasses

### Action 3: Update `tts_health.py`

The endpoint tries to call `.snapshot()` on `app.state.tts_pool` which is an `OnDemandResourcePool`. This works because `OnDemandResourcePool` has a `snapshot()` method, but the naming is confusing.

### Action 4: Configuration Cleanup

Remove unused environment variables:
```python
# These are defined but have no effect since the pools aren't used:
AOAI_POOL_ENABLED = os.getenv("AOAI_POOL_ENABLED", "true")
AOAI_POOL_SIZE = int(os.getenv("AOAI_POOL_SIZE", "10"))
TTS_POOL_SIZE = int(os.getenv("POOL_SIZE_TTS", "100"))  # 100 is excessive
TTS_POOL_PREWARMING_ENABLED = os.getenv("TTS_POOL_PREWARMING_ENABLED", "true")
VOICE_LIVE_POOL_SIZE = int(os.getenv("POOL_SIZE_VOICE_LIVE", "8"))
```

---

## Part 3: WarmableResourcePool Design

### 3.1 Design Goals

1. **Replace OnDemandResourcePool** - Drop-in replacement with warmup capabilities
2. **Minimal complexity** - No over-engineering
3. **Configurable warmup** - Enable/disable via environment
4. **Background maintenance** - Replenish warm pool periodically
5. **Session awareness** - Optional per-session resource binding

### 3.2 Proposed Implementation

```python
# src/pools/warmable_pool.py

class WarmableResourcePool(Generic[T]):
    """
    Resource pool with optional pre-warming and session awareness.
    
    Tiers:
    1. DEDICATED - Per-session cached resource (0ms)
    2. WARM - Pre-created resource from pool (<50ms)
    3. COLD - On-demand factory call (~200ms)
    """
    
    def __init__(
        self,
        *,
        factory: Callable[[], Awaitable[T]],
        name: str,
        # Warmup configuration
        warm_pool_size: int = 0,           # 0 = no pre-warming (OnDemand behavior)
        enable_background_warmup: bool = False,
        warmup_interval_sec: float = 30.0,
        # Session configuration
        session_awareness: bool = False,
        session_max_age_sec: float = 1800.0,
        # Warmup function (optional)
        warm_fn: Optional[Callable[[T], Awaitable[bool]]] = None,
    ):
        ...
```

### 3.3 Migration Path

```python
# Before (current main.py):
app.state.tts_pool = OnDemandResourcePool(
    factory=make_tts,
    session_awareness=True,
    name="speech-tts",
)

# After (Phase 3):
app.state.tts_pool = WarmableResourcePool(
    factory=make_tts,
    name="speech-tts",
    # Phase 3 additions:
    warm_pool_size=5,                    # Pre-create 5 TTS instances
    enable_background_warmup=True,       # Maintain pool level
    session_awareness=True,              # Keep per-session caching
    warm_fn=lambda tts: tts.warm_connection(),  # Use Phase 2 warmup
)
```

### 3.4 Key Differences from Over-Engineered Pools

| Feature | async_pool.py | dedicated_tts_pool.py | WarmableResourcePool |
|---------|---------------|----------------------|---------------------|
| Lines of Code | ~500 | ~500 | ~200 (target) |
| Background Tasks | 2 (prewarm + cleanup) | 2 (prewarm + cleanup) | 1 (combined) |
| Session Tracking | Complex dataclass | Complex dataclass | Simple dict |
| Metrics | Detailed | Detailed | Minimal |
| Generic | Yes | No (TTS-specific) | Yes |
| Default Behavior | Complex | Complex | Simple (OnDemand) |

---

## Part 4: Implementation Plan

### Phase 3a: Cleanup (1-2 hours)

1. ✅ Delete `src/pools/aoai_pool.py`
2. ✅ Delete `src/pools/dedicated_tts_pool.py`  
3. ✅ Delete `src/pools/voice_live_pool.py`
4. ✅ Move `AllocationTier` to `on_demand_pool.py`
5. ✅ Delete or simplify `async_pool.py`
6. ✅ Update any remaining imports

### Phase 3b: WarmableResourcePool (2-3 hours)

1. ✅ Create `src/pools/warmable_pool.py` (~320 lines)
2. ✅ Implement core pool with:
   - Warm queue (asyncio.Queue)
   - Session cache (dict with last_used tracking)
   - Background warmup task (combined warmup + cleanup)
   - `warm_fn` callback support
3. ✅ Write unit tests (28 tests in `tests/test_warmable_pool.py`)
4. ✅ API compatibility with `OnDemandResourcePool`

### Phase 3c: Integration (1-2 hours)

1. ✅ Update `main.py` to use `WarmableResourcePool`
2. ✅ Configure warmup settings via environment:
   ```
   WARM_POOL_ENABLED=true          # Enable/disable warm pools
   WARM_POOL_TTS_SIZE=3             # Pre-warm 3 TTS instances
   WARM_POOL_STT_SIZE=2             # Pre-warm 2 STT instances  
   WARM_POOL_BACKGROUND_REFRESH=true
   WARM_POOL_REFRESH_INTERVAL=30.0
   WARM_POOL_SESSION_MAX_AGE=1800.0
   ```
3. ✅ Update warmup step to coordinate with pool warmup
4. ✅ Test end-to-end (48 pool tests passing)
5. ✅ **Consolidation cleanup pass:**
   - Removed redundant `OnDemandResourcePool` branch from `main.py`
   - Always use `WarmableResourcePool` (with `warm_pool_size=0` when disabled)
   - Added `src/pools/__init__.py` with public exports
   - Deprecated `websocket_manager.py` (unused in production)

### Phase 3d: Monitoring (1 hour) ✅

1. ✅ Added `PoolMetrics` and `PoolsHealthResponse` schemas to `health.py`
2. ✅ Added `/api/v1/pools` endpoint with detailed pool metrics:
   - Warm pool levels vs targets
   - Allocation tier breakdown (DEDICATED/WARM/COLD)
   - Hit rate percentage calculation
   - Session cache statistics
3. ✅ Pool snapshot() already includes all needed metrics for dashboards

---

## ✅ PHASE 3 COMPLETE

All phases implemented and tested:
- **Phase 3a:** Cleanup - 4 dead pool files deleted (~1650 lines)
- **Phase 3b:** WarmableResourcePool - 320 lines, 28 tests
- **Phase 3c:** Integration - env vars, main.py updated
- **Phase 3d:** Monitoring - /api/v1/pools endpoint, metrics schemas

Total pool tests: 48 passing

---

## Part 5: Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking changes during cleanup | Low | Medium | All deleted code is unused |
| Warm pool resources timeout | Medium | Low | Background refresh loop |
| Increased startup time | Low | Low | Warmup is parallel/async |
| Memory overhead from warm pool | Medium | Low | Configurable pool size |

---

## Part 6: Success Metrics

| Metric | Before (OnDemand) | After (Warmable) | Target |
|--------|-------------------|------------------|--------|
| First STT latency | ~300-600ms | <100ms | -80% |
| First TTS latency | ~200-400ms | <50ms | -80% |
| Cold allocations | 100% | <20% | -80% |
| Warm allocations | 0% | >80% | >80% |

---

## Appendix: Files to Delete

### `src/pools/aoai_pool.py` - ANTI-PATTERN
- 300 lines of unused code
- OpenAI clients don't benefit from pooling
- Never imported in main.py or handlers

### `src/pools/dedicated_tts_pool.py` - DEAD CODE
- 500 lines duplicating async_pool.py functionality
- TTS-specific implementation that was never wired up
- `tts_health.py` accesses `app.state.tts_pool` which is NOT this class

### `src/pools/voice_live_pool.py` - ORPHANED
- 250 lines for Voice Live agent pooling
- No imports found in production code
- May have been superseded by different architecture

### `src/pools/async_pool.py` - OVER-ENGINEERED
- 600 lines of complex pool logic
- Only `AllocationTier` enum is used externally
- Can be replaced with simple enum file

---

*Document prepared for architecture review. Proceed with cleanup before implementing WarmableResourcePool.*
