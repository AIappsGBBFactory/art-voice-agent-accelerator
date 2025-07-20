<!-- markdownlint-disable MD033 MD041 -->

# 🎙️ **RTAgent**  
*Omni-channel, real-time voice-intelligence accelerator framework on Azure*

**RTAgent** is an accelerator that delivers a friction-free, AI-driven voice experience—whether callers dial a phone number, speak to an IVR, or click “Call Me” in a web app. Built entirely on generally available Azure services—Azure Communication Services, Azure AI, and Azure App Service—it provides a low-latency stack that scales on demand while keeping the AI layer fully under your control.

Design a single agent or orchestrate multiple specialist agents (claims intake, authorization triage, appointment scheduling—anything). The framework allows you to build your voice agent from scratch, incorporate long- and short-term memory, configure actions, and fine-tune your TTS and STT layers to give any workflow an intelligent voice.

## **Overview** 

<img src="utils/images/RTAGENT.png" align="right" height="180" alt="RTAgent Logo" />

> **88 %** of customers still make a **phone call** when they need real support  
> — yet most IVRs feel like 1999. **RTAgent** fixes that.

**RTAgent in a nutshell**

RT Agent is a plug-and-play accelerator, voice-to-voice AI pipeline that slots into any phone line, web client, or CCaaS flow. Caller audio arrives through Azure Communication Services (ACS), is transcribed by a dedicated STT component, routed through your agent chain of LLMs, tool calls, and business logic, then re-synthesised by a TTS component—all in a sub-second round-trip. Because each stage runs as an independent microservice, you can swap models, fine-tune latency budgets, or inject custom logic without touching the rest of the stack. The result is natural, real-time conversation with precision control over every hop of the call.

<img src="utils/images/RTAgentArch.png" alt="RTAgent Logo" />

<br>

| What you get | How it helps |
|--------------|--------------|
| **Sub-second loop** (STT → LLM/Tools → TTS) | Conversations feel human, not robotic latency-ridden dialogs. |
| **100 % GA Azure stack** | No private previews, no hidden SKUs—easy procurement & support. |
| **Drop-in YAML agents** | Spin up FNOL claims bots, triage nurses, or legal intake in minutes. |
| **Micro-service architecture** | Swap models, tune latency, or add new business logic without redeploying the whole stack. |

## Getting Started

### **🚀 One-Command Azure Deployment**

Provision the full solution—including App Gateway, Container Apps, Cosmos DB, Redis, OpenAI, and Key Vault—with a single command:

```bash
azd auth login
azd up   # ~15 min for complete infra and code deployment
```

**Key Features:**
- TLS managed by Key Vault and App Gateway
- KEDA auto-scales RT Agent workers
- All outbound calls remain within a private VNet

For a detailed deployment walkthrough, see [`docs/DeploymentGuide.md`](docs/DeploymentGuide.md).

**Directory Highlights:**

| Path                | Description                                 |
|---------------------|---------------------------------------------|
| apps/rtagent/backend| FastAPI + WebSocket voice pipeline          |
| apps/rtagent/frontend| Vite + React demo client                   |
| apps/rtagent/scripts| Helper launchers (backend, frontend, tunnel)|
| infra/              | Bicep/Terraform IaC                        |
| docs/               | Architecture, agents, tuning guides         |
| tests/              | Pytest suite                               |
| Makefile            | One-line dev commands                       |
| environment.yaml    | Conda environment spec (name: audioagent)   |

### *⚡ Rapid Local Run*

**Prerequisites:** Infra deployed (above), Conda, Node.js ≥ 18, Azure CLI with `dev-tunnel` extension.

**Backend (FastAPI + Uvicorn):**
```bash
git clone https://github.com/your-org/gbb-ai-audio-agent.git
cd gbb-ai-audio-agent/rtagents/RTAgent/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env   # Configure ACS, Speech, and OpenAI keys
python server.py      # Starts backend at ws://localhost:8010/realtime
```

**Frontend (Vite + React):**
```bash
cd ../../frontend
npm install
npm run dev           # Starts frontend at http://localhost:5173
```
To enable phone dial-in, expose the backend using Azure Dev Tunnels, update `BASE_URL` in both `.env` files, and configure the ACS event subscription.

**You can also run these scripts in the terminal to automate the above:**

| Script                | Purpose                                           |
|-----------------------|---------------------------------------------------|
| apps/rtagents/scripts/start_backend.py      | Launches FastAPI pipeline, sets PYTHONPATH, checks env |
| apps/rtagents/scripts/start_frontend.sh     | Runs Vite dev server at port 5173                   |
| apps/rtagents/scripts/start_devtunnel_host.sh| Opens Azure Dev Tunnel on port 8010, prints public URL |

Copy the public URL from the dev tunnel into Azure Communication Services → Event Callback URL to enable real phone dial-in within minutes. 

## **Load and Chaos Testing**

**Performance Targets:**
- <500 ms STT→TTS
- 1,000+ concurrent calls
- >99.5% success rate (in progress)

```bash
az load test run --test-plan tests/load/azure-load-test.yaml
```

Additional load test scripts (Locust, Artillery) are available in [`docs/LoadTesting.md`](docs/LoadTesting.md).

## **Roadmap**
- Live Agent API integration
- Multi-modal agents (documents, images)

## **Contributing**
PRs & issues welcome—see `CONTRIBUTING.md` and run `make pre-commit` before pushing.

## **License & Disclaimer**
Released under MIT. This sample is **not** an official Microsoft product—validate compliance (HIPAA, PCI, GDPR, etc.) before production use.

<br>

> [!IMPORTANT]  
> This software is provided for demonstration purposes only. It is not intended to be relied upon for any production workload. The creators of this software make no representations or warranties of any kind, express or implied, about the completeness, accuracy, reliability, suitability, or availability of the software or related content. Any reliance placed on such information is strictly at your own risk.