# Agent Handoff Strategies

> **Navigation**: [Architecture](./index.md) | [Voice Channels](./voice-channels.md) | [LLM Orchestration](./llm-orchestration.md)

This document explains the **agent handoff system** in the ART Voice Agent Accelerator—how specialized agents can transfer conversations to each other seamlessly, and how different voice transport mechanisms plug into this capability.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Handoff Strategies](#handoff-strategies)
   - [Tool-Based Handoff (VoiceLive)](#tool-based-handoff-voicelive)
   - [State-Based Handoff (Speech Cascade)](#state-based-handoff-speech-cascade)
4. [Integration with Voice Channels](#integration-with-voice-channels)
5. [Flow Diagrams](#flow-diagrams)
6. [Implementation Guide](#implementation-guide)
7. [Configuration Reference](#configuration-reference)

---

## Overview

In multi-agent voice systems, **handoffs** allow specialized agents to transfer conversations to each other. For example:
- A concierge agent (`EricaConcierge`) might transfer to a fraud specialist (`FraudAgent`)
- An investment advisor might escalate to compliance (`ComplianceDesk`)

The handoff system provides a **pluggable abstraction** that works across different voice transport mechanisms:

| Transport | Handoff Strategy | Trigger Mechanism |
|-----------|-----------------|-------------------|
| **VoiceLive SDK** | `ToolBasedHandoff` | LLM calls handoff tool (e.g., `handoff_fraud_agent`) |
| **Speech Cascade** | `StateBasedHandoff` | Session state change in MemoManager/Redis |

---

## Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          Voice Channels Layer                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────┐       ┌──────────────────────────────────┐ │
│  │   VoiceLiveSDKHandler   │       │       MediaHandler               │ │
│  │   (Azure VoiceLive)     │       │   (Speech Cascade Mode)          │ │
│  └───────────┬─────────────┘       └──────────────┬───────────────────┘ │
│              │                                    │                     │
│              ▼                                    ▼                     │
│  ┌─────────────────────────┐       ┌──────────────────────────────────┐ │
│  │ LiveOrchestratorAdapter │       │   SpeechCascadeHandler           │ │
│  │                         │       │                                  │ │
│  │  ┌───────────────────┐  │       │  ┌─────────────────────────────┐ │ │
│  │  │  ToolBasedHandoff │  │       │  │    StateBasedHandoff        │ │ │
│  │  │                   │  │       │  │                             │ │ │
│  │  │  handoff_map:     │  │       │  │  MemoManager.active_agent   │ │ │
│  │  │  ├─handoff_fraud  │  │       │  │  Redis: pending_handoff     │ │ │
│  │  │  │  →FraudAgent   │  │       │  │                             │ │ │
│  │  │  ├─handoff_paypal │  │       │  └─────────────────────────────┘ │ │
│  │  │  │  →PayPalAgent  │  │       │                                  │ │
│  │  │  └─handoff_trading│  │       │     ┌─────────────────────┐      │ │
│  │  │     →TradingDesk  │  │       │     │   gpt_flow.py       │      │ │
│  │  └───────────────────┘  │       │     │   (route_turn)      │      │ │
│  │                         │       │     └─────────────────────┘      │ │
│  └─────────────────────────┘       └──────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

                              HandoffContext
                         ┌───────────────────────┐
                         │ source_agent: String  │
                         │ target_agent: String  │
                         │ reason: String        │
                         │ user_last_utterance   │
                         │ context_data: Dict    │
                         │ greeting: Optional    │
                         └───────────────────────┘
                                    │
                                    ▼
                              HandoffResult
                         ┌───────────────────────┐
                         │ success: bool         │
                         │ target_agent: String  │
                         │ message: Optional     │
                         │ should_interrupt: bool│
                         └───────────────────────┘
```

---

## Handoff Strategies

### Tool-Based Handoff (VoiceLive)

**How it works**: The LLM calls a handoff function (defined in the agent's tools), which the orchestrator intercepts to trigger an agent switch.

```text
┌──────────────┐    ┌─────────────────┐    ┌───────────────────┐    ┌──────────────┐
│    User      │    │  EricaConcierge │    │ LiveOrchestrator  │    │  FraudAgent  │
│              │    │    (Active)     │    │                   │    │   (Target)   │
└──────┬───────┘    └────────┬────────┘    └─────────┬─────────┘    └──────┬───────┘
       │                     │                       │                      │
       │ "I think my card    │                       │                      │
       │  was stolen"        │                       │                      │
       │────────────────────►│                       │                      │
       │                     │                       │                      │
       │                     │ LLM decides handoff   │                      │
       │                     │ is needed             │                      │
       │                     │                       │                      │
       │                     │ Tool call:            │                      │
       │                     │ handoff_fraud_agent(  │                      │
       │                     │   reason="stolen card"│                      │
       │                     │   caller_name="John"  │                      │
       │                     │ )                     │                      │
       │                     │──────────────────────►│                      │
       │                     │                       │                      │
       │                     │                       │ 1. is_handoff_tool() │
       │                     │                       │    → true            │
       │                     │                       │                      │
       │                     │                       │ 2. Build context:    │
       │                     │                       │    source=Erica      │
       │                     │                       │    target=FraudAgent │
       │                     │                       │    reason=stolen card│
       │                     │                       │                      │
       │                     │                       │ 3. execute_handoff() │
       │                     │                       │    → success=true    │
       │                     │                       │                      │
       │                     │                       │ 4. _switch_to_agent()│
       │                     │                       │──────────────────────►│
       │                     │                       │                      │
       │                     │                       │                      │ Apply session
       │                     │                       │                      │ with handoff
       │                     │                       │                      │ context
       │                     │                       │                      │
       │ "I'm the fraud      │                       │                      │
       │  specialist. I see  │                       │◄─────────────────────│
       │  you're concerned   │                       │                      │
       │  about your card..."│                       │                      │
       │◄────────────────────┼───────────────────────┼──────────────────────│
       │                     │                       │                      │
```

**Configuration** (in `registry.py`):

```python
HANDOFF_MAP: Dict[str, str] = {
    "handoff_to_auth": "AuthAgent",
    "handoff_fraud_agent": "FraudAgent",
    "handoff_paypal_agent": "PayPalAgent",
    "handoff_to_trading": "TradingDesk",
    "handoff_to_compliance": "ComplianceDesk",
    # ... more mappings
}
```

**Tool Definition** (in agent YAML):

```yaml
tools:
  - name: handoff_fraud_agent
    description: Transfer to fraud specialist for suspicious activity
    parameters:
      type: object
      properties:
        reason:
          type: string
          description: Why the handoff is needed
        caller_name:
          type: string
          description: Customer's name for personalization
      required: [reason]
```

---

### State-Based Handoff (Speech Cascade)

**How it works**: Agent switches are managed through MemoManager/Redis state changes, allowing code-driven handoffs independent of LLM tool calls.

```text
┌──────────────┐    ┌─────────────────┐    ┌───────────────────┐     ┌──────────────┐
│    User      │    │  MediaHandler   │    │   MemoManager     │     │ Target Agent │
│              │    │ (SpeechCascade) │    │   + Redis         │     │              │
└──────┬───────┘    └────────┬────────┘    └─────────┬─────────┘     └──────┬───────┘
       │                     │                       │                      │
       │ Audio/Text input    │                       │                      │
       │────────────────────►│                       │                      │
       │                     │                       │                      │
       │                     │ route_turn()          │                      │
       │                     │ detects handoff need  │                      │
       │                     │                       │                      │
       │                     │ Update state:         │                      │
       │                     │ cm.update_corememory( │                      │
       │                     │   "active_agent",     │                      │
       │                     │   "FraudAgent"        │                      │
       │                     │ )                     │                      │
       │                     │──────────────────────►│                      │
       │                     │                       │                      │
       │                     │                       │ Redis publish:       │
       │                     │                       │ pending_handoff →    │
       │                     │                       │─────────────────────►│
       │                     │                       │                      │
       │                     │ Observe state change  │                      │
       │                     │◄──────────────────────│                      │
       │                     │                       │                      │
       │                     │ Load new agent config │                      │
       │                     │ Apply system prompt   │                      │
       │                     │─────────────────────────────────────────────►│
       │                     │                       │                      │
       │ Response from new   │                       │                      │
       │ agent               │                       │                      │
       │◄────────────────────│                       │                      │
       │                     │                       │                      │
```

**Key Differences from Tool-Based**:

| Aspect | Tool-Based | State-Based |
|--------|------------|-------------|
| **Trigger** | LLM tool call | Code/state change |
| **Agent Mapping** | Static `handoff_map` | Dynamic from args |
| **Context Storage** | Tool arguments | MemoManager/Redis |
| **Use Case** | VoiceLive multi-agent | ART Agent patterns |

---

## Integration with Voice Channels

### VoiceLive SDK Flow

```text
                     VoiceLiveSDKHandler
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
     LiveOrchestrator              Azure VoiceLive SDK
            │                               │
            ├─ start()                      │
            │   └── Apply first agent       │
            │                               │
            ├─ Event Loop ◄─────────────────┤ ServerEventType events
            │   │                           │
            │   ├─ FUNCTION_CALL_ARGUMENTS  │
            │   │   │                       │
            │   │   ├─ is_handoff_tool()?   │
            │   │   │   └── Yes → handle_handoff()
            │   │   │              ├── build_context_from_args()
            │   │   │              ├── execute_handoff()
            │   │   │              └── _switch_to_agent()
            │   │   │                       │
            │   │   └── No → execute_tool() │
            │   │              └── Send result to model
            │   │                           │
            │   ├─ RESPONSE_AUDIO_DELTA ────┤ Audio playback
            │   │                           │
            │   └─ RESPONSE_DONE ───────────┤ Turn complete
            │                               │
            └───────────────────────────────┘
```

### Speech Cascade Flow

```text
                      MediaHandler
                          │
         ┌────────────────┼────────────────┐
         │                │                │
         ▼                ▼                ▼
   SpeechSDKThread   RouteTurnThread   MainEventLoop
         │                │                │
         │                │                │
   STT Recognition        │                │
         │                │                │
         ├────────────────┤                │
         │   Final text   │                │
         │────────────────►                │
         │                │                │
         │           route_turn()          │
         │                │                │
         │           ┌────┴────┐           │
         │           │ gpt_flow│           │
         │           │ process │           │
         │           └────┬────┘           │
         │                │                │
         │    If handoff detected:         │
         │    MemoManager.update()         │
         │                │                │
         │                ├────────────────┤
         │                │  State change  │
         │                │  observed      │
         │                │                │
         │           Load new agent        │
         │           config from YAML      │
         │                │                │
         │           TTS Response          │
         │                │────────────────►
         │                │     on_tts()   │
         │                │                │
```

---

## Flow Diagrams

### Complete Handoff Lifecycle (VoiceLive)

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            HANDOFF LIFECYCLE                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. USER INPUT                                                                  │
│  ┌──────────────────┐                                                           │
│  │ "I think my card │                                                           │
│  │  was stolen"     │                                                           │
│  └────────┬─────────┘                                                           │
│           │                                                                     │
│           ▼                                                                     │
│  2. AGENT PROCESSING                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  EricaConcierge (active agent)                                       │       │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │       │
│  │  │ LLM evaluates: "stolen card" → needs fraud specialist           │ │       │
│  │  │ Selects tool: handoff_fraud_agent                               │ │       │
│  │  └─────────────────────────────────────────────────────────────────┘ │       │
│  └────────┬─────────────────────────────────────────────────────────────┘       │
│           │                                                                     │
│           ▼                                                                     │
│  3. HANDOFF DETECTION                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  HandoffStrategy.is_handoff_tool("handoff_fraud_agent")              │       │
│  │                    │                                                 │       │
│  │                    ▼                                                 │       │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │       │
│  │  │ HANDOFF_MAP lookup:                                             │ │       │
│  │  │   "handoff_fraud_agent" → "FraudAgent"  ✓ MATCH                 │ │       │
│  │  └─────────────────────────────────────────────────────────────────┘ │       │
│  └────────┬─────────────────────────────────────────────────────────────┘       │
│           │                                                                     │
│           ▼                                                                     │
│  4. CONTEXT BUILDING                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  HandoffContext:                                                     │       │
│  │  ├─ source_agent: "EricaConcierge"                                   │       │
│  │  ├─ target_agent: "FraudAgent"                                       │       │
│  │  ├─ reason: "stolen card"                                            │       │
│  │  ├─ user_last_utterance: "I think my card was stolen"                │       │
│  │  └─ context_data: {caller_name: "John", ...}                         │       │
│  └────────┬─────────────────────────────────────────────────────────────┘       │
│           │                                                                     │
│           ▼                                                                     │
│  5. HANDOFF EXECUTION                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  execute_handoff() → HandoffResult(success=True, target="FraudAgent")│       │
│  └────────┬─────────────────────────────────────────────────────────────┘       │
│           │                                                                     │
│           ▼                                                                     │
│  6. AGENT SWITCH                                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  _switch_to_agent("FraudAgent", system_vars)                         │       │
│  │  ├─ Cancel pending TTS/audio                                         │       │
│  │  ├─ Emit summary span for EricaConcierge (token usage)               │       │
│  │  ├─ Load FraudAgent configuration                                    │       │
│  │  ├─ Apply session.update() with new instructions                     │       │
│  │  ├─ Set messenger active agent                                       │       │
│  │  └─ Queue greeting if first visit                                    │       │
│  └────────┬─────────────────────────────────────────────────────────────┘       │
│           │                                                                     │
│           ▼                                                                     │
│  7. NEW AGENT RESPONSE                                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐       │
│  │  FraudAgent now active                                               │       │
│  │  ├─ Context injected: "user concerned about stolen card"             │       │
│  │  └─ Responds: "I'm the fraud specialist. I can help with that..."    │       │
│  └──────────────────────────────────────────────────────────────────────┘       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Barge-In During Handoff

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                     BARGE-IN DURING HANDOFF                               │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   User            Agent A             Orchestrator          Agent B       │
│     │                │                      │                   │         │
│     │   "transfer    │                      │                   │         │
│     │    please"     │                      │                   │         │
│     │───────────────►│                      │                   │         │
│     │                │                      │                   │         │
│     │                │ handoff_to_agent_b() │                   │         │
│     │                │─────────────────────►│                   │         │
│     │                │                      │                   │         │
│     │                │                      │ switch_to(B)      │         │
│     │                │                      │──────────────────►│         │
│     │                │                      │                   │         │
│     │                │                      │  Agent B starts   │         │
│     │                │                      │  greeting: "Hello │         │
│     │                │                      │  I'm Agent B..."  │         │
│     │                │                      │◄──────────────────│         │
│     │                │                      │                   │         │
│     │                │        TTS playing   │                   │         │
│     │◄───────────────┼──────────────────────│                   │         │
│     │                │                      │                   │         │
│     │  "Actually,    │                      │                   │         │
│     │   wait..."     │                      │                   │         │
│     │────────────────┼─────────────────────►│                   │         │
│     │                │                      │                   │         │
│     │                │         BARGE-IN!    │                   │         │
│     │                │                      │                   │         │
│     │                │      ┌───────────────┴──────────────┐    │         │
│     │                │      │ 1. Cancel TTS playback       │    │         │
│     │                │      │ 2. Stop audio                │    │         │
│     │                │      │ 3. Agent B processes new     │    │         │
│     │                │      │    user input                │    │         │
│     │                │      └───────────────┬──────────────┘    │         │
│     │                │                      │                   │         │
│     │  Agent B       │                      │                   │         │
│     │  responds to   │                      │◄──────────────────│         │
│     │  interruption  │                      │                   │         │
│     │◄───────────────┼──────────────────────│                   │         │
│     │                │                      │                   │         │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Guide

### Adding a New Handoff (VoiceLive)

1. **Define the tool in agent YAML**:

```yaml
# agents/EricaConcierge.yaml
tools:
  - name: handoff_new_specialist
    description: Transfer to the new specialist
    parameters:
      type: object
      properties:
        reason:
          type: string
          description: Why handoff is needed
        details:
          type: string
          description: Additional context
      required: [reason]
```

2. **Add to HANDOFF_MAP**:

```python
# registry.py
HANDOFF_MAP: Dict[str, str] = {
    # ... existing mappings
    "handoff_new_specialist": "NewSpecialistAgent",
}
```

3. **Create the target agent**:

```yaml
# agents/NewSpecialistAgent.yaml
name: NewSpecialistAgent
description: Specialist for new domain
greeting: "Hi, I'm the new specialist. I understand you need help with..."
return_greeting: "Welcome back to new specialist support."
system_prompt: |
  You are a specialist in the new domain.
  {{#if handoff_context}}
  Previous agent transferred because: {{handoff_context.reason}}
  {{/if}}
```

### Adding State-Based Handoff (Speech Cascade)

1. **Trigger handoff in code**:

```python
async def route_turn(cm: MemoManager, transcript: str, ws: WebSocket, **kwargs):
    # Detect need for handoff
    if should_handoff_to_specialist(transcript):
        # Update state to trigger handoff
        cm.update_corememory("pending_handoff", {
            "target_agent": "SpecialistAgent",
            "reason": "User requested specialist",
            "context": {"user_query": transcript}
        })
        cm.update_corememory("active_agent", "SpecialistAgent")
        return
    
    # Normal processing...
```

2. **Observe state in handler**:

```python
class MediaHandler:
    async def _check_handoff(self):
        pending = self.memory_manager.get_value_from_corememory("pending_handoff")
        if pending:
            await self._switch_to_agent(pending["target_agent"], pending)
            self.memory_manager.update_corememory("pending_handoff", None)
```

---

## Configuration Reference

### HandoffContext Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_agent` | `str` | Name of the agent initiating the handoff |
| `target_agent` | `str` | Name of the agent receiving the handoff |
| `reason` | `str` | Why the handoff is occurring |
| `user_last_utterance` | `str` | User's most recent speech for context |
| `context_data` | `Dict[str, Any]` | Additional structured context (caller info, etc.) |
| `session_overrides` | `Dict[str, Any]` | Configuration to apply to the new agent |
| `greeting` | `Optional[str]` | Explicit greeting for the new agent |

### HandoffResult Fields

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether the handoff completed successfully |
| `target_agent` | `Optional[str]` | The agent that is now active |
| `message` | `Optional[str]` | Message to speak after handoff |
| `error` | `Optional[str]` | Error message if handoff failed |
| `should_interrupt` | `bool` | Whether to cancel current TTS playback |

### How HandoffResult Maps to session.update()

The `HandoffResult` is a **signal**, not a direct API call. The actual `session.update()` happens downstream:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                  HandoffResult → session.update() Chain                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. execute_handoff()                                                       │
│     │                                                                       │
│     └──► HandoffResult(success=True, target_agent="FraudAgent")             │
│                │                                                            │
│                │  ┌─────────────────────────────────────────┐               │
│                │  │ HandoffResult is a SIGNAL, not action   │               │
│                │  │ It tells orchestrator: "proceed with    │               │
│                │  │ switch to FraudAgent"                   │               │
│                │  └─────────────────────────────────────────┘               │
│                │                                                            │
│                ▼                                                            │
│  2. LiveOrchestratorAdapter.handle_handoff()                                │
│     │                                                                       │
│     │  if result.success and result.target_agent:                           │
│     │      switch_vars = context.to_system_vars()                           │
│     │      await self._switch_to_agent(result.target_agent, switch_vars)    │
│     │                                                                       │
│     └──► _switch_to_agent("FraudAgent", system_vars)                        │
│                │                                                            │
│                ▼                                                            │
│  3. _switch_to_agent() implementation                                       │
│     │                                                                       │
│     │  agent = self.agents.get("FraudAgent")                                │
│     │  # ... emit summary span, update state ...                            │
│     │                                                                       │
│     └──► await agent.apply_session(conn, system_vars=vars_copy)             │
│                │                                                            │
│                ▼                                                            │
│  4. VoiceLiveAgent.apply_session()  ← THIS calls session.update()           │
│     │                                                                       │
│     │  session_payload = RequestSession(                                    │
│     │      instructions=self._render_prompt(system_vars),                   │
│     │      tools=self.tools,                                                │
│     │      voice=self._build_voice_payload(),                               │
│     │      ...                                                              │
│     │  )                                                                    │
│     │                                                                       │
│     └──► await conn.session.update(session=session_payload)  ← ACTUAL CALL  │
│                │                                                            │
│                ▼                                                            │
│  5. Azure VoiceLive SDK sends "session.update" to the realtime API          │
│     │                                                                       │
│     │  The model's instructions, tools, and voice are now FraudAgent's      │
│     │                                                                       │
│     └──► Model responds with new persona                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key insight**: `HandoffResult` is a data structure that carries the decision. The orchestrator interprets it and calls `_switch_to_agent()`, which eventually calls `agent.apply_session()` → `conn.session.update()`.

This separation allows:
- **Strategy** to make decisions without coupling to transport
- **Orchestrator** to manage timing, cancellation, and tracing
- **Agent** to apply its configuration to the session

### ToolBasedHandoff Configuration

```python
from voice_channels import ToolBasedHandoff

strategy = ToolBasedHandoff(
    handoff_map={
        "handoff_fraud_agent": "FraudAgent",
        "handoff_trading": "TradingDesk",
        "handoff_compliance": "ComplianceDesk",
    }
)

# Register additional handoffs dynamically
strategy.register_handoff("handoff_new_agent", "NewAgent")

# Check if a tool is a handoff
is_handoff = strategy.is_handoff_tool("handoff_fraud_agent")  # True

# Get target agent
target = strategy.get_target_agent("handoff_fraud_agent")  # "FraudAgent"
```

### StateBasedHandoff Configuration

```python
from voice_channels import StateBasedHandoff

strategy = StateBasedHandoff(
    agent_key="active_agent",        # MemoManager key for current agent
    handoff_key="pending_handoff",   # MemoManager key for pending handoff
)

# Built-in handoff tools
strategy.is_handoff_tool("switch_agent")        # True
strategy.is_handoff_tool("handoff_to_agent")    # True
strategy.is_handoff_tool("escalate_to_human")   # True
```

---

## Best Practices

### 1. Context Preservation

Always pass user context through handoffs:

```python
context = HandoffContext(
    source_agent="EricaConcierge",
    target_agent="FraudAgent",
    reason="Suspicious activity reported",
    user_last_utterance="I think my card was stolen",
    context_data={
        "caller_name": "John",
        "account_type": "Premium",
        "previous_issues": ["password_reset"]
    }
)
```

### 2. Graceful Greeting Selection

Let the system choose appropriate greetings:

- **First visit**: Agent's `greeting` field
- **Return visit**: Agent's `return_greeting` field  
- **Handoff with context**: Skip automatic greeting (agent handles naturally)
- **Explicit override**: Use `session_overrides.greeting`

### 3. Token Attribution

The system tracks token usage per agent for cost attribution:

```text
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  EricaConcierge │    │    FraudAgent   │    │   TradingDesk   │
│  ─────────────  │    │  ─────────────  │    │  ─────────────  │
│  Input:   450   │    │  Input:   320   │    │  Input:   180   │
│  Output:  120   │    │  Output:   85   │    │  Output:   45   │
│  Turns:     3   │    │  Turns:     2   │    │  Turns:     1   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                     │                      │
         └─────────────────────┴──────────────────────┘
                               │
                     Session Total: 1200 tokens
```

---

## Related Documentation

- [Voice Channels Architecture](./voice-channels.md)
- [LLM Orchestration](./llm-orchestration.md)
- [Multi-Agent Configuration](../guides/multi-agent-setup.md)
- [VoiceLive SDK Integration](../guides/voicelive-setup.md)

---

## Code Organization

### Folder Structure

The handoff system lives in a dedicated module for clarity and extensibility:

```text
voice_channels/
├── __init__.py
├── orchestrators/
│   ├── __init__.py
│   ├── base.py                    # VoiceOrchestrator protocol
│   ├── gpt_flow_adapter.py        # Speech Cascade adapter
│   ├── live_adapter.py            # VoiceLive adapter (consumes handoff strategies)
│   └── handoff.py                 # DEPRECATED - re-exports from handoffs/
│
├── handoffs/                       # Handoff subsystem
│   ├── __init__.py                 # Main exports
│   ├── context.py                  # HandoffContext, HandoffResult
│   ├── registry.py                 # HANDOFF_MAP configuration
│   └── strategies/
│       ├── __init__.py
│       ├── base.py                 # HandoffStrategy ABC
│       ├── tool_based.py           # ToolBasedHandoff (VoiceLive pattern)
│       └── state_based.py          # StateBasedHandoff (ART Agent pattern)
│
├── speech_cascade/
│   └── handler.py                  # MediaHandler (uses StateBasedHandoff)
│
└── voicelive/
    ├── handler.py                  # VoiceLiveSDKHandler
    └── orchestrator.py             # LiveOrchestrator (uses ToolBasedHandoff)
```

### Benefits of This Structure

| Aspect | Benefit |
|--------|---------|
| **Discoverability** | Handoff code lives in one place |
| **Extensibility** | Add new strategies (event-based, API-based) easily |
| **Separation of Concerns** | Strategies don't know about transports |
| **Testing** | Mock strategies independently from orchestrators |
| **Configuration** | `registry.py` centralizes HANDOFF_MAP |

### Import Patterns

```python
# Canonical imports from the handoffs module
from voice_channels.handoffs import (
    HandoffContext,
    HandoffResult,
    ToolBasedHandoff,
    StateBasedHandoff,
    HANDOFF_MAP,
)

# Or access strategies directly
from voice_channels.handoffs.strategies import ToolBasedHandoff

# Backward compatible (deprecated, shows warning)
from voice_channels.orchestrators.handoff import HandoffContext  # deprecated
```
