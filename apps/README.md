# Real-Time Voice Agent Application

Voice agent application built with ARTAgent framework for Azure Communication Services.

## Structure

```
apps/rtagent/
├── backend/     # FastAPI backend with multi-agent orchestration
├── frontend/    # React frontend with Azure Speech SDK
└── scripts/     # Setup and deployment utilities
```

## Architecture

**Real-time voice application** with intelligent agent routing:
- **Frontend** - Browser-based voice interface using Azure Speech SDK
- **Backend** - FastAPI WebSocket server with multi-agent orchestration
- **Agents** - AuthAgent → FNOLIntakeAgent/GeneralInfoAgent workflow

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Azure services provisioned (see Infrastructure section)

### 1. Backend Setup
```bash
cd apps/rtagent/backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env  # Configure Azure credentials
python main.py
```

### 2. Frontend Setup
```bash
cd apps/rtagent/frontend
npm install
npm run dev
```

### 3. Access Application
- **Frontend**: http://localhost:5173
- **Backend**: ws://localhost:8010
- **API Docs**: http://localhost:8010/docs

## Configuration

### Environment Variables
Configure `.env` files in both backend and frontend:

**Backend** (`backend/.env`):
```bash
AZURE_OPENAI_ENDPOINT=your-endpoint
AZURE_SPEECH_KEY=your-key
ACS_CONNECTION_STRING=your-connection-string
```

**Frontend** (`frontend/.env`):
```bash
VITE_BACKEND_URL=ws://localhost:8010
VITE_SPEECH_KEY=your-speech-key
```

## Infrastructure Requirements

### Azure Services
- **Azure Communication Services** - Phone calling and media streaming
- **Azure Speech Services** - STT/TTS processing
- **Azure OpenAI** - GPT model for agent responses
- **Azure Redis** - Session and conversation state
- **Azure Cosmos DB** - Persistent data storage
- **Azure Storage** - Audio recording storage

### Deployment Options
1. **Terraform** - Use `infra/terraform/` for automated provisioning
2. **Azure Developer CLI** - Use `azd up` for quick deployment
3. **Manual** - Configure services via Azure Portal

See [Deployment Guide](../../docs/DeploymentGuide.md) for detailed steps.

## Development

### Adding Agents
1. Create YAML config in `backend/src/agents/agent_store/`
2. Add prompt template in `backend/src/agents/prompt_store/`
3. Register in orchestration system

### Modifying Voice Settings
Edit `backend/config/voice_config.py` for TTS voices and speech recognition.

### Feature Toggles
Edit `backend/config/feature_flags.py` to enable/disable features.

## Production Deployment

### Local Development with Azure Integration
Use Azure Dev Tunnels for ACS callback integration:

```bash
cd scripts/
./start_devtunnel_host.sh  # Exposes backend publicly
```

Update `BASE_URL` in environment variables with the tunnel URL.

### Container Deployment
```bash
docker build -t voice-agent-backend ./backend
docker build -t voice-agent-frontend ./frontend
```

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/start_backend.py` | Launch backend with environment validation |
| `scripts/start_frontend.sh` | Launch React development server |
| `scripts/start_devtunnel_host.sh` | Create Azure Dev Tunnel for ACS integration |

## Agent Workflow

```
1. User calls → ACS → WebSocket connection
2. AuthAgent validates caller identity
3. Intent routing: Claims → FNOLIntakeAgent, General → GeneralInfoAgent
4. Agent processes with approved tools
5. Response generation via Azure OpenAI
6. TTS conversion and audio streaming
```

## Extending the System

### Custom Agents
- Create domain-specific agents (LegalAgent, HealthcareAgent)
- Define agent behavior in YAML configuration
- Link to specialized prompt templates and tools

### Tool Integration
- Add external APIs and services to `backend/src/agents/tool_store/`
- Tools automatically available to agents via function calling

### Memory Enhancement
- Implement custom memory backends
- Add vector storage for semantic search
- Extend conversation persistence

For advanced customization, see the [ARTAgent Framework Documentation](../README.md).
