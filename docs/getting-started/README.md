# :material-rocket: Getting Started

!!! success "Real-Time Voice AI Accelerator"
    Get your voice agent running with Azure Communication Services, Speech Services, and AI in just a few steps.

---

## :material-check-circle: Prerequisites

### Required Tools

| Tool | Purpose | Install |
|------|---------|---------|
| **Azure CLI** | Resource management | [Install](https://docs.microsoft.com/cli/azure/install-azure-cli) |
| **Azure Developer CLI** | One-command deployment | [Install](https://aka.ms/azd-install) |
| **Python 3.11+** | Backend runtime | [Install](https://www.python.org/downloads/) |
| **Node.js 22+** | Frontend build | [Install](https://nodejs.org/) |
| **Docker** | Container builds | [Install](https://docs.docker.com/get-docker/) |

### Azure Requirements

- **Azure Subscription**: [Create free](https://azure.microsoft.com/free/)
- **Permissions**: Contributor access (ask your admin if unsure)

---

## 🎯 Fastest Path to Running Code

```bash
# 1. Clone & enter the repo
git clone https://github.com/Azure-Samples/art-voice-agent-accelerator.git
cd art-voice-agent-accelerator

# 2. Login to Azure
azd auth login

# 3. Deploy everything (~15 min)
azd up

# 4. Open the frontend URL shown in the output
```

**That's it!** Your voice agent is now running in Azure.

📚 **Detailed guide**: [`infra/README.md`](../../infra/README.md)

---

## 📍 Setup Steps

### Step 1: Infrastructure Deployment
> **Time**: ~15 minutes | **Goal**: Azure resources running

```
azd up
   │
   ├──► Terraform provisions Azure resources
   ├──► Builds & deploys container apps
   └──► Generates .env.local with App Configuration connection
 
OUTPUT: Frontend URL + Backend API + All Azure services
```

[`infra/README.md`](../../infra/README.md) 

---

### Step 2: Local Development Setup
> **Time**: ~5 minutes | **Goal**: Run backend/frontend locally

```
.env.local (auto-generated)
   │
   └──► Points to Azure App Configuration
            │
            └──► Backend fetches all settings at startup
                    • OpenAI endpoints
                    • Speech service config
                    • ACS, Redis, Cosmos settings
```

[Local Development](local-development.md) 

---

### Step 3: Try the Demo
> **Time**: ~5 minutes | **Goal**: Talk to the AI agent

```
Browser Demo                      Phone Demo (optional)
   │                                   │
   └──► Open frontend URL              └──► Call ACS phone number
   └──► Allow microphone               └──► Speak to AI agent
   └──► Start talking
```

 [Demo Guide](demo-guide.md) 

---

### Step 4: Customize & Extend
> **Time**: Ongoing | **Goal**: Build your own voice agent

| Task | Resource |
|------|----------|
| Understand the architecture | [Architecture Overview](../architecture/README.md) |
| Modify agent behavior | [LLM Orchestration](../architecture/llm-orchestration.md) |
| Add custom tools | [`src/tools/`](../../src/tools/) |
| Configure agents | [`apps/artagent/backend/src/agents/`](../../apps/artagent/backend/src/agents/) |

---

## :material-microsoft-azure: What Gets Deployed

| Category | Services | Purpose |
|----------|----------|---------|
| **AI & Voice** | OpenAI (Foundry + Foudnry Project), Speech, VoiceLive, ACS | Voice processing pipeline |
| **Data** | Cosmos DB Mongo vCore, Azure Managed Redis, Blob Storage | State & caching |
| **Compute** | Container Apps, App Configuration | Hosting & config |
| **Monitoring** | App Insights, Log Analytics | Observability |

---

## ❓ Common Questions

??? question "How long does deployment take?"
    **~15 minutes** for complete infrastructure + application deployment via `azd up`.

??? question "What if I already have Azure resources?"
    Skip `azd up` and configure your `.env` file manually. See [Local Development](local-development.md).

??? question "Do I need a phone number?"
    **Only for telephony**. Browser-based voice works without it.

??? question "What regions are supported?"
    East US, West US 2, and most Azure regions with OpenAI availability.
    ??? question "What regions are supported?"
        East US, West US 2, and most Azure regions with OpenAI availability.
        
        **Special considerations:**
        
        - **Cosmos DB for MongoDB (vCore)**: Limited to specific regions. Check [region availability](https://learn.microsoft.com/azure/cosmos-db/mongodb/vcore/introduction#supported-regions).
        - **Azure Managed Redis**: Available in most regions, but verify [Redis region support](https://azure.microsoft.com/explore/global-infrastructure/products-by-region/?products=redis-cache).
        - **VoiceLive API**: Currently in preview with limited regional availability. Confirm service availability in your target region.
        [Speech Services region availability](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions?tabs=voice-live).
        
        **Best practice**: Deploy all resources in the same region to minimize latency for real-time voice applications.

---

## :material-help: Getting Help

| Resource | Use For |
|----------|---------|
| **[Troubleshooting Guide](../operations/troubleshooting.md)** | Common issues & solutions |
| **[GitHub Issues](https://github.com/Azure-Samples/art-voice-agent-accelerator/issues)** | Bug reports |
| **[GitHub Discussions](https://github.com/Azure-Samples/art-voice-agent-accelerator/discussions)** | Questions & community |
