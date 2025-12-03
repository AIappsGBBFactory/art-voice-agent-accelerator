# Change Notes - December 2025

## Multi-Agent Orchestration Improvements

### Handoff Flow Enhancements

#### Speech Cascade (`cascade_adapter.py`)
- **Seamless handoffs**: New agent now responds immediately after handoff completes instead of showing a confirmation message
- **Streaming timeout protection**: Added 90s overall timeout and 5s per-chunk timeout to prevent LLM streaming hangs
- **Fixed JSON parsing**: Handoff tool arguments now properly handle both string and dict formats

#### VoiceLive SDK (`live_orchestrator.py`, `agent_adapter.py`)
- **Fixed handoff response triggering**: New agent now properly introduces itself after handoff instead of sitting silent
- **Removed confusing transition messages**: Old agent's "I'll connect you to..." message no longer spoken by new agent
- **Added `cancel_active` support**: `trigger_response()` now cancels any active response before triggering to avoid conflicts
- **Context-aware handoff**: New agent receives instruction with handoff context to respond naturally

### Greeting & Prompt Rendering

#### Agent Base (`base.py`)
- **Fixed "I'm Assistant, your None assistant" bug**: Greeting context now filters out `None` values
- **Agent name defaults**: Uses agent's own `self.name` as fallback for `agent_name` in prompts
- **Prompt rendering**: `render_prompt()` now filters `None` and `"None"` string values from context

#### Session Context
- **Agent name tracking**: `route_turn()` now includes `agent_name` in session context
- **Explicit agent naming**: Media handler provides explicit `agent_name` for greeting derivation

### Tool Execution

#### Cascade Orchestrator
- **Fixed tool status UI**: Tool calls now properly show completion status
- **Fixed streaming index 0 bug**: Added validation to filter malformed tool calls with null indices
- **Session context continuity**: Context now persists correctly across agent switches

### General Improvements

- **GeneralKBAgent**: Converted from custom agent to use `search_knowledge_base` tool with proper handoff support
- **Redis session persistence**: Session context now persists to Redis for cross-request continuity
- **Auto-load user context**: User profile automatically loaded on handoff when `client_id` is present
