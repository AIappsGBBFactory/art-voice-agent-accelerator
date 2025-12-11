# Session-Agent Mapping Architecture

> **Audience:** Junior developers and new team members  
> **Last Updated:** December 2025

This document explains how agents get mapped to sessions and how state flows through the system.
Both orchestrators (Cascade and VoiceLive) use the **shared session_state module** for consistency.

---

## Quick Reference: Key Files

| File | Purpose | Read First? |
|------|---------|-------------|
| [voice/shared/session_state.py](../voice/shared/session_state.py) | **Single source of truth** for state sync | ✅ Yes |
| [agents/loader.py](loader.py) | Discovers agents from YAML, builds handoff_map | ✅ Yes |
| [voice/shared/config_resolver.py](../voice/shared/config_resolver.py) | Resolves which agents to use (with scenario support) | ✅ Yes |
| [agents/session_manager.py](session_manager.py) | Per-session agent overrides (FUTURE USE) | ❌ Skip for now |

---

## How It Works: The Happy Path

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SESSION STARTUP                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. AGENT DISCOVERY (happens once at app startup)                           │
│     ┌──────────────────────────────────────────────────────────────────┐    │
│     │  discover_agents()                                               │    │
│     │       ↓                                                          │    │
│     │  Scans agents/ directory for agent.yaml files                    │    │
│     │       ↓                                                          │    │
│     │  Returns: Dict[agent_name, UnifiedAgent]                         │    │
│     │                                                                  │    │
│     │  build_handoff_map(agents)                                       │    │
│     │       ↓                                                          │    │
│     │  Returns: Dict[tool_name, target_agent_name]                     │    │
│     │  e.g., {"handoff_fraud_agent": "FraudAgent"}                     │    │
│     └──────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  2. ORCHESTRATOR CREATION (happens per call/session)                        │
│     ┌──────────────────────────────────────────────────────────────────┐    │
│     │  resolve_orchestrator_config()                                   │    │
│     │       ↓                                                          │    │
│     │  Returns: OrchestratorConfigResult with:                         │    │
│     │    - agents: Dict of all agents                                  │    │
│     │    - handoff_map: Tool→Agent mappings                            │    │
│     │    - start_agent: Which agent starts the call                    │    │
│     │    - scenario: Optional scenario overrides                       │    │
│     │                                                                  │    │
│     │  CascadeOrchestratorAdapter.create(...) or LiveOrchestrator(...) │    │
│     │       ↓                                                          │    │
│     │  Orchestrator stores agents + handoff_map                        │    │
│     └──────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  3. STATE SYNC (per turn)                                                   │
│     ┌──────────────────────────────────────────────────────────────────┐    │
│     │  sync_state_from_memo(memo_manager)                              │    │
│     │       ↓                                                          │    │
│     │  Loads: active_agent, visited_agents, session_profile            │    │
│     │                                                                  │    │
│     │  ... orchestrator processes turn ...                             │    │
│     │                                                                  │    │
│     │  sync_state_to_memo(memo_manager, active_agent=..., ...)         │    │
│     │       ↓                                                          │    │
│     │  Persists state for next turn / session restore                  │    │
│     └──────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The Key Data Structures

### 1. UnifiedAgent (what an agent IS)

```python
# From agents/base.py
@dataclass
class UnifiedAgent:
    name: str              # "EricaConcierge"
    description: str       # "Main concierge agent"
    greeting: str          # "Hello, how can I help?"
    return_greeting: str   # "Welcome back!"
    
    # How to reach this agent from other agents
    handoff: HandoffConfig  # handoff.trigger = "handoff_concierge"
    
    # LLM settings
    model: ModelConfig      # deployment_id, temperature, etc.
    voice: VoiceConfig      # name, style, rate
    
    # The prompt template (Jinja2)
    prompt_template: str    # "You are a helpful concierge..."
    
    # Available tools
    tool_names: List[str]   # ["search_knowledge_base", "handoff_fraud_agent"]
```

### 2. OrchestratorConfigResult (what the orchestrator receives)

```python
# From voice/shared/config_resolver.py
@dataclass
class OrchestratorConfigResult:
    start_agent: str = "Concierge"
    agents: Dict[str, UnifiedAgent] = field(default_factory=dict)
    handoff_map: Dict[str, str] = field(default_factory=dict)  # tool→agent
    scenario: Optional[ScenarioConfig] = None
```

### 3. SessionState (what gets synced with MemoManager)

```python
# From voice/shared/session_state.py
@dataclass
class SessionState:
    active_agent: Optional[str] = None      # "EricaConcierge"
    visited_agents: Set[str] = field(...)   # {"Concierge", "FraudAgent"}
    system_vars: Dict[str, Any] = field(...)  # session_profile, client_id, etc.
    pending_handoff: Optional[Dict] = None  # For state-based handoffs
```

---

## Common Tasks

### "How do I add a new agent?"

1. Create `agents/<agent_name>/agent.yaml`
2. Add a `handoff.trigger` if other agents should route to it
3. Done! `discover_agents()` will find it automatically.

See [agents/README.md](README.md#adding-a-new-agent) for details.

### "How do I know which agent is active?"

```python
# In CascadeOrchestratorAdapter:
self._active_agent  # or self.current_agent property

# In LiveOrchestrator:
self.active  # or self.current_agent property
```

### "How does handoff detection work?"

```python
# When LLM calls a tool like "handoff_fraud_agent":
target = self.handoff_map.get("handoff_fraud_agent")  # → "FraudAgent"
if target:
    # It's a handoff! Switch agents.
    await self._switch_to(target, system_vars)
```

### "Where does session_profile come from?"

1. User calls in → ACS provides caller phone number
2. Backend looks up profile in Redis/Cosmos via `load_user_profile_by_client_id()`
3. Profile is stored in `MemoManager.corememory["session_profile"]`
4. Orchestrator syncs it to `self._system_vars["session_profile"]`
5. Prompt templates can use `{{session_profile.name}}`

---

## What's NOT Used Yet

### SessionAgentManager

The `agents/session_manager.py` provides per-session agent overrides (change prompts, voice, tools at runtime). It's **not integrated** into production orchestrators yet.

**When it will be used:**
- A/B testing of agent configurations
- Admin UI for real-time prompt tuning
- Per-customer agent customization

For now, you can safely ignore this file when onboarding.

---

## Debugging Tips

### "Agent not found" errors

```python
# Check what agents were discovered:
from apps.artagent.backend.registries.agentstore import discover_agents
agents = discover_agents()
print(list(agents.keys()))  # Should show your agent
```

### "Handoff not working"

```python
# Check the handoff_map:
from apps.artagent.backend.registries.agentstore import discover_agents, build_handoff_map
agents = discover_agents()
handoff_map = build_handoff_map(agents)
print(handoff_map)  # Should show tool→agent mappings

# Make sure your agent.yaml has:
handoff:
  trigger: handoff_your_agent_name  # This becomes the key in handoff_map
```

### "State not persisting between turns"

```python
# Check MemoManager has the state:
mm = orchestrator.memo_manager
print(mm.get_value_from_corememory("active_agent"))
print(mm.get_value_from_corememory("session_profile"))
```

---

## Related Documentation

- [Agent Framework](../../../docs/architecture/agent-framework.md) - Full agent system docs
- [Orchestration Overview](../../../docs/architecture/orchestration/README.md) - How orchestrators work
- [Handoff Strategies](../../../docs/architecture/handoff-strategies.md) - Agent-to-agent transfers
