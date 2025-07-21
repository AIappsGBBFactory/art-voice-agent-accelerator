# **🚀 Deploying Voice-to-Voice Application Powered by RTAgent**

This README provides technical instructions for deploying, customizing, and running a real-time voice-to-voice demo application built with the RTAgent framework. Refer to the [RTAgent README](../README.md) for full framework details.

### **Application Structure**

```text
apps/
└── rtagent/
  ├── backend/   # FastAPI WebSocket backend for transcription & GPT orchestration
  ├── frontend/  # React + Vite frontend using Azure Speech SDK
  └── scripts/   # Setup and utility scripts
```

### **Extending RTAgent: Framework-Agnostic Agent Customization**

RTAgent is designed to be modular and extensible, allowing teams to tailor the system for domain-specific deployments and intelligent orchestration.

To begin customizing, refer to the following key backend components:

+ `rtagent/backend/src/agents/` – Core agent definitions and logic

- `rtagent/backend/src/agent_store/` – Persistent store for registered agents and metadata

+ `rtagent/backend/src/prompt_store/` – Structured storage for agent-specific prompt templates

- `rtagent/backend/src/tool_store/` – Interface for injecting custom tools, APIs, and capabilities

#### **🔧 Extension Capabilities**

 **🧠 Custom Agents** -> Develop specialized agents such as LegalAgent, HealthcareAgent, or domain-specific copilots.Register them in the agent_store and link them to corresponding prompts in the prompt_store. Define behavior, memory scope, and toolchains specific to their operational goals.

 **🔌 Tool Integration** -> Augment agent capabilities with external APIs, document retrieval functions, or third-party services. Extend the tool_store with domain tools—these tools are automatically exposed to agents through function-calling or tool selection logic.

 **🧬 Memory Enhancements** -> Implement advanced memory mechanisms for long-term user context, dialogue history, and personalized responses. You can plug in vector memory backends (e.g., Redis, ChromaDB) or use custom embeddings to persist semantic interactions across sessions.

 **🧭 Dynamic Routing (LLM and Agent Orchestration)** -> RTAgent supports dynamic routing strategies that can be modified at multiple abstraction layers:

  + **API Dispatching (Low Latency Pathways)** -> Within the router/ module, adjust the FastAPI-based routing logic to handle cost-aware, latency-sensitive decision trees across model backends or endpoint variants.
  - **Agentic Orchestration (Cognitive Planning Layer)** -> Within the orchestrator/ module, you can define custom orchestration flows—using heuristics, scoring functions, or embedding similarity—to route queries between agents. You may also substitute this with your own orchestration stack such as Semantic Kernel, Autogen, or OpenAgents-style architectures for more advanced agent-based collaboration. RTAgent doesn’t lock you into a rigid architecture—it provides a principled starting point for building low-latency, stateful, and tool-augmented conversational agents that can evolve to fit your infrastructure, orchestration strategy, and domain-specific requirements.

## **Before to Start..**

### **Setup Your Development Environment**

- Python 3.11+
- Node.js 18+ (with npm)
- Docker
- Terraform
- Azure CLI (Dev Tunnel extension)

```bash
az extension add --name devtunnel
```
### **Required Azure Services**

- Azure Communication Services  
- Azure Cosmos DB (Mongo vCore)  
- Azure Event Grid  
- Azure Key Vault  
- Azure Managed Redis Enterprise  
- Azure Monitor (Log Analytics / Application Insights)  
- Azure OpenAI  
- Azure Speech Services  
- Azure Storage Account  
- User-Assigned Managed Identities  
- Azure Container Apps & Registry or App Service Plan / Web Apps  

#### **Infrastructure Deployment Options**

Provision the required Azure services before deploying:

1. **Manual Provisioning**  
   Set up each service via the Azure portal.
2. **Automated Provisioning (Recommended)**  
   Use IaC for repeatable deployments:
   - **Terraform:** Provided Terraform scripts  
   - **Azure Developer CLI (azd):** Provided azd scripts  

See the [Infrastructure Deployment Guide](../../docs/DeploymentGuide.md) for detailed steps.

## ⚡ Running the App Locally?

Ensure infrastructure is provisioned before running locally.

### Backend Setup

```bash
git clone https://github.com/your-org/gbb-ai-audio-agent.git
cd gbb-ai-audio-agent/apps/rtagent/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env     # Configure ACS, Speech, and OpenAI credentials
python server.py        # Backend available at ws://localhost:8010/realtime
```

### Frontend Setup

```bash
cd ../../frontend
npm install
npm run dev            # Frontend available at http://localhost:5173
```

Enabling ACS Call-In and “Call Me” Locally feature: 

- Expose the backend via Azure Dev Tunnels. How ? Update `BASE_URL` in both `.env` files, and configure the ACS event subscription. 
- Update the public URL in Azure Communication Services’ event callback.

## Need help getting started? Use the Utility Scripts

| Script                          | Purpose                                  |
| ------------------------------- | ---------------------------------------- |
| scripts/start_backend.py        | Launch backend & verify environment      |
| scripts/start_frontend.sh       | Launch React frontend dev server         |
| scripts/start_devtunnel_host.sh | Open Dev Tunnel & display public URL     |

For advanced customization, see the [RTAgent documentation](../README.md).
