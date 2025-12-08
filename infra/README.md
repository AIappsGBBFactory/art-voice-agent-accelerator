# 🚀 Infrastructure Deployment Guide

> **Goal**: Get your Azure infrastructure deployed in **~15 minutes** with a single command.

---

## 🎯 TL;DR — The Fastest Path

```bash
# 1. Login
azd auth login

# 2. Deploy everything
azd up
```

That's it. The Azure Developer CLI handles infrastructure + app deployment automatically.

---

## 📋 Quick Reference

| What You Want | Command | Time |
|--------------|---------|------|
| **Deploy everything** | `azd up` | ~15 min |
| **Infrastructure only** | `azd provision` | ~12 min |
| **Apps only** (infra exists) | `azd deploy` | ~3 min |
| **Tear down** | `azd down` | ~5 min |
| **Switch environments** | `azd env select <name>` | instant |

---

## 🗺️ Deployment Phases Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DEPLOYMENT JOURNEY                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   PHASE 1                PHASE 2                 PHASE 3                    │
│   ────────               ────────                ────────                   │
│   Prerequisites          Infrastructure          Post-Deploy                │
│   (~5 min)               (~15 min)               (~5 min)                   │
│                                                                             │
│   ┌─────────┐           ┌─────────────┐         ┌───────────────┐           │
│   │ Install │           │   azd up    │         │ Phone Number  │           │
│   │  Tools  │ ────────► │ (automatic) │ ──────► │  (optional)   │           │
│   └─────────┘           └─────────────┘         └───────────────┘           │
│        │                      │                        │                    │
│        ▼                      ▼                        ▼                    │
│   • Azure CLI            • AI Services            • Configure ACS           │
│   • azd CLI              • Data Layer             • Test endpoints          │
│   • Terraform            • Compute                • Start developing!       │
│   • Docker               • Monitoring                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Phase 1: Prerequisites

### Required Tools

| Tool | Install Command | Verify |
|------|----------------|--------|
| **Azure CLI** | [Install Guide](https://docs.microsoft.com/cli/azure/install-azure-cli) | `az --version` |
| **Azure Developer CLI** | [Install Guide](https://aka.ms/azd-install) | `azd version` |
| **Terraform** | Auto-installed by azd | `terraform -v` |
| **Docker** | [Install Guide](https://docs.docker.com/get-docker/) | `docker --version` |

### Quick Install (Linux/WSL)

```bash
# Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Azure Developer CLI
curl -fsSL https://aka.ms/install-azd.sh | bash

# Verify installations
az --version && azd version
```

### Azure Access Check

```bash
# Login to Azure
az login
azd auth login

# Verify you have access
az account show --query "{Name:name, ID:id}" -o table
```

> ⚠️ **Need Permissions?** You need **Contributor** access to create resources. Check with your Azure admin if deployment fails with permission errors.

---

## 🏗️ Phase 2: Deploy Infrastructure

### Option A: One-Command Deployment (Recommended)

```bash
# From the repository root
cd /path/to/art-voice-agent-accelerator

# Deploy everything
azd up
```

**What happens during `azd up`:**

1. **Pre-provisioning** → Configures Terraform state storage
2. **Terraform Apply** → Creates all Azure resources (~12 min)
3. **Container Build** → Builds and pushes Docker images (~2 min)
4. **Post-provisioning** → Generates `.env` files for local dev

### Option B: Step-by-Step Deployment

```bash
# Create and configure environment (interactive prompts)
azd env new dev
# ↑ This will guide you through:
#   • Choosing your Azure subscription
#   • Setting your preferred region (e.g., eastus, westus2)
#   • Configuring any required Terraform parameters

# Provision infrastructure only
# Provision infrastructure only
azd provision
# ↑ This runs:
#   • Pre-provisioning script (Terraform remote state setup)
#   • Terraform Apply (creates all Azure resources)
#   • Post-provisioning script (generates .env.local, optional phone purchase)
#   • Outputs a .env.local with the Azure App Config parameters

# Deploy applications (after infra is ready)azs
azd deploy
```

### What Gets Created

```
┌─────────────────────────────────────────────────────────────────┐
│                   AZURE RESOURCES CREATED                        │
├──────────────────────┬──────────────────────────────────────────┤
│   AI & Voice         │   Azure OpenAI (GPT-4o)                  │
│                      │   Azure AI Speech (STT/TTS)              │
│                      │   Azure VoiceLive (real-time)            │
│                      │   Azure Communication Services           │
├──────────────────────┼──────────────────────────────────────────┤
│   Data & Storage     │   Cosmos DB (MongoDB API)                │
│                      │   Redis Enterprise (caching)             │
│                      │   Blob Storage (audio/media)             │
│                      │   Key Vault (secrets)                    │
├──────────────────────┼──────────────────────────────────────────┤
│   Compute            │   Container Apps (frontend + backend)    │
│                      │   Container Registry                     │
├──────────────────────┼──────────────────────────────────────────┤
│   Configuration      │   ⭐ App Configuration (central config)  │
│                      │   All settings stored centrally          │
├──────────────────────┼──────────────────────────────────────────┤
│   Monitoring         │   Application Insights                   │
│                      │   Log Analytics Workspace                │
└──────────────────────┴──────────────────────────────────────────┘
```

!!! note "Azure App Configuration"
    All configuration (endpoints, keys, feature flags) is stored in **Azure App Configuration**. 
    Local development uses a minimal `.env.local` that points to App Config—no need to manage dozens of environment variables locally.

---

## ✅ Phase 3: Post-Deployment

### 1. Verify Deployment

```bash
# Check deployed resources
azd env get-values

# Test backend health
curl https://<your-backend-url>/api/v1/health
```

### 2. Configure Phone Number (Optional — for telephony)

Phone number is **required only if** you want to make/receive actual phone calls.

```bash
# Option 1: Azure Portal (Recommended)
# Navigate to: ACS Resource → Phone Numbers → Get

# Option 2: Makefile helper
make purchase_acs_phone_number

# Set the number in App Configuration
make set_phone_number PHONE=+18001234567
```

> ⚠️ **Warning**: Repeated programmatic phone purchases may flag your subscription. Use the portal if purchases fail.

### 3. Access Your Application

| Component | URL |
|-----------|-----|
| **Frontend** | Shown in `azd up` output |
| **Backend API** | `<frontend-url>/api/v1/...` |
| **Swagger Docs** | `<backend-url>/docs` |

---

## 💻 Local Development Setup

After infrastructure is deployed, set up local development:

### How Configuration Works

This project uses **Azure App Configuration** as the central configuration store:

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│   .env.local    │ ──►  │  Azure App Config    │ ──►  │   Backend App   │
│  (bootstrap)    │      │  (all settings)      │      │  (loads config) │
└─────────────────┘      └──────────────────────┘      └─────────────────┘
        │                         │
        └── Contains only:        └── Contains:
            • AZURE_APPCONFIG_ENDPOINT    • OpenAI endpoints
            • AZURE_APPCONFIG_LABEL       • Speech settings
            • AZURE_TENANT_ID             • ACS configuration
                                          • Redis, Cosmos, etc.
```

### Quick Setup

```bash
# 1. Verify .env.local was created (generated by azd postprovision)
cat .env.local

# 2. Start the dev tunnel (for ACS callbacks)
devtunnel host -p 8010 --allow-anonymous

# 3. Start backend (fetches config from App Configuration)
uv run uvicorn apps.artagent.backend.main:app --reload --port 8010

# 4. Start frontend (new terminal)
cd apps/artagent/frontend
npm install && npm run dev
```bash
# 1. Verify .env.local was created (generated by azd postprovision)
cat .env.local

# 2. Start the dev tunnel (for ACS callbacks)
devtunnel host -p 8010 --allow-anonymous

# 3. Start backend (fetches config from App Configuration)
uv run uvicorn apps.artagent.backend.main:app --reload --port 8010

# 4. Start frontend (new terminal)
cd apps/artagent/frontend
npm install && npm run dev
```

!!! note "No full `.env` needed"
    The backend automatically fetches all settings from Azure App Configuration at startup. You only need `.env.local` with the App Config connection info.
    
    **Optional**: Reference `.env.sample` to see all available parameters. You only need to create a full `.env` file if you want to override specific App Configuration settings locally during development.

📚 **Full Guide**: See [`docs/getting-started/local-development.md`](../docs/getting-started/local-development.md)

---

## 🔧 Configuration Reference

### Terraform Variable Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Terraform Variable Sources                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   1. infra/terraform/params/         2. azd env set                 │
│      main.tfvars.<env>.json             (stored in .azure/<env>/)   │
│      ─────────────────────              ───────────────────────     │
│      • location                         • TF_VAR_environment_name   │
│      • redis_sku                        • TF_VAR_location           │
│      • cosmosdb_sku                     • TF_VAR_deployed_by        │
│      • openai_location                                              │
│      • (static, per-env)                • (dynamic, runtime)        │
│                                                                     │
│   ──────────────────────────────────────────────────────────────    │
│                            │                                        │
│                            ▼                                        │
│                ┌────────────────────────┐                           │
│                │ .azure/<env>/.env      │                           │
│                │ (azd env storage)      │                           │
│                ├────────────────────────┤                           │
│                │ • AZURE_ENV_NAME       │                           │
│                │ • AZURE_LOCATION       │                           │
│                │ • AZURE_SUBSCRIPTION_ID│                           │
│                │ • TF_VAR_*             │                           │
│                │ • RS_* (state config)  │                           │
│                └────────────────────────┘                           │
│                            │                                        │
│                            ▼                                        │
│                    ┌───────────────┐                                │
│                    │   Terraform   │                                │
│                    │    Apply      │                                │
│                    └───────────────┘                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Static params** (per-environment): Edit `infra/terraform/params/main.tfvars.<env>.json`  
**Dynamic params** (runtime): Set via `azd env set TF_VAR_<name> <value>`

### Environment Variables (azd)

```bash
# View all configured values
azd env get-values

# Set a value
azd env set AZURE_LOCATION "westus2"

# Switch environments
azd env select production
```

### Key Files

| File | Purpose | When to Edit |
|------|---------|--------------|
| `azure.yaml` | azd manifest | Rarely (add new services) |
| `infra/terraform/` | Infrastructure code | Customize resources |
| `infra/terraform/params/` | Per-environment static configs | Change SKUs, locations |
| `.env.local` | App Config bootstrap (minimal) | After `azd up` (auto-generated) |
| `.env.sample` | Full config template | Reference for manual setup |

### Configuration Architecture

| Layer | File/Service | Contents |
|-------|--------------|----------|
| **Bootstrap** | `.env.local` | App Config endpoint + tenant ID only |
| **Central Config** | Azure App Configuration | All settings (OpenAI, Speech, ACS, etc.) |
| **Legacy Fallback** | `.env` (full) | Only if not using App Configuration |

---


## 🔍 Under the Hood: azd Lifecycle

<details>
<summary><strong>Pre-Provisioning Script</strong> (<code>devops/scripts/azd/preprovision.sh</code>)</summary>

Runs **before** Terraform to set up the environment:

1. **CI Tagging** — Retrieves deployer identity from git
2. **Terraform State Storage** — Creates/configures remote state backend
   - `RS_STORAGE_ACCOUNT`: Storage account name
   - `RS_CONTAINER_NAME`: Container name
   - `RS_RESOURCE_GROUP`: Resource group name
   - `RS_STATE_KEY`: State file name (optional)
3. **Terraform Variables** — Sets `TF_VAR_*` via `azd env set`:
   - `TF_VAR_environment_name`: Environment name (e.g., `dev`, `staging`)
   - `TF_VAR_location`: Azure region (e.g., `eastus`)
   - `TF_VAR_deployed_by`: Git identity for resource tagging

**Interactive Prompts:**
- `(y)` — Auto-configure remote state (recommended)
- `(n)` — Use local state (dev only)
- `(c)` — Bring your own storage configuration

> **Note:** Variables are stored in `.azure/<env>/.env` and exported automatically by azd.

</details>

<details>
<summary><strong>Post-Provisioning Script</strong> (<code>devops/scripts/azd/postprovision.sh</code>)</summary>

Runs **after** Terraform to finalize setup:

1. **Creates `.env.local`** — Minimal config with App Configuration connection
2. **Phone Number Purchase** (optional) — Automated ACS number provisioning

</details>

---

## ❓ Troubleshooting

### Common Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `azd up` fails with permissions | Missing Azure roles | Request **Contributor** access |
| Terraform state error | Backend not configured | Say `y` during pre-provision |
| `TF_VAR_*` not set | Pre-provision script failed | Re-run `azd provision` or manually set via `azd env set TF_VAR_location eastus` |
| Container build fails | Docker not running | Start Docker Desktop |
| Phone number purchase fails | Too many attempts or account flagged | Use Azure Portal instead. If portal purchase also fails, open a support ticket—repeated programmatic purchases may flag your subscription as suspicious. |
| Redis connection timeout | SKU not available in region | Try different `AZURE_LOCATION` |
| Backend can't find config | App Configuration not accessible | Check `az login` and `.env.local` |
| `.env.local` missing | Post-provision didn't run | Run `azd provision` again |

### Get Help

```bash
# Check azd logs
azd show

# View App Configuration values
az appconfig kv list --endpoint $(grep AZURE_APPCONFIG_ENDPOINT .env.local | cut -d= -f2) --auth-mode login

# View Terraform state
cd infra/terraform && terraform show

# Check container logs
az containerapp logs show --name <app-name> --resource-group <rg-name> --follow
```

### Reset Everything

```bash
# Destroy all resources and start fresh
azd down --force --purge
azd up
```

---

## 📁 Directory Structure

```
infra/
├── README.md              # ← You are here
├── terraform/             # Terraform configuration (used by azd)
│   ├── main.tf           # Main infrastructure definitions
│   ├── variables.tf      # Variable definitions  
│   ├── outputs.tf        # Output values for azd
│   └── modules/          # Reusable Terraform modules
└── bicep/                # Bicep templates (deprecated)

devops/
└── scripts/
    └── azd/
        ├── preprovision.sh   # Pre-deployment automation
        └── postprovision.sh  # Post-deployment automation
```

---

## 🔗 Related Documentation

| Topic | Link |
|-------|------|
| **Local Development** | [`docs/getting-started/local-development.md`](../docs/getting-started/local-development.md) |
| **Demo Guide** | [`docs/getting-started/demo-guide.md`](../docs/getting-started/demo-guide.md) |
| **Architecture** | [`docs/architecture/README.md`](../docs/architecture/README.md) |
| **Terraform Details** | [`infra/terraform/README.md`](./terraform/README.md) |
| **Phone Setup** | [`docs/deployment/phone-number-setup.md`](../docs/deployment/phone-number-setup.md) |
| **Production Deployment** | [`docs/deployment/production.md`](../docs/deployment/production.md) |

---

## 🆘 Still Stuck?

1. **Check the [Troubleshooting Guide](../docs/operations/troubleshooting.md)** for detailed solutions
2. **Open an issue** on GitHub with your error message
3. **Join the discussion** in GitHub Discussions

---

**Ready to deploy?** Run `azd up` and you're good to go! 🚀
