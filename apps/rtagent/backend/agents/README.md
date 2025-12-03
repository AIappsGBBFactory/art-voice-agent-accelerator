# 🤖 Unified Agent Framework

This directory contains the **modular agent framework** for the ART Voice Agent Accelerator. It provides a clean, YAML-driven approach to defining agents that work seamlessly with both SpeechCascade and VoiceLive orchestrators.

## 📁 Directory Structure

```
agents/
├── README.md                  # This documentation
├── _defaults.yaml             # Shared defaults (model, voice, session)
├── base.py                    # UnifiedAgent dataclass & helpers
├── loader.py                  # Agent discovery & loading
├── session_manager.py         # 🔮 Session-level agent management (future)
│
├── concierge/                 # Example: Entry-point agent
│   ├── agent.yaml             # Agent configuration
│   └── prompt.jinja           # Prompt template
│
├── fraud_agent/               # Example: Specialist agent
│   ├── agent.yaml
│   └── prompt.jinja
│
└── tools/                     # Shared tool registry
    ├── __init__.py
    ├── registry.py            # Core registration logic
    ├── banking.py             # Banking tools
    ├── handoffs.py            # Handoff tools
    └── ...                    # Other tool modules
```

---

## 🚀 Quick Start

### Loading Agents

```python
from apps.rtagent.backend.agents.loader import discover_agents, build_handoff_map

# Discover all agents from the agents/ directory
agents = discover_agents()

# Build the handoff map (tool_name → target_agent)
handoff_map = build_handoff_map(agents)

# Get a specific agent
concierge = agents.get("Concierge")

# Render a prompt with runtime context
prompt = concierge.render_prompt({
    "caller_name": "John",
    "customer_intelligence": {"tier": "platinum"},
})

# Get OpenAI-compatible tool schemas
tools = concierge.get_tools()
```

### Using the Tool Registry

```python
from apps.rtagent.backend.agents.tools import (
    initialize_tools,
    execute_tool,
    get_tools_for_agent,
)

# Initialize all tools (call once at startup)
initialize_tools()

# Get tools for specific agent
tools = get_tools_for_agent(["get_account_summary", "handoff_fraud_agent"])

# Execute a tool
result = await execute_tool("get_account_summary", {"client_id": "12345"})
```

---

## 📖 How the Loader Works

The **loader** (`loader.py`) provides auto-discovery and configuration loading for agents:

### Discovery Process

1. **Scans the `agents/` directory** for subdirectories containing `agent.yaml`
2. **Loads shared defaults** from `_defaults.yaml`
3. **Deep-merges** agent-specific config with defaults
4. **Resolves prompts** from file references (`.jinja`, `.md`, `.txt`)
5. **Returns** a `Dict[str, UnifiedAgent]` mapping agent names to configs

### Key Functions

| Function | Description |
|----------|-------------|
| `discover_agents(path)` | Auto-discover all agents in directory |
| `build_handoff_map(agents)` | Build tool_name → agent_name mapping |
| `get_agent(name)` | Load a single agent by name |
| `list_agent_names()` | List all discovered agent names |
| `render_prompt(agent, context)` | Render prompt with runtime variables |

### Example: Discovery Flow

```python
# Directory structure:
# agents/
#   _defaults.yaml        ← Shared defaults
#   concierge/
#     agent.yaml          ← Agent-specific config
#     prompt.jinja        ← Prompt template
#   fraud_agent/
#     agent.yaml
#     prompt.jinja

agents = discover_agents()
# Returns: {"Concierge": UnifiedAgent(...), "FraudAgent": UnifiedAgent(...)}
```

---

## 🔮 Session Manager (Future Use)

> **Note:** The `SessionAgentManager` is designed for future use and is **not currently integrated** into the production orchestrators. It provides infrastructure for runtime agent modification.

### Purpose

The **SessionAgentManager** enables:
- **Per-session agent overrides** (prompt, voice, model, tools)
- **Runtime hot-swap** of agent configurations
- **A/B testing** with experiment tracking
- **Persistence** via Redis/MemoManager

### Future Integration Example

```python
from apps.rtagent.backend.agents.session_manager import SessionAgentManager

# Create manager for a session (future pattern)
session_mgr = SessionAgentManager(
    session_id="session_123",
    base_agents=discover_agents(),
    memo_manager=memo,
)

# Get agent with session overrides applied
agent = session_mgr.get_agent("Concierge")

# Modify agent at runtime (without restart)
session_mgr.update_agent_prompt("Concierge", "New prompt...")
session_mgr.update_agent_voice("Concierge", VoiceConfig(name="en-US-EmmaNeural"))

# Track A/B experiments
session_mgr.set_experiment("voice_experiment", "variant_b")
```

### When This Will Be Used

The SessionAgentManager will be integrated when:
- Dynamic prompt modification via admin UI is needed
- A/B testing of agent configurations is implemented
- Real-time agent tuning during calls is required

---

## ➕ Adding a New Agent

### Step 1: Create Agent Directory

```bash
mkdir -p agents/my_new_agent
```

### Step 2: Create `agent.yaml`

```yaml
# agents/my_new_agent/agent.yaml

name: MyNewAgent
description: Handles specific customer requests

greeting: "Hi, I'm the MyNewAgent. How can I help?"
return_greeting: "Welcome back! What can I do for you?"

# Handoff configuration
handoff:
  trigger: handoff_my_new_agent    # Tool name that routes TO this agent
  strategy: auto                    # Works with any orchestrator

# Override defaults (optional)
voice:
  name: en-US-AriaNeural
  rate: "-5%"

# Tools available to this agent
tools:
  - get_user_profile
  - get_account_summary
  - handoff_concierge   # Can route back to Concierge

# Prompt template (file reference)
prompts:
  path: prompt.jinja
```

### Step 3: Create `prompt.jinja`

```jinja
You are {{ agent_name | default('MyNewAgent') }}, a specialist at {{ institution_name | default('Contoso Bank') }}.

Your capabilities:
- Help with specific customer requests
- Route to Concierge for general inquiries

Customer Context:
- Name: {{ caller_name | default('Customer') }}
{% if customer_intelligence %}
- Tier: {{ customer_intelligence.tier | default('standard') }}
{% endif %}

Always be helpful, professional, and concise.
```

### Step 4: Add Handoff Tool (if needed)

If other agents need to route TO your agent, add the handoff tool:

```python
# agents/tools/handoffs.py (add to existing file)

handoff_my_new_agent_schema = {
    "name": "handoff_my_new_agent",
    "description": "Transfer to MyNewAgent for specific requests",
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why transferring"},
        },
        "required": ["reason"],
    },
}

async def execute_handoff_my_new_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": True,
        "handoff": True,
        "target_agent": "MyNewAgent",
        "message": "Connecting you to our specialist.",
    }

# Register the tool
register_tool(
    "handoff_my_new_agent",
    handoff_my_new_agent_schema,
    execute_handoff_my_new_agent,
    is_handoff=True,
)
```

### Step 5: Update Calling Agents

Add the handoff tool to agents that should route to your new agent:

```yaml
# agents/concierge/agent.yaml
tools:
  - ...existing tools...
  - handoff_my_new_agent   # ← Add this
```

---

## 🔧 Adding a New Tool

### Step 1: Choose or Create a Tool Module

Tools are organized by domain in `agents/tools/`:
- `banking.py` - Account, transaction, card tools
- `auth.py` - Identity verification, MFA
- `fraud.py` - Fraud detection tools
- `handoffs.py` - Agent transfer tools
- `escalation.py` - Human escalation tools

### Step 2: Define Schema and Executor

```python
# agents/tools/banking.py (add to existing file)

from apps.rtagent.backend.agents.tools.registry import register_tool

# 1. Define the schema (OpenAI function calling format)
my_new_tool_schema = {
    "name": "my_new_tool",
    "description": "Does something useful for the customer",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Customer identifier",
            },
            "option": {
                "type": "string",
                "enum": ["option_a", "option_b"],
                "description": "Which option to use",
            },
        },
        "required": ["client_id"],
    },
}

# 2. Define the executor (sync or async)
async def execute_my_new_tool(args: dict) -> dict:
    client_id = args.get("client_id")
    option = args.get("option", "option_a")
    
    # Your business logic here
    result = do_something(client_id, option)
    
    return {
        "success": True,
        "message": f"Completed action for {client_id}",
        "data": result,
    }

# 3. Register the tool
register_tool(
    "my_new_tool",
    my_new_tool_schema,
    execute_my_new_tool,
    tags={"banking"},  # Optional: for filtering
)
```

### Step 3: Add to Agent Configuration

```yaml
# agents/concierge/agent.yaml
tools:
  - ...existing tools...
  - my_new_tool   # ← Add here
```

### Tool Best Practices

| Do | Don't |
|----|-------|
| Return `{"success": True/False, ...}` | Return bare values |
| Include descriptive `message` field | Leave errors unexplained |
| Handle exceptions gracefully | Let exceptions bubble up |
| Use `async` for I/O operations | Block the event loop |
| Add `is_handoff=True` for handoff tools | Forget handoff flag |

---

## 📋 Configuration Reference

### `agent.yaml` Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique agent identifier |
| `description` | string | ❌ | Human-readable description |
| `greeting` | string | ❌ | Initial greeting (Jinja template) |
| `return_greeting` | string | ❌ | Greeting when returning to agent |
| `handoff.trigger` | string | ❌ | Tool name that routes TO this agent |
| `handoff.strategy` | string | ❌ | `auto`, `tool_based`, or `state_based` |
| `voice.name` | string | ❌ | Azure TTS voice name |
| `voice.rate` | string | ❌ | Speech rate (e.g., "-5%") |
| `model.deployment_id` | string | ❌ | Azure OpenAI deployment |
| `model.temperature` | float | ❌ | Response creativity (0-1) |
| `tools` | list | ❌ | Tool names from registry |
| `prompts.path` | string | ❌ | Path to prompt file |

### `_defaults.yaml`

Shared defaults inherited by all agents unless overridden:

```yaml
model:
  deployment_id: gpt-4o
  temperature: 0.7

voice:
  name: en-US-ShimmerTurboMultilingualNeural
  type: azure-standard

session:
  modalities: [TEXT, AUDIO]
  turn_detection:
    type: azure_semantic_vad
    silence_duration_ms: 700

template_vars:
  institution_name: "Contoso Financial"
```

---

## 🔄 Handoff Flow

```
┌─────────────┐    handoff_fraud_agent    ┌─────────────┐
│  Concierge  │ ─────────────────────────► │ FraudAgent  │
└─────────────┘                            └─────────────┘
       ▲                                          │
       │           handoff_concierge              │
       └──────────────────────────────────────────┘
```

1. **Agent A** calls `handoff_agent_b` tool
2. **Orchestrator** looks up target in `handoff_map`
3. **Orchestrator** switches active agent to **Agent B**
4. **Agent B** receives context and continues conversation

---

## 🧪 Testing Agents

```python
import pytest
from apps.rtagent.backend.agents.loader import discover_agents, build_handoff_map

def test_all_agents_load():
    agents = discover_agents()
    assert len(agents) > 0
    assert "Concierge" in agents

def test_handoff_map_complete():
    agents = discover_agents()
    handoff_map = build_handoff_map(agents)
    
    # Every handoff tool should have a target
    for agent in agents.values():
        if agent.handoff.trigger:
            assert agent.handoff.trigger in handoff_map

def test_agent_tools_exist():
    from apps.rtagent.backend.agents.tools import initialize_tools, get_tool_schema
    initialize_tools()
    
    agents = discover_agents()
    for agent in agents.values():
        for tool_name in agent.tool_names:
            assert get_tool_schema(tool_name) is not None, f"Tool {tool_name} not found"
```

---

## 📚 Related Documentation

- [Voice Channels Architecture](../../voice_channels/README.md)
- [Tool Registry Deep Dive](./tools/README.md)
- [SpeechCascade Orchestrator](../../voice_channels/speech_cascade/README.md)
- [VoiceLive Orchestrator](../../voice_channels/voicelive/README.md)
