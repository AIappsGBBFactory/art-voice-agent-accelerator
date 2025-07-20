<!-- markdownlint-disable MD033 -->

# **🎙️ RTAgent: Real-Time Voice Intelligence Accelerator**

## **Extensibility and Adaptability**

RTAgent is designed as a base framework that can be extended and adapted to solve domain-specific problems. The modular architecture allows developers to create custom agents and workflows tailored to their unique requirements.

### **How to Extend RTAgent**
1. **Custom Agents**: Add new agents by implementing the standardized agent interface. For example, create a `LegalAgent` or `HealthcareAgent` with domain-specific logic.
2. **Tool Integration**: Extend the tool store with custom functions, external API integrations, or document fetchers.
3. **Memory Enhancements**: Adapt the memory store to include additional context or historical data for personalized interactions.
4. **Dynamic Routing**: Modify the task router to prioritize agents based on cost, complexity, or latency requirements.

### **Folder Structure for Extensions**
The RTAgent project is organized into the following folders:

```
apps/
└─ rtagent/
    ├─ backend/      # FastAPI WebSocket server for real-time transcription and GPT orchestration
    ├─ frontend/     # React + Vite client leveraging Azure Speech SDK for voice interactions
    └─ scripts    # Project documentation and setup instructions
```

Each folder serves a specific purpose to ensure modularity and ease of development. For example:
- **backend/** handles server-side logic, including WebSocket communication and AI orchestration.
- **frontend/** provides the user interface for interacting with the voice agent.
- **README.md** (You are here)

Refer to the folder descriptions above as you navigate the codebase.

## **Getting Started**

### **Prerequisites**

1. Local development tools  
    - Python 3.11+  
    - Node.js 18+ with npm  
    - Docker  
    - Azure Developer CLI (azd)  
    - Terraform  
    - Azure CLI with Dev Tunnels extension  
      ```bash
      az extension add --name devtunnel
      ```

2. Azure subscription & identity  
    - An active Azure subscription
    - The deploying user or service principal must have:  
      - Subscription RBAC roles  
         - Contributor  
         - User Access Administrator  
      - Microsoft Entra ID roles  
         - Application Administrator (needed for app registrations / EasyAuth)  

3. Provision required Infrastructure
    - Clone and review the IaC repo (Terraform or azd):  
      - Audio Agent Deployment (to be merged into the main branch)  
    - Services deployed:  
      1. Azure Communication Services  
      2. Azure Cosmos DB (Mongo vCore)  
      3. Azure Event Grid  
      4. Azure Key Vault  
      5. Azure Managed Redis Enterprise  
      6. Azure Monitor (Log Analytics / Application Insights)  
      7. Azure OpenAI  
      8. Azure Speech Services  
      9. Azure Storage Account  
      10. User-Assigned Managed Identities  
      11. Azure Container Apps & Azure Container Registry  
      12. App Service Plan / Web Apps

A complete IaC walkthrough—including networking, SSL, scalability, and CI/CD—is available in 📄 **[Deployment Guide](../../docs/DeploymentGuide.md)**. Follow it when you are ready to move beyond local development.


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



