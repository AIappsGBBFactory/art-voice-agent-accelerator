# Real-Time Voice Agent Backend

FastAPI backend for Azure Communication Services voice agent with multi-agent orchestration.

## Structure

```
backend/
├── main.py              # FastAPI app entry point
├── api/                 # HTTP REST endpoints
├── config/              # Configuration management
└── src/                 # Core application logic
```

## Core Components

### **`main.py`**
FastAPI application factory with WebSocket and HTTP endpoints. Initializes agent orchestration, connection pooling, and Azure services.

### **`api/`** - REST API Layer
HTTP endpoints for call management and system health.

```
api/
├── v1/                  # API versioning
│   ├── calls.py         # ACS call initiation/management
│   ├── health.py        # Health check endpoints  
│   └── websocket.py     # WebSocket connection handler
└── swagger_docs.py      # OpenAPI documentation
```

### **`config/`** - Configuration Management
Environment-based configuration separated by functionality for easy modification.

```
config/
├── infrastructure.py    # Azure services, secrets, endpoints
├── voice_config.py      # TTS/STT and speech settings
├── connection_config.py # WebSocket limits, session management
├── feature_flags.py     # Feature toggles, monitoring
├── ai_config.py         # Agent configs, model parameters
└── security_config.py   # CORS, authentication paths
```

### **`src/`** - Core Application Logic

#### **Agent System**
```
src/agents/              # YAML-driven agent framework
├── base.py              # ARTAgent class for agent creation
├── agent_store/         # Agent YAML configurations
├── prompt_store/        # Jinja prompt templates
└── tool_store/          # Agent tool registry
```

#### **Orchestration Engine**
```
src/orchestration/       # Multi-agent routing and coordination
├── orchestrator.py      # Main routing entry point
├── agent_registry.py    # Agent registration system
├── agent_handlers.py    # Auth, claims, general agent handlers
├── greeting_manager.py  # Agent handoff management
└── gpt_flow.py          # GPT response processing
```

#### **Core Services**
```
src/services/            # External service integrations
├── speech/              # Azure Speech STT/TTS
├── aoai/                # Azure OpenAI integration
├── pools/               # Connection pooling
└── acs/                 # Azure Communication Services
```

#### **Session & State Management**
```
src/sessions/            # WebSocket session lifecycle
├── stateful/            # Memory and conversation state
└── ws_helpers/          # WebSocket utilities
```

#### **Supporting Components**
```
src/handlers/            # Event and message handlers
src/utils/               # Shared utilities and helpers
```

## Key Features

- **Multi-Agent Orchestration** - AuthAgent → FNOLIntakeAgent/GeneralInfoAgent routing
- **Azure Integration** - ACS, Speech Services, OpenAI native integration
- **Connection Pooling** - Optimized for 100-200 concurrent connections
- **Session Management** - Persistent conversation state with Redis
- **Real-time Audio** - Low-latency WebSocket streaming
- **Production Ready** - Comprehensive logging, tracing, health checks

## Development

### **Adding an Agent**
1. Create YAML config in `src/agents/agent_store/`
2. Add handler in `src/orchestration/agent_handlers.py`
3. Register in `src/orchestration/orchestrator.py`

### **Modifying Voice Settings**
Edit `config/voice_config.py` for TTS voices and speech recognition settings.

### **Adjusting Connection Limits**
Edit `config/connection_config.py` for WebSocket and session management.

### **Feature Toggles**
Edit `config/feature_flags.py` for enabling/disabling features.

## Architecture Flow

```
WebSocket → API → Orchestrator → Agent → Tools → Response → TTS → Client
```

1. **WebSocket Connection** - Client connects via `/api/v1/media/stream`
2. **Authentication** - AuthAgent validates caller identity
3. **Intent Routing** - Based on conversation, route to specialist agent
4. **Tool Execution** - Agent uses approved tools for responses
5. **Response Generation** - Azure OpenAI generates contextual response
6. **Speech Synthesis** - Azure Speech converts to audio
7. **Real-time Streaming** - Audio streamed back to client
