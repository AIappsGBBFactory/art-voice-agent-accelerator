# ⚡ Local Development

Run the ARTVoice Accelerator locally with raw commands. No Makefile usage. Keep secrets out of git and rotate any previously exposed keys.

---

## 1. Scope

What this covers:

- Local backend (FastAPI + Uvicorn) and frontend (Vite/React)
- Dev tunnel for inbound [Azure Communication Services](https://learn.microsoft.com/en-us/azure/communication-services/) callbacks
- Environment setup via venv OR Conda
- Minimal `.env` files (root + frontend)

What this does NOT cover:
- Full infra provisioning
- CI/CD
- Persistence hardening

---

## 2. Prerequisites

| Tool | Notes |
|------|-------|
| Python 3.11 | Required runtime |
| Node.js ≥ 22 | Frontend |
| Azure CLI | `az login` first |
| Dev Tunnels | [Getting Started Guide](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/get-started) |
| (Optional) Conda | If using `environment.yaml` |
| Provisioned Azure resources | For real STT/TTS/LLM/ACS |

If you only want a browser demo (no phone), ACS variables are optional.

---

## 3. Clone Repository

```bash
git clone https://github.com/Azure-Samples/art-voice-agent-accelerator.git
cd art-voice-agent-accelerator
```

---

## 4. Python Environment (Choose One)

### Option A: uv (Recommended)
[uv](https://docs.astral.sh/uv/) is an extremely fast Python package manager (10-100x faster than pip).

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies (creates .venv automatically)
uv sync

# Run commands in the environment
uv run uvicorn apps.artagent.backend.main:app --reload --port 8010
```

### Option B: venv + pip
```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

### Option C: Conda
```bash
conda env create -f environment.yaml
conda activate audioagent
uv sync  # or: pip install -e .[dev]
```

---

## 5. Environment Configuration

This project uses **Azure App Configuration** as the primary configuration source. For local development, you only need a minimal `.env.local` file that points to App Configuration.

### Option A: Recommended — Use App Configuration (after `azd up`)

If you deployed infrastructure using `azd up`, a minimal `.env.local` file was generated automatically:

```bash
# The file should already exist at repo root
cat .env.local
```

**Contents of `.env.local`** (minimal bootstrap):
```bash
# Azure App Configuration (PRIMARY CONFIG SOURCE)
AZURE_APPCONFIG_ENDPOINT=https://<your-appconfig>.azconfig.io
AZURE_APPCONFIG_LABEL=dev

# Azure Identity (for DefaultAzureCredential)
AZURE_TENANT_ID=<your-tenant-id>
```

**How it works:**
1. Backend starts and reads `AZURE_APPCONFIG_ENDPOINT` from `.env.local`
2. Connects to Azure App Configuration using your Azure CLI credentials
3. Fetches all settings (OpenAI, Speech, ACS, Redis, Cosmos, etc.)
4. Loads them into environment variables before the app initializes

!!! success "This is the recommended approach"
    App Configuration provides centralized management, versioning, and feature flags. Local `.env.local` contains only the connection—all actual config lives in Azure.

### Option B: Legacy — Full `.env` file (manual setup)

If you **don't have infrastructure deployed** or need to work offline, create a full `.env` file:

!!! tip "Sample Configuration"
    Use [`.env.sample`](https://github.com/Azure-Samples/art-voice-agent-accelerator/blob/main/.env.sample) as a starting template.

```bash
# Copy the sample file
cp .env.sample .env
# Edit with your values
```

**Required variables for basic functionality:**

```bash
# ===== Azure OpenAI (Required) =====
AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com
AZURE_OPENAI_KEY=<aoai-key>
AZURE_OPENAI_CHAT_DEPLOYMENT_ID=gpt-4o

# ===== Speech (Required) =====
AZURE_SPEECH_REGION=<speech-region>
AZURE_SPEECH_KEY=<speech-key>

# ===== ACS (Optional — only for phone/PSTN) =====
ACS_CONNECTION_STRING=endpoint=https://<your-acs>.communication.azure.com/;accesskey=<acs-key>
ACS_SOURCE_PHONE_NUMBER=+1XXXXXXXXXX
ACS_ENDPOINT=https://<your-acs>.communication.azure.com

# ===== Runtime =====
ENVIRONMENT=dev
BASE_URL=https://<tunnel-url>
```

!!! warning "Legacy Approach"
    Managing a full `.env` file manually is error-prone and harder to keep in sync. Use Option A whenever possible.

### Configuration Precedence

The backend loads configuration in this order (first found wins):

1. **Azure App Configuration** (if `AZURE_APPCONFIG_ENDPOINT` is set)
2. **Environment variables** (from `.env.local`, `.env`, or system)
3. **Default values** (hardcoded in `settings.py`)

---

## 6. Start Dev Tunnel

Required if you want ACS callbacks (phone flow) or remote test:

```bash
devtunnel host -p 8010 --allow-anonymous
```

Copy the printed HTTPS URL and set `BASE_URL` in root `.env`. Update it again if the tunnel restarts (URL changes).

The Dev Tunnel URL will look similar to:
```bash
https://abc123xy-8010.usw3.devtunnels.ms
```

!!! warning "Security Considerations for Operations Teams"
    **Dev Tunnels create public endpoints** that expose your local development environment to the internet. Review the following security guidelines:
    
    - **[Azure Dev Tunnels Security](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/security)** - Comprehensive security guidance
    - **Access Control**: Use `--allow-anonymous` only for development; consider authentication for sensitive environments
    - **Network Policies**: Ensure dev tunnels comply with organizational network security policies
    - **Monitoring**: Dev tunnels should be monitored and logged like any public endpoint
    - **Temporary Usage**: Tunnels are for development only; use proper Azure services for production
    - **Credential Protection**: Never expose production credentials through dev tunnels
    
    **InfoSec Recommendation**: Review tunnel usage with your security team before use in corporate environments.

---

## 7. Run Backend

```bash
cd apps/artagent/backend
uvicorn apps.artagent.backend.main:app --host 0.0.0.0 --port 8010 --reload
```

---

## 8. Frontend Environment

Create or edit `apps/artagent/frontend/.env`:

!!! tip "Sample Configuration"
    Use [`apps/artagent/frontend/.env.sample`](https://github.com/Azure-Samples/art-voice-agent-accelerator/blob/main/apps/artagent/frontend/.env.sample) as a starting template.

Use the dev tunnel URL by default so the frontend (and any external device or ACS-related flows) reaches your backend consistently—even if you open the UI on another machine or need secure HTTPS.

```
# Recommended (works across devices / matches ACS callbacks)
VITE_BACKEND_BASE_URL=https://<tunnel-url>
```

If the tunnel restarts (URL changes), update both `BASE_URL` in the root `.env` and this value.

---

## 9. Run Frontend

```bash
cd apps/artagent/frontend
npm install
npm run dev
```

Open: http://localhost:5173

WebSocket URL is auto-derived by replacing `http/https` with `ws/wss`.

---

## 10. Alternative: VS Code Debugging

**Built-in debugger configurations** are available in [`.vscode/launch.json`](https://github.com/Azure-Samples/art-voice-agent-accelerator/blob/main/.vscode/launch.json):

### Backend Debugging
1. **Set breakpoints** in Python code
2. **Press F5** or go to Run & Debug view
3. **Select "[RT Agent] Python Debugger: FastAPI"**
4. **Debug session starts** with hot reload enabled

### Frontend Debugging  
1. **Start the React dev server** (`npm run dev`)
2. **Press F5** or go to Run & Debug view
3. **Select "[RT Agent] React App: Browser Debug"**
4. **Browser opens** with debugger attached

**Benefits:**
- Set breakpoints in both Python and TypeScript/React code
- Step through code execution
- Inspect variables and call stacks
- Hot reload for both frontend and backend

---

## 11. Alternative: Docker Compose

**For containerized local development**, use the provided [`docker-compose.yml`](https://github.com/Azure-Samples/art-voice-agent-accelerator/blob/main/docker-compose.yml):

```bash
# Ensure .env files are configured (see sections 5 & 8 above)

# Build and run both frontend and backend containers
docker-compose up --build

# Or run in detached mode
docker-compose up --build -d

# View logs
docker-compose logs -f

# Stop containers
docker-compose down
```

**Container Ports:**

- **Frontend**: http://localhost:8080 (containerized)
- **Backend**: http://localhost:8010 (same as manual setup)

**When to use Docker Compose:**

- Consistent environment across team members
- Testing containerized deployment locally
- Isolating dependencies from host system
- Matching production container behavior

!!! note "Dev Tunnel with Docker"
    You still need to run `devtunnel host -p 8010 --allow-anonymous` for ACS callbacks, as the containers need external access for webhook endpoints.

---

## 12. Optional: Phone (PSTN) Flow

1. Purchase ACS phone number (Portal or CLI).

2. Ensure these vars are set in your root `.env` (with real values):

   ```
   ACS_CONNECTION_STRING=endpoint=...
   ACS_SOURCE_PHONE_NUMBER=+1XXXXXXXXXX
   ACS_ENDPOINT=https://<your-acs>.communication.azure.com
   BASE_URL=https://<tunnel-hash>-8010.usw3.devtunnels.ms
   ```

3. Create a single Event Grid subscription for the Incoming Call event pointing to your answer handler:
   - Inbound endpoint:  
     `https://<tunnel-hash>-8010.usw3.devtunnels.ms/api/v1/calls/answer`
   - Event type: `Microsoft.Communication.IncomingCall`
   - (Callbacks endpoint `/api/v1/calls/callbacks` is optional unless you need detailed lifecycle events.)

   If tunnel URL changes, update the subscription (delete & recreate or update endpoint).

   Reference: [Subscribing to events](https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/events/subscribe-to-event)

4. Dial the number; observe:
   - Call connection established
   - Media session events
   - STT transcripts
   - TTS audio frames

---

## 13. Quick Browser Test

1. Backend + frontend running.
2. Open app, allow microphone.
3. Speak → expect:
   - Interim/final transcripts
   - Model response
   - Audio playback

---

## 14. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| 404 on callbacks | Stale `BASE_URL` | Restart tunnel, update `.env` |
| No audio | Speech key/region invalid | Verify Azure Speech resource |
| WS closes fast | Wrong `VITE_BACKEND_BASE_URL` | Use exact backend/tunnel URL |
| Slow first reply | Cold pool warm-up | Keep process running |
| Phone call no events | ACS callback not updated to tunnel | Reconfigure Event Grid subscription |
| Import errors | Missing dependencies | Re-run `uv sync` (or `pip install -e .[dev]`) |

---

## 15. Testing Your Setup

### Quick Unit Tests
Validate your local setup with the comprehensive test suite:

```bash
# Run core component tests
uv run pytest tests/test_acs_media_lifecycle.py -v

# Test event handling and WebSocket integration
uv run pytest tests/test_acs_events_handlers.py -v

# Validate DTMF processing (if using phone features)
uv run pytest tests/test_dtmf_validation.py -v
```

### Load Testing (Advanced)
Validate ACS media relay and real-time conversation paths with the maintained Locust scripts and Make targets:

```bash
# Generate or refresh PCM fixtures shared by both load tests
make generate_audio

# ACS media relay flow (/api/v1/media/stream)
make run_load_test_acs_media HOST=wss://<your-backend-host>

# Real-time conversation flow (/api/v1/realtime/conversation)
make run_load_test_realtime_conversation HOST=wss://<your-backend-host>
```

Adjust concurrency via `USERS`, `SPAWN_RATE`, `TIME`, and pass extra Locust flags with `EXTRA_ARGS='--headless --html report.html'`.

Metrics reported in Locust:
- `ttfb[...]` — time-to-first-byte after the client stops streaming audio.
- `barge_latency[...]` — recovery time after simulated barge-in traffic.
- `turn_complete[...]` — end-to-end latency covering audio send, response, and barge handling.

The targets wrap `tests/load/locustfile.acs_media.py` and `tests/load/locustfile.realtime_conversation.py`. To run them manually:

```bash
locust -f tests/load/locustfile.acs_media.py --host wss://<backend-host> --users 10 --spawn-rate 2 --run-time 5m --headless
locust -f tests/load/locustfile.realtime_conversation.py --host wss://<backend-host> --users 10 --spawn-rate 2 --run-time 5m --headless
```

**What the load tests validate:**

- ✅ **Real-time audio streaming** - 20ms PCM chunks via WebSocket
- ✅ **Multi-turn conversations** - Insurance inquiries and quick questions
- ✅ **Response timing** - TTFB (Time-to-First-Byte) measurement
- ✅ **Barge-in handling** - Response interruption simulation
- ✅ **Connection stability** - Automatic WebSocket reconnection

!!! info "Additional Resources"
    For more comprehensive guidance on development and operations:
    
    - **[Troubleshooting Guide](../operations/troubleshooting.md)** - Detailed problem resolution for common issues
    - **[Testing Guide](../operations/testing.md)** - Comprehensive unit and integration testing (85%+ coverage)
    - **[Load Testing](../operations/load-testing.md)** - WebSocket performance testing and Azure Load Testing integration
    - **[Repository Structure](../guides/repository-structure.md)** - Understand the codebase layout
    - **[Utilities & Services](../guides/utilities.md)** - Core infrastructure components

---

Keep secrets out of commits. Rotate anything that has leaked.