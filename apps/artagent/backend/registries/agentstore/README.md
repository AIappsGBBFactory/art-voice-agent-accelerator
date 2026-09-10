# 🤖 Unified Agent Framework

This directory contains the **modular agent framework** for the ART Voice Agent Accelerator. It provides a clean, YAML-driven approach to defining agents that work seamlessly with both SpeechCascade and VoiceLive orchestrators.

## 📁 Directory Structure

```
agents/
├── README.md                  # This documentation
├── _defaults.yaml             # Shared defaults (model, voice, session)
├── base.py                    # UnifiedAgent dataclass & helpers
├── loader.py                  # Agent discovery & loading
│
├── concierge/                 # Example: Entry-point agent
│   ├── agent.yaml             # Agent configuration
│   └── prompt.jinja           # Prompt template
│
├── fraud_agent/               # Example: Specialist agent
│   ├── agent.yaml
│   └── prompt.jinja
│
├── scenarios/                 # Scenario-specific configurations
│   └── banking/               # Banking demo scenario
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
from apps.artagent.backend.registries.agentstore import discover_agents, build_handoff_map

# Discover all agents from the registries/agentstore/ directory
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
from apps.artagent.backend.registries.toolstore import (
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

## Definition and live-session boundaries

The unused `SessionAgentManager` subsystem is removed. Runtime tuning already
uses `src/orchestration/session_agents.py` and `session_scenarios.py`, builder
endpoints and native orchestrator update callbacks; there is no second catalog.
Experiment labels can be stored in ordinary agent metadata.

`registries/definitions.py` projects and validates the existing dataclasses for
YAML loading, builder schemas, persisted definitions and editable responses.
Aliases/presets remain API-specific; declared fields, empty/null values and
server-side `source_dir` provenance share one codec. Builder updates cannot
introduce arbitrary client-supplied executable source directories.

Async API/session entry points prime the definition views from the current memo
or awaited Redis hydration. Live changes reuse the memo held by the existing
application/engine registries. Redis ordering remains per memo, not distributed
CAS. Native VoiceLive SDK projection, session updates and greeting requests live
in `voice/voicelive/session.py`; they are not methods on the neutral agent.

See [the human extension guide](../../../../../docs/voice-extension-guide.md)
for ordinary field/policy changes and the compatibility retirement map.

---

# ➕ Adding a New Agent

This section provides a comprehensive, step-by-step guide for adding a new agent to the framework.

## Overview: What You Need

To add a new agent, you'll create:

| File | Purpose | Required? |
|------|---------|-----------|
| `agents/<agent_name>/agent.yaml` | Agent configuration (identity, tools, voice, prompt) | ✅ Yes |
| `agents/<agent_name>/prompt.jinja` | Prompt template (external file) | ❌ Optional |
| `agents/tools/handoffs.py` | Handoff tool (if other agents route TO this agent) | Only if routable |
| `agents/<agent_name>/tools.py` | Agent-specific custom tools | ❌ Optional |

> **Note:** You can define prompts either inline in `agent.yaml` OR in a separate `prompt.jinja` file. See [Step 4](#step-4-define-the-prompt) for both approaches.

## Step 1: Plan Your Agent

Before writing code, answer these questions:

| Question | Example Answer |
|----------|----------------|
| What is this agent's specialty? | "Handles retirement and 401k questions" |
| What tools does it need? | `get_account_summary`, `calculate_retirement_projection` |
| Can other agents route to it? | Yes → needs a handoff tool |
| Should it route to other agents? | Yes → include those handoff tools |
| What voice personality? | Professional, calm, slightly slower pace |

## Step 2: Create the Agent Directory

```bash
# Create the agent directory
mkdir -p apps/artagent/backend/registries/agentstore/my_new_agent
```

## Step 3: Create `agent.yaml`

The `agent.yaml` file defines your agent's identity, behavior, and capabilities.

### Minimal Configuration

```yaml
# registries/agentstore/my_new_agent/agent.yaml
name: MyNewAgent
description: Brief description of what this agent does

greeting: "Hello, I'm here to help with your request."
return_greeting: "Welcome back! What else can I help with?"

# Handoff: How other agents route TO this agent
handoff:
  trigger: handoff_my_new_agent

# Tools this agent can use
tools:
  - get_user_profile
  - handoff_concierge  # Return to main agent

# Prompt template
prompts:
  path: prompt.jinja
```

### Full Configuration (with all options)

```yaml
# ═══════════════════════════════════════════════════════════════════════════════
# My New Agent - Unified Schema
# ═══════════════════════════════════════════════════════════════════════════════
# Description of what this agent does and when it's used
# ═══════════════════════════════════════════════════════════════════════════════

name: MyNewAgent
description: |
  Detailed description of the agent's purpose.
  Can be multi-line for complex explanations.

# Greetings (support Jinja2 templates)
greeting: "Hi, I'm {{ agent_name | default('the specialist') }} at {{ institution_name | default('Contoso Bank') }}. How can I help?"
return_greeting: "Welcome back! What else can I help with?"

# ─────────────────────────────────────────────────────────────────────────────
# Handoff Configuration
# ─────────────────────────────────────────────────────────────────────────────
handoff:
  trigger: handoff_my_new_agent   # Tool name that routes TO this agent
  is_entry_point: false           # Set true only for the default starting agent

# ─────────────────────────────────────────────────────────────────────────────
# Model Configuration (overrides _defaults.yaml)
# ─────────────────────────────────────────────────────────────────────────────
model:
  deployment_id: gpt-4o           # Azure OpenAI deployment name
  temperature: 0.7                # Lower = more focused, higher = more creative
  top_p: 0.9
  max_tokens: 4096

# ─────────────────────────────────────────────────────────────────────────────
# Voice Configuration (Azure TTS)
# ─────────────────────────────────────────────────────────────────────────────
voice:
  name: en-US-AriaNeural          # Azure TTS voice
  type: azure-standard
  rate: "-5%"                     # Slow down 5% for clarity

# ─────────────────────────────────────────────────────────────────────────────
# Session Configuration (VoiceLive-specific)
# ─────────────────────────────────────────────────────────────────────────────
session:
  modalities: [TEXT, AUDIO]
  input_audio_format: PCM16
  output_audio_format: PCM16

  input_audio_transcription_settings:
    model: azure-speech
    language: en-US

  turn_detection:
    type: azure_semantic_vad
    threshold: 0.5
    prefix_padding_ms: 240
    silence_duration_ms: 700

  tool_choice: auto

# ─────────────────────────────────────────────────────────────────────────────
# Tools (referenced by name from shared registry)
# ─────────────────────────────────────────────────────────────────────────────
tools:
  # Core functionality
  - get_user_profile
  - get_account_summary

  # Handoffs to other agents
  - handoff_concierge        # Return to main assistant

  # Escalation
  - escalate_human
  - transfer_call_to_call_center

# ─────────────────────────────────────────────────────────────────────────────
# Prompt (file reference)
# ─────────────────────────────────────────────────────────────────────────────
prompts:
  path: prompt.jinja

# ─────────────────────────────────────────────────────────────────────────────
# Template Variables (available in prompt rendering)
# ─────────────────────────────────────────────────────────────────────────────
template_vars:
  custom_var: "Custom value available in prompt"
```

### Configuration Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Unique agent identifier (e.g., `FraudAgent`) |
| `description` | string | `""` | Human-readable description |
| `greeting` | string | `""` | Initial greeting (supports Jinja2) |
| `return_greeting` | string | `""` | Greeting when returning to agent |
| `handoff.trigger` | string | `""` | Tool name that routes TO this agent |
| `handoff.is_entry_point` | bool | `false` | Is this the default starting agent? |
| `model.deployment_id` | string | `gpt-4o` | Azure OpenAI deployment |
| `model.temperature` | float | `0.7` | Response creativity (0-1) |
| `voice.name` | string | `en-US-ShimmerTurboMultilingualNeural` | Azure TTS voice |
| `voice.rate` | string | `+0%` | Speech rate adjustment |
| `tools` | list | `[]` | Tool names from registry |
| `prompts.path` | string | `""` | Path to prompt file (relative to agent dir) |
| `template_vars` | dict | `{}` | Custom variables for prompt rendering |

## Step 4: Define the Prompt

You have **two options** for defining your agent's prompt:

### Option A: Inline Prompt in `agent.yaml` (Simpler)

For shorter prompts, define them directly in `agent.yaml`:

```yaml
# agents/my_new_agent/agent.yaml
name: MyNewAgent
description: Handles specific customer requests

greeting: "Hello, I'm here to help."
return_greeting: "Welcome back!"

handoff:
  trigger: handoff_my_new_agent

tools:
  - get_user_profile
  - handoff_concierge

# Inline prompt using 'prompts.content'
prompts:
  content: |
    You are **{{ agent_name | default('Specialist') }}** at {{ institution_name | default('Contoso Bank') }}.

    # YOUR ROLE
    Help customers with specific requests.

    # CUSTOMER CONTEXT
    {% if session_profile %}
    - **Name:** {{ session_profile.full_name }}
    - **Client ID:** {{ session_profile.client_id }}
    {% else %}
    No profile loaded. Ask for identification if needed.
    {% endif %}

    # GUIDELINES
    - Keep responses brief (1-3 sentences)
    - For general questions → use `handoff_concierge`
```

### Option B: External `prompt.jinja` File (Recommended for Complex Prompts)

For longer prompts with complex logic, use a separate file:

```yaml
# agents/my_new_agent/agent.yaml
name: MyNewAgent
description: Handles specific customer requests

greeting: "Hello, I'm here to help."
return_greeting: "Welcome back!"

handoff:
  trigger: handoff_my_new_agent

tools:
  - get_user_profile
  - handoff_concierge

# External prompt file reference
prompts:
  path: prompt.jinja
```

Then create the prompt file:

```jinja
{# agents/my_new_agent/prompt.jinja #}
You are **{{ agent_name | default('Specialist') }}** at {{ institution_name | default('Contoso Bank') }}.

# YOUR ROLE
[Detailed description of responsibilities...]

# CUSTOMER CONTEXT
{% if session_profile %}
## Authenticated Customer
- **Name:** {{ session_profile.full_name }}
- **Client ID:** {{ session_profile.client_id }}
{% if session_profile.customer_intelligence %}
- **Tier:** {{ session_profile.customer_intelligence.relationship_context.relationship_tier | default('Standard') }}
{% endif %}
{% else %}
## New Customer
No profile loaded. Gather necessary information before proceeding.
{% endif %}

# ... more sections ...
```

### Which Option to Choose?

| Use Inline (`prompts.content`) | Use External File (`prompts.path`) |
|-------------------------------|-----------------------------------|
| Prompt is < 50 lines | Prompt is > 50 lines |
| Simple, straightforward logic | Complex conditional sections |
| Quick prototyping | Production agents |
| Single-purpose agents | Agents with detailed routing rules |

### Available Template Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `agent_name` | agent config or env | Display name of the agent |
| `institution_name` | env or defaults | Bank/company name |
| `caller_name` | runtime context | Customer's name (if known) |
| `client_id` | runtime context | Customer identifier |
| `session_profile` | runtime context | Full customer profile object |
| `customer_intelligence` | runtime context | Customer data and insights |
| `previous_agent` | runtime context | Agent that handed off (if any) |
| `handoff_context` | runtime context | Context passed during handoff |

### Prompt Template Example (External File)

```jinja
You are **{{ agent_name | default('Specialist') }}**, a {{ description | default('specialist') }} at {{ institution_name | default('Contoso Bank') }}.

# YOUR ROLE
[Describe what this agent does and its key responsibilities]

# CUSTOMER CONTEXT
{% if session_profile %}
## Authenticated Customer
- **Name:** {{ session_profile.full_name }}
- **Client ID:** {{ session_profile.client_id }}
{% if session_profile.customer_intelligence %}
- **Tier:** {{ session_profile.customer_intelligence.relationship_context.relationship_tier | default('Standard') }}
{% endif %}
{% else %}
## New Customer
No profile loaded yet. Gather necessary information before proceeding.
{% endif %}

# AVAILABLE ACTIONS
You have these tools:
{% for tool in tools %}
- `{{ tool }}`
{% endfor %}

# HANDOFF RULES
- For general questions → `handoff_concierge`
- For fraud concerns → `handoff_fraud_agent`
- Always say goodbye before transferring

# CONVERSATION GUIDELINES
- Keep responses brief (1-3 sentences)
- Spell out numbers for voice clarity
- Ask one question at a time

{% if previous_agent %}
# INCOMING HANDOFF
You received this customer from **{{ previous_agent }}**.
{% if handoff_context %}
Context: {{ handoff_context | tojson }}
{% endif %}
{% endif %}
```

### Prompt Writing Best Practices

| Do ✅ | Don't ❌ |
|-------|---------|
| Use clear section headers | Write walls of text |
| Provide specific tool usage examples | Assume the model knows your domain |
| Include conditional sections with `{% if %}` | Hard-code customer details |
| Use `| default()` filters for optional values | Leave template variables undefined |
| Keep instructions actionable | Use vague language |
| Test with various context combinations | Only test the happy path |

## Step 5: Add Handoff Tool (if other agents route to yours)

If other agents need to transfer customers to your agent, create a handoff tool.

### Add to `agents/tools/handoffs.py`

```python
# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF TO MY NEW AGENT
# ═══════════════════════════════════════════════════════════════════════════════

# 1. Define the schema
handoff_my_new_agent_schema: Dict[str, Any] = {
    "name": "handoff_my_new_agent",
    "description": (
        "Transfer to MyNewAgent for [specific purpose]. "
        "Use when customer mentions [trigger phrases]."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Customer identifier",
            },
            "reason": {
                "type": "string",
                "description": "Why the customer needs this specialist",
            },
            "context": {
                "type": "string",
                "description": "Additional context for the specialist",
            },
        },
        "required": ["client_id"],
    },
}

# 2. Define the executor
async def handoff_my_new_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to MyNewAgent."""
    client_id = (args.get("client_id") or "").strip()
    reason = (args.get("reason") or "").strip()
    context = (args.get("context") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("🔄 Handoff to MyNewAgent | client=%s reason=%s", client_id, reason)
    
    return _build_handoff_payload(
        target_agent="MyNewAgent",  # Must match agent.yaml 'name' field
        message="Let me connect you with our specialist.",
        summary=f"Specialist request: {reason or 'customer inquiry'}",
        context={
            "client_id": client_id,
            "reason": reason,
            "additional_context": context,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "Concierge",
        },
        extra={"should_interrupt_playback": True},
    )

# 3. Register the tool
register_tool(
    "handoff_my_new_agent",
    handoff_my_new_agent_schema,
    handoff_my_new_agent,
    is_handoff=True,  # IMPORTANT: Mark as handoff tool
    tags={"handoff"},
)
```

### Handoff Payload Structure

```python
{
    "handoff": True,                    # Signals orchestrator to switch agents
    "target_agent": "MyNewAgent",       # Must match agent.yaml name
    "message": "Transition message",    # Spoken to customer during transfer
    "handoff_summary": "Brief context", # For logging/debugging
    "handoff_context": {                # Passed to target agent's prompt
        "client_id": "CLT-123",
        "reason": "needs specialist",
        "handoff_timestamp": "2024-12-03T10:30:00Z",
        "previous_agent": "Concierge",
    },
    "should_interrupt_playback": True,  # Optional: stop current TTS
}
```

## Step 6: Update Calling Agents

Add your handoff tool to agents that should be able to route to your new agent.

```yaml
# agents/concierge/agent.yaml
tools:
  # ... existing tools ...
  - handoff_my_new_agent   # ← Add this line
```

## Step 7: Test Your Agent

### Verify Agent Loads

```python
from apps.artagent.backend.registries.agentstore import discover_agents, build_handoff_map

# Check agent is discovered
agents = discover_agents()
assert "MyNewAgent" in agents, "Agent not found!"

# Check handoff mapping
handoff_map = build_handoff_map(agents)
assert "handoff_my_new_agent" in handoff_map, "Handoff not mapped!"
assert handoff_map["handoff_my_new_agent"] == "MyNewAgent"

# Check tools resolve
agent = agents["MyNewAgent"]
tools = agent.get_tools()
assert len(tools) > 0, "No tools loaded!"
```

### Test Prompt Rendering

```python
agent = agents["MyNewAgent"]

# Test with minimal context
prompt = agent.render_prompt({})
assert "{{ " not in prompt, "Unrendered template variables!"

# Test with full context
prompt = agent.render_prompt({
    "caller_name": "John Smith",
    "client_id": "CLT-001",
    "session_profile": {"full_name": "John Smith"},
})
assert "John Smith" in prompt
```

### Integration Test

```python
import pytest
from apps.artagent.backend.registries.toolstore import initialize_tools, execute_tool

@pytest.mark.asyncio
async def test_handoff_to_my_new_agent():
    initialize_tools()
    
    result = await execute_tool("handoff_my_new_agent", {
        "client_id": "CLT-001",
        "reason": "needs specialist help",
    })
    
    assert result["handoff"] is True
    assert result["target_agent"] == "MyNewAgent"
```

---

# 🔄 Updating an Existing Agent

## Common Update Scenarios

### 1. Modify the Prompt

Edit the `prompt.jinja` file. Changes take effect on the next agent discovery (typically at startup or when `discover_agents()` is called).

```jinja
{# Add a new section to the prompt #}
# NEW CAPABILITY
You can now also help with [new feature].
```

### 2. Add a New Tool

**Step 1:** Add the tool to the registry (if it's new):

```python
# agents/tools/banking.py
register_tool("my_new_tool", schema, executor, tags={"banking"})
```

**Step 2:** Add to agent's tool list:

```yaml
# agents/my_agent/agent.yaml
tools:
  - existing_tool
  - my_new_tool  # ← Add here
```

### 3. Change Voice Settings

```yaml
# agents/my_agent/agent.yaml
voice:
  name: en-US-JennyNeural    # Change voice
  rate: "-10%"               # Slow down 10%
```

### 4. Adjust Model Parameters

```yaml
# agents/my_agent/agent.yaml
model:
  temperature: 0.5    # More focused responses
  max_tokens: 2048    # Shorter responses
```

### 5. Update Handoff Behavior

To change where your agent routes customers:

```yaml
# agents/my_agent/agent.yaml
tools:
  # Remove old handoff
  # - handoff_old_agent
  
  # Add new handoff
  - handoff_new_agent
```

---

# 🔧 Adding a New Tool

Tools are the actions agents can take. They follow OpenAI's function calling format.

## Step 1: Choose a Tool Module

| Module | Domain | Example Tools |
|--------|--------|---------------|
| `banking.py` | Account operations | `get_account_summary`, `refund_fee` |
| `auth.py` | Identity verification | `verify_client_identity`, `send_mfa_code` |
| `fraud.py` | Fraud detection | `check_suspicious_activity`, `block_card` |
| `handoffs.py` | Agent transfers | `handoff_concierge`, `handoff_fraud_agent` |
| `escalation.py` | Human escalation | `escalate_human`, `escalate_emergency` |
| `investment.py` | Investment services | `get_portfolio_summary` |
| `knowledge_base.py` | Information retrieval | `search_knowledge_base` |

## Step 2: Define Schema and Executor

```python
# registries/toolstore/banking.py

from apps.artagent.backend.registries.toolstore.registry import register_tool

# 1. Schema (OpenAI function calling format)
calculate_loan_payment_schema: Dict[str, Any] = {
    "name": "calculate_loan_payment",
    "description": (
        "Calculate monthly payment for a loan. "
        "Returns payment amount, total interest, and amortization preview."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "principal": {
                "type": "number",
                "description": "Loan amount in dollars",
            },
            "annual_rate": {
                "type": "number",
                "description": "Annual interest rate as decimal (e.g., 0.05 for 5%)",
            },
            "term_months": {
                "type": "integer",
                "description": "Loan term in months",
            },
        },
        "required": ["principal", "annual_rate", "term_months"],
    },
}

# 2. Executor (async preferred for I/O operations)
async def calculate_loan_payment(args: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate monthly loan payment."""
    principal = args.get("principal", 0)
    annual_rate = args.get("annual_rate", 0)
    term_months = args.get("term_months", 0)
    
    # Validation
    if principal <= 0:
        return {"success": False, "message": "Principal must be positive."}
    if term_months <= 0:
        return {"success": False, "message": "Term must be positive."}
    
    # Calculation
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        payment = principal / term_months
    else:
        payment = principal * (monthly_rate * (1 + monthly_rate) ** term_months) / \
                  ((1 + monthly_rate) ** term_months - 1)
    
    total_paid = payment * term_months
    total_interest = total_paid - principal
    
    return {
        "success": True,
        "monthly_payment": round(payment, 2),
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "message": f"Monthly payment: ${payment:.2f}",
    }

# 3. Register
register_tool(
    "calculate_loan_payment",
    calculate_loan_payment_schema,
    calculate_loan_payment,
    tags={"banking", "loans"},
)
```

## Tool Best Practices

| Practice | Example |
|----------|---------|
| **Always return a dict** | `{"success": True, "data": ...}` |
| **Include a message field** | Spoken to customer in voice apps |
| **Validate inputs** | Check required fields, ranges |
| **Handle exceptions** | Wrap in try/catch, return error dict |
| **Use async for I/O** | Database queries, API calls |
| **Add descriptive tags** | `tags={"banking", "loans"}` |
| **Log important actions** | `logger.info("Processing loan...")` |

## Agent-Specific Custom Tools

For tools unique to a single agent, create `tools.py` in the agent directory:

```python
# registries/agentstore/my_agent/tools.py

from apps.artagent.backend.registries.toolstore.registry import register_tool

# This file is auto-loaded when the agent is loaded
# Tools registered here can override shared tools if needed

my_special_tool_schema = {
    "name": "my_special_tool",
    "description": "Agent-specific tool",
    "parameters": {"type": "object", "properties": {}},
}

async def my_special_tool(args):
    return {"success": True, "message": "Special action completed."}

def register_tools():
    """Called automatically when agent loads."""
    register_tool(
        "my_special_tool",
        my_special_tool_schema,
        my_special_tool,
        override=True,  # Can override shared tools
    )

# Optional: Override the agent's tool list
TOOL_NAMES = ["my_special_tool", "handoff_concierge"]
```

---

## 📋 Configuration Reference

### `agent.yaml` Complete Schema

```yaml
# Identity
name: string              # Required: Unique identifier
description: string       # Optional: Human-readable description

# Greetings (Jinja2 templates)
greeting: string          # Optional: First-time greeting
return_greeting: string   # Optional: Returning customer greeting

# Handoff
handoff:
  trigger: string         # Tool name that routes TO this agent
  is_entry_point: bool    # Is this the default starting agent?

# Model (overrides _defaults.yaml)
model:
  deployment_id: string   # Azure OpenAI deployment
  temperature: float      # 0.0-1.0
  top_p: float           # 0.0-1.0
  max_tokens: int        # Max response tokens

# Voice (Azure TTS)
voice:
  name: string           # TTS voice name
  type: string           # azure-standard or azure-neural
  style: string          # Voice style (chat, cheerful, etc.)
  rate: string           # Speed adjustment (-50% to +50%)

# Session (VoiceLive SDK)
session:
  modalities: [TEXT, AUDIO]
  input_audio_format: string
  output_audio_format: string
  input_audio_transcription_settings:
    model: string
    language: string
  turn_detection:
    type: string
    threshold: float
    prefix_padding_ms: int
    silence_duration_ms: int
  tool_choice: string

# Tools
tools: [string]          # List of tool names from registry

# Prompt
prompts:
  path: string           # Relative path to prompt file
  content: string        # OR inline prompt content

# Template Variables
template_vars:
  key: value             # Custom variables for prompt rendering

# Metadata
metadata:
  key: value             # Custom metadata (not used by framework)
```

### `_defaults.yaml`

Shared defaults inherited by all agents:

```yaml
model:
  deployment_id: gpt-4o
  temperature: 0.7
  top_p: 0.9
  max_tokens: 4096

voice:
  name: en-US-ShimmerTurboMultilingualNeural
  type: azure-standard
  style: chat
  rate: "+0%"

session:
  modalities: [TEXT, AUDIO]
  input_audio_format: PCM16
  output_audio_format: PCM16
  turn_detection:
    type: azure_semantic_vad
    threshold: 0.5
    prefix_padding_ms: 240
    silence_duration_ms: 700
  tool_choice: auto

template_vars:
  institution_name: "Contoso Financial"
  agent_name: "Assistant"
```

---

## 🔄 Handoff Flow

```
┌─────────────┐    handoff_fraud_agent     ┌─────────────┐
│  Concierge  │ ─────────────────────────► │ FraudAgent  │
└─────────────┘                            └─────────────┘
       ▲                                          │
       │           handoff_concierge              │
       └──────────────────────────────────────────┘
```

### How Handoffs Work

1. **Agent A** calls a handoff tool (e.g., `handoff_fraud_agent`)
2. **Tool executor** returns `{"handoff": True, "target_agent": "FraudAgent", ...}`
3. **Orchestrator** looks up target in `handoff_map`
4. **Orchestrator** switches active agent to **Agent B**
5. **Agent B** receives `handoff_context` in its prompt rendering

### Handoff Context Flow

```python
# In Concierge, when calling handoff:
handoff_fraud_agent({
    "client_id": "CLT-001",
    "fraud_type": "unauthorized_charge",
    "issue_summary": "Customer saw $500 charge they don't recognize",
})

# FraudAgent's prompt receives:
{
    "previous_agent": "Concierge",
    "handoff_context": {
        "client_id": "CLT-001",
        "fraud_type": "unauthorized_charge",
        "issue_summary": "Customer saw $500 charge they don't recognize",
        "handoff_timestamp": "2024-12-03T10:30:00Z",
    }
}
```

---

## 🧪 Testing Agents

### Unit Tests

```python
import pytest
from apps.artagent.backend.registries.agentstore import discover_agents, build_handoff_map

def test_all_agents_load():
    """Verify all agents can be discovered and loaded."""
    agents = discover_agents()
    assert len(agents) > 0
    assert "Concierge" in agents

def test_handoff_map_complete():
    """Verify all handoff triggers are mapped."""
    agents = discover_agents()
    handoff_map = build_handoff_map(agents)
    
    for agent in agents.values():
        if agent.handoff.trigger:
            assert agent.handoff.trigger in handoff_map

def test_agent_tools_exist():
    """Verify all referenced tools are registered."""
    from apps.artagent.backend.registries.toolstore import initialize_tools, get_tool_schema
    initialize_tools()
    
    agents = discover_agents()
    for agent in agents.values():
        for tool_name in agent.tool_names:
            assert get_tool_schema(tool_name) is not None, \
                f"Tool {tool_name} not found for agent {agent.name}"

def test_prompts_render():
    """Verify prompts render without errors."""
    agents = discover_agents()
    for agent in agents.values():
        prompt = agent.render_prompt({})
        assert "{{ " not in prompt, \
            f"Unrendered variable in {agent.name}"
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_tool_execution():
    """Test that tools execute correctly."""
    from apps.artagent.backend.registries.toolstore import initialize_tools, execute_tool
    initialize_tools()
    
    result = await execute_tool("get_account_summary", {"client_id": "CLT-001"})
    assert result["success"] is True
    assert "accounts" in result

@pytest.mark.asyncio
async def test_handoff_execution():
    """Test handoff tool returns correct payload."""
    from apps.artagent.backend.registries.toolstore import initialize_tools, execute_tool
    initialize_tools()
    
    result = await execute_tool("handoff_fraud_agent", {
        "client_id": "CLT-001",
        "fraud_type": "unauthorized_charge",
    })
    
    assert result["handoff"] is True
    assert result["target_agent"] == "FraudAgent"
    assert "handoff_context" in result
```

---

## 🚨 Troubleshooting

### Agent Not Loading

```python
# Check for YAML syntax errors
import yaml
with open("agents/my_agent/agent.yaml") as f:
    config = yaml.safe_load(f)
print(config)

# Check discovery logs
import logging
logging.getLogger("agents.loader").setLevel(logging.DEBUG)
agents = discover_agents()
```

### Tool Not Found

```python
# Verify tool is registered
from apps.artagent.backend.registries.toolstore import initialize_tools, list_tools
initialize_tools()
print(list_tools())  # Should include your tool

# Check for import errors
from apps.artagent.backend.registries.toolstore import banking  # Should not error
```

### Handoff Not Working

```python
# Verify handoff map
from apps.artagent.backend.registries.agentstore import discover_agents, build_handoff_map
agents = discover_agents()
handoff_map = build_handoff_map(agents)
print(handoff_map)  # Should map tool name → agent name

# Verify target_agent matches agent name exactly
# In handoff tool: target_agent="MyNewAgent"
# In agent.yaml: name: MyNewAgent  (must match exactly)
```

### Prompt Variables Not Rendering

```python
# Test prompt rendering
agent = agents["MyAgent"]
prompt = agent.render_prompt({
    "caller_name": "Test User",
    "client_id": "CLT-001",
})
print(prompt)

# Check for undefined variables
# Use | default() filter: {{ var | default('fallback') }}
```

---

## 📚 Related Documentation

- [Voice Channels Architecture](../voice/README.md)
- [Tool Registry Details](./tools/README.md)
- [SpeechCascade Orchestrator](../voice/speech_cascade/README.md)
- [VoiceLive Orchestrator](../voice/voicelive/README.md)
- [Testing Guide](../../../../BANKING_TESTING_GUIDE.md)
