# ARTVoice Backend

FastAPI backend for real-time voice AI via Azure Communication Services.

## Architecture

```
Phone → ACS → WebSocket → STT → Multi-Agent AI → TTS → Audio
```

## Structure

```
backend/
├── main.py              # FastAPI app + startup
├── api/v1/              # REST + WebSocket endpoints
├── voice/               # Voice orchestration (SpeechCascade, VoiceLive)
├── registries/          # Agent, tool, scenario registration
└── config/              # Settings and feature flags
```

## Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/v1/media/stream` | ACS media streaming WebSocket |
| `/api/v1/realtime/conversation` | Real-time voice WebSocket |
| `/api/v1/calls/*` | Call management |
| `/health` | Health check |

## Core Folders

### `registries/` - Agent, Tool, Scenario System
```
registries/
├── agentstore/          # Agent definitions (YAML-based)
├── toolstore/           # Tool registry (@register_tool)
└── scenariostore/       # Industry scenarios (banking, etc.)
```

**Usage:**
```python
from apps.artagent.backend.registries.agentstore import discover_agents
from apps.artagent.backend.registries.toolstore import register_tool
from apps.artagent.backend.registries.scenariostore import load_scenario
```

See [`registries/README.md`](./registries/README.md) for details.

### `voice/` - Voice Orchestration
```
voice/
├── speech_cascade/      # Custom STT/TTS pipeline orchestrator
├── voicelive/           # Azure OpenAI Realtime API orchestrator
└── handoffs/            # Agent handoff logic
```

Two orchestration paths:
- **SpeechCascade**: Custom pipeline (Azure Speech STT → AOAI → Azure Speech TTS)
- **VoiceLive**: Managed API (Azure OpenAI Realtime with built-in voice)

### `api/v1/` - HTTP + WebSocket APIs
```
api/v1/
├── endpoints/
│   ├── calls.py         # ACS call management
│   ├── media.py         # Media streaming handler
│   ├── realtime.py      # Real-time voice handler
│   └── health.py        # Health checks
└── schemas/             # Pydantic request/response models
```

### `config/` - Configuration
```
config/
├── app_config.py        # Main app settings
├── app_settings.py      # Agent/orchestrator settings
└── feature_flags.py     # Feature toggles
```

## Quick Start

### Run Backend
```bash
make start_backend
```

### Add New Agent
1. Create YAML in `registries/agentstore/`
2. Define prompts, tools, handoffs
3. Restart or call `/api/v1/agents/refresh`

### Add New Tool
```python
# In registries/toolstore/your_tool.py
from apps.artagent.backend.registries.toolstore.registry import register_tool

@register_tool(name="your_tool", description="...")
async def your_tool(param: str) -> dict:
    return {"result": "..."}
```

### Load Scenario
```python
from apps.artagent.backend.registries.scenariostore import load_scenario

scenario = load_scenario("banking_customer_service")
agents = get_scenario_agents("banking_customer_service")
```

## WebSocket Flow

```
1. Client connects → /api/v1/media/stream or /api/v1/realtime/conversation
2. Audio chunks → STT (Azure Speech or Realtime API)
3. Text → Multi-agent orchestrator
4. Response → TTS (Azure Speech or Realtime API)
5. Audio → Stream back to client
```

## Troubleshooting

### Import Errors
Use new paths:
```python
# ✅ Correct
from apps.artagent.backend.registries.agentstore import discover_agents

# ❌ Old (deprecated)
from apps.artagent.backend.agents_store import discover_agents
```

### Agent Not Found
```python
agents = discover_agents()
print([a.name for a in agents])  # List all discovered agents
```

### Tool Not Registered
```python
from apps.artagent.backend.registries.toolstore.registry import list_tools
print(list_tools())  # List all registered tools
```

### Health Check Failed
```bash
curl http://localhost:8000/health
```

Check logs for Azure service connectivity issues (Speech, OpenAI, Redis, CosmosDB).

## Scenario authoring and local authentication

Scenario generation reads its chat deployment from the runtime configuration
provider, after App Configuration has loaded. It must not use an import-time
deployment value: importing the configuration package during bootstrap can happen
before the cloud settings have been synchronized.

If generation fails locally, distinguish these cases:

- **App Configuration returns 401/403:** sign in to the tenant configured by
  `AZURE_TENANT_ID` and confirm that identity can read the configured App
  Configuration store. A successful generic `/health` response does not prove
  model inference access.
- **No chat deployment configured:** check the runtime
  `azure/openai/deployment-id` / `AZURE_OPENAI_CHAT_DEPLOYMENT_ID` setting.
- **Invalid generated draft:** the authoring endpoint gives the model one bounded
  opportunity to repair the validation errors. It never applies an invalid draft
  or silently removes unknown tools or protected context fields.

Generate and review are read-only. Agent/scenario persistence and activation occur
only through the explicit Apply endpoint.

When multiple Azure accounts are used on the same workstation, set
`AZURE_AUTH_SUBSCRIPTION` to the subscription ID (or unique name) associated with
the authorized login. Local App Configuration, OpenAI/Speech/Redis credentials,
and VoiceLive then use that account explicitly, including token refresh, instead
of following later `az account set` changes from another project. This does not
change the CLI's global default or grant access. Hosted managed identity remains
unchanged. Use the project environment (`uv sync`), not an older global Python
environment: subscription-pinned `AzureCliCredential` requires Azure Identity
1.20 or newer.
Resource tenant challenges are checked against `AZURE_TENANT_ID`; a different
tenant is rejected. For a matching challenge, the redundant tenant selector is
omitted because Azure CLI rejects combining `--tenant` and `--subscription`.

### Existing scenario edits and prompt previews

`GET /api/v1/scenario-builder/session/{session_id}?scenario_name=...` reads a
named scenario without activating it. Omitting the name retains the active-scenario
behavior. Scenario updates return the complete editable configuration, including
tools and agent defaults. The session catalog uses saved overrides of built-in
scenarios rather than reverting their displayed settings to the YAML template.

The prompt editor uses a read-only endpoint:

```http
POST /api/v1/agent-builder/prompt-preview?session_id=...
Content-Type: application/json

{
  "agent_name": "BankingConcierge",
  "prompt": "You are {{ agent_name }}. {% if caller_name is defined %}Welcome {{ caller_name }}.{% endif %}",
  "template_vars": {},
  "tools": [],
  "scenario": null,
  "mode": "voicelive"
}
```

Explicit `template_vars`, `tools`, and `scenario` values describe an unsaved draft
for preview only. A null scenario resolves the session's active scenario. Context
precedence matches runtime: base defaults, agent template variables, scenario
globals, scenario agent-default variables, then available runtime values. Cascade
and VoiceLive use shared binding helpers; connection-only VoiceLive values are
marked unavailable when there is no live connection. Tool selections are not
implicitly a Jinja `tools` variable.

Responses include insertable variable paths and expressions, source/type metadata,
safe snapshot values, rendered text, missing-variable paths, warnings, and
diagnostics with line numbers. Ordinary syntax, undefined-value, unsupported
operation, and rendering-limit errors return diagnostics rather than pretending
the original template rendered successfully. Invalid requests and unavailable
context return sanitized HTTP errors without echoing submitted or stored values.

Preview runs against sanitized JSON in a separately bounded Jinja sandbox. It
supports normal conditions, bounded loops, JSON dictionary access, and common
filters, while rejecting imports, private attribute access, arbitrary calls,
recursive macros, and unbounded work. Limits include a 192 KB request, 64 KB UTF-8
prompt, 128 KB context/output, 1,000 loop iterations, and 512 displayed variable
paths. Credentials, verification codes, internal runtime objects, and
credential-like text are omitted or redacted. The endpoint does not persist,
register, activate, invoke a model, or execute tools. Handoff instructions and
conversation recap text appended by runtime are outside this template preview.

### Regional voice discovery

`GET /api/v1/agent-builder/voices` enumerates the configured Speech resource with
the Speech SDK's `get_voices_async()` and returns every discovered voice, including
non-English voices absent from the starter presets. The response includes locale,
gender, voice family, styles, status, resource/region provenance, discovery time,
and completeness/cache flags. It is a catalog query, not a synthesis or VoiceLive
compatibility test.

Discovery runs outside the request event loop and is coalesced per resource.
Successful catalogs are cached for ten minutes, keyed by region, endpoint,
resource ID, and credential fingerprint. `use_cache=false` forces a refresh.
Caller waits are bounded; a timed-out SDK request is shared rather than starting
additional requests. Temporary failures are throttled. A same-resource snapshot
up to one hour old can be returned with a stale warning; otherwise the response
explicitly marks the limited preset fallback as unverified/incomplete.

Optional `category` and `language` filters apply to the discovered catalog, not a
curated allowlist. `total_available` retains the unfiltered count.
`include_unverified=true` preserves the legacy opt-in preset behavior without
contacting Azure. Custom/personal voices and native VoiceLive model voices can
require separate configuration beyond the regional prebuilt Speech catalog.

References: [Speech voice discovery](https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech#get-a-list-of-voices)
and [Voice Live voice/model support](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live).

### MAI transcription and voice configuration

The managed live transcription identifier is `mai-transcribe`. Older stored
`mai-transcribe-1.5` and `mai-transcribe-2` labels normalize to that service alias;
they do not pin the fast-transcription model version.

In VoiceLive, use `session.input_audio_transcription_settings.model` with a managed
text model or an explicit `byom-azure-openai-chat-completion` /
`byom-foundry-anthropic-messages` profile. Native realtime models and
`byom-azure-openai-realtime` are rejected for MAI input. Validation also runs during
handoffs against the actual connection model/profile. MAI connections use API
`2026-04-10`; ordinary existing connections retain their version behavior.
Custom speech maps and phrase lists must be removed explicitly rather than being
silently dropped. There is no undocumented `custom-cascade` profile sent on the
wire; a managed text model already creates a speech/chat/speech pipeline.

In the application's Custom Speech/Cascade mode, set
`speech.transcription_model: mai-transcribe`. The async input provider creates a
session-owned VoiceLive connection using the managed `gpt-4.1` text host and
`create_response: false`. It does not request model responses or synthesize audio:
the normal Cascade LLM and pooled Speech TTS remain in charge. It waits for a
matching `session.updated` acknowledgement before accepting PCM, applies bounded
audio backpressure, preserves final-transcript ordering, and closes on provider
failure instead of substituting another recognizer. This connection never enters
or releases the Speech SDK pool.

Browser PCM defaults to 24 kHz and ACS to 16 kHz, mono PCM16. MAI input rejects
diarization and global Speech phrase biases. Semantic segmentation selects
semantic VAD; a single candidate language becomes a hint and multiple candidates
use explicitly reported automatic detection. Provider changes require reconnecting.

`runtime_transcription_models` on the voice catalog advertises implemented backend
routing, not regional model availability. MAI voice IDs use `voice.type:
azure-standard` and remain intact through VoiceLive requests and Cascade SSML.
The configured Speech resource must separately support the chosen MAI voice.

### Foundry prompt-agent direction

A versioned Foundry **prompt agent**, rather than a hosted voice agent, is a good
fit for making the authoring instructions, model and tool definitions visible.
The current generator remains the direct-model path; no Foundry authoring agent
is provisioned automatically.

The recommended authoring tools are read-only and bound to the calling session
on the server, with no model-supplied session identifier:

| Tool | Purpose |
|------|---------|
| `find_session_agents` | Search the effective registry, including current session overrides. |
| `get_agent_configuration` | Read a selected agent's current configuration, with private values protected. |
| `list_available_tools` | Inspect registered capabilities and current MCP availability. |
| `get_current_scenario` | Read the active scenario and current review draft. |
| `validate_scenario_draft` | Return schema, routing and capability errors without writing state. |

The app must execute these lookups against the latest session cache, return the
tool results to the Foundry agent, and revalidate the final result before review.
Keep Apply and all business-tool execution outside the authoring agent.

Current versioned prompt-agent guidance:
[Create a prompt agent](https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent)
and [function calling](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/function-calling).
Azure AI Projects 1.x is not the versioned prompt-agent SDK; use the documented
2.x SDK or REST contract when implementing this provider.
