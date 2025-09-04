<!-- markdownlint-disable MD033 MD041 -->

# 🎙️ **ARTVoice Accelerator Framework**  

* TLDR; *An frameowrk to aclcleertate your jjoutbe to budil Vpice agentsm in adinel stack, hyepe scale and onmichahenent, yes taht mean telehepeny also via Azure concicni serviice*

In anothiser;, clear spepatayaon of cocnecnt doent he top layete leeheeh evvrhainAure concocny lateht, with an optitntotn depleoeyemnt patetrn  to the mdidlled e sclalabaiaoltty but with all the flelccyie tofo to own you AI agent ancjene as your suuecase reididuowrte And clelalru ont eh "sfmalssu Stutucied arhciehetc evs voci -toc coie dirieictey

1 - Full contorl anc fotoruanualtyor event needes as local deplpeete whehre you wnt ot an ever letate fo the AI ifneinfvicie ienfiene paispue STT -> LLM _TTS whats is so colaleb stucjehd atchoeueete 
2 - Buidldiduin with latetst AzureAI serciie vOide leive APi a amangeged vovie leayte hatconenct to azur eAI agent fofucntity forirnrn tool and cpaaiaaiit aout of the box as 
3 - Buid your latets gpt-relelat flahaosgs mdole form open ai in anovvi toto cocide layeyr

The frmmaeor ahas bebe dndeofoih to mbe mdoeuela and leocu to aodp tot oyur nend sbit wiht wnad end to end veieie toptipciie you the oputon you ennd to bdudk you Aicicosu layye jssttascj and also a veir ot integrtaaion. 

We use FatsAPI and manage websosbekests, but you can decidied what prorpuoci to use. again is proocodoe. 
We procidie you with teh code to kepe leiebeiebe on oyu ACS, we absctatrctted teh code fo ejays prruryrirn whrh totu wnebsbee via biridieirotion strmeiana  afutiiee tahtpricoode you the cpabailit to connect you abncknend and vodil AS 

**ARTAgent** is an accelerator that delivers a friction-free, AI-driven voice experience—whether callers dial a phone number, speak to an IVR, or click “Call Me” in a web app. Providie a moduelas satch ehre there are Built entirely on generally available Azure services—Azure Communication Services, Azure AI, and Azure App Service—it provides a low-latency stack that scales on demand while keeping the AI layer fully under your control.

Design a single agent or orchestrate multiple specialist agents (claims intake, authorization triage, appointment scheduling—anything). 

## **Overview** 

<img src="utils/images/RTAGENT.png" align="right" height="180" alt="ARTAgent Logo" />

> **88 %** of customers still make a **phone call** when they need real support  
> — yet most IVRs feel like 1999. **ARTAgent** fixes that.

**ARTAgent in a nutshell**

RT Agent is a plug-and-play accelerator, voice-to-voice AI pipeline that slots into any phone line, web client, or CCaaS flow. Caller audio arrives through Azure Communication Services (ACS), is transcribed by a dedicated STT component, routed through your agent chain of LLMs, tool calls, and business logic, then re-synthesised by a TTS component—all in a sub-second round-trip. Because each stage runs as an independent microservice, you can swap models, fine-tune latency budgets, or inject custom logic without touching the rest of the stack. The result is natural, real-time conversation with precision control over every hop of the call.

<img src="utils/images/RTAgentArch.png" alt="ARTAgent Logo" />

<br>

| What you get | How it helps |
|--------------|--------------|
| **Sub-second loop** (STT → LLM/Tools → TTS) | Conversations feel human, not robotic latency-ridden dialogs. |
| **100 % GA Azure stack** | No private previews, no hidden SKUs—easy procurement & support. |
| **Drop-in YAML agents** | Spin up FNOL claims bots, triage nurses, or legal intake in minutes. |
| **Micro-service architecture** | Swap models, tune latency, or add new business logic without redeploying the whole stack. |

## Deploy and Customize the Demo App Using the ARTAgent Framework

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

### 🎯 **Quick Reference: Common Commands**

```bash
# Full deployment 
export ARM_SUBSCRIPTION_ID="your-subscription-id"
cd infra/terraform 
terraform init
terraform apply 
cd ../.. 

# Environment management
make generate_env_from_terraform    # Extract config from Terraform
make update_env_with_secrets        # Add Key Vault secrets  
make show_env_file                  # View current environment

# Deploy applications  
make deploy_backend                 # Deploy FastAPI backend
make deploy_frontend                # Deploy Vite/React frontend

# Monitor deployments (enhanced with timeout handling)
make monitor_backend_deployment     # Backend deployment status
make monitor_frontend_deployment    # Frontend deployment status  

# ACS phone setup
make purchase_acs_phone_number      # Purchase phone number

# Get help
make help                           # Show all available targets
```

**💡 Pro Tips:**
- Large frontend deployments may timeout after 15 minutes but continue in background
- Use monitoring commands to check deployment progress  
- Install 'Azure App Service' VS Code extension for easy log streaming
- All sensitive values are automatically stored in Azure Key Vault

**Project Structure Highlights:**

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


**Prerequisites:** 
- Infra deployed (above)
- Python 3.11 
- Node.js ≥ 22
- Azure CLI
- [Azure Dev Tunnels](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/get-started?tabs=windows)


**Backend (FastAPI + Uvicorn):**
```bash
git clone https://github.com/your-org/gbb-ai-audio-agent.git
cd gbb-ai-audio-agent/rtagents/ARTAgent/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make generate_env_from_terraform  # Generate .env from Terraform outputs
cp .env.<env name> .env   # Configure ACS, Speech, and OpenAI keys

devtunnel host -p 8010 --allow-anonymous  # Start dev tunnel for local testing
make start_backend
```

> 💡 **Having issues?** Check the [troubleshooting guide](docs/Troubleshooting.md) for common setup problems and solutions.

**Frontend (Vite + React):**
```bash
make start_frontend
```

## **Deployment on Azure**

### 🚀 **Quick Start (Recommended)**

The fastest way to deploy ARTAgent is using Azure Developer CLI:

```bash
azd auth login
azd up         # Complete infra + code deployment (~15 min)
```

### 🛠️ **Alternative Deployment: Terraform + Makefile**

For environments where `azd` is not available or when you need more infrastructure control, use our streamlined Terraform + Makefile approach:

#### **Prerequisites**
- Azure CLI installed and authenticated (`az login`)
- Terraform installed
- Make utility available

#### **Step-by-Step Deployment**

##### 1. **Environment Setup**
```bash
# Set your Azure subscription ID
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export AZURE_ENV_NAME="dev"  # Optional: defaults to 'dev'

# Configure Terraform variables
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Edit terraform.tfvars with your subscription and region preferences
```

##### 2. **Infrastructure Deployment**
```bash
cd infra/terraform
terraform init
terraform apply
cd ../..  # Return to repo root
```

##### 3. **Environment Configuration**
```bash
# Generate .env file from Terraform outputs and Key Vault secrets
make generate_env_from_terraform
make update_env_with_secrets
```
##### 4. **Application Deployment**
```bash
# Deploy both backend and frontend apps to Azure App Service
make deploy_backend
make deploy_frontend
```

> **⚠️ IMPORTANT:**  
> **Don't forget to purchase your ACS phone number and update configuration:**
> **YOUR BACKEND WILL NOT WORK WITHOUT THIS NUMBER**
> - For **local development**, purchase the number and add it to your `.env` file as `ACS_SOURCE_PHONE_NUMBER`.
> - For **Azure App Service deployments**, update `acs_source_phone_number` in your `terraform.tfvars` and re-run `terraform apply` to propagate the change.
> - Alternatively, you can set the ACS phone number manually using the Azure CLI if needed.

##### 5. **REQUIRED: Phone Number Setup**
```bash
# Purchase an ACS phone number for voice calls via Python script
make purchase_acs_phone_number
```

> To purchase a number via the Azure Portal:
> https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/telephony/get-phone-number?tabs=windows&pivots=platform-azcli"

> ⚠️ **Phone number issues?** If you encounter problems with ACS calling or phone number setup, see the [ACS troubleshooting section](docs/Troubleshooting.md#acs-azure-communication-services-issues) for detailed solutions.

#### **🎯 One-Command Full Deployment**

Once your environment variables are set, you can deploy everything with:

```bash
# Complete end-to-end deployment
cd infra/terraform && terraform apply && cd ../.. && \
make generate_env_from_terraform && \
make update_env_with_secrets && \
make deploy_backend && \
make deploy_frontend
```

#### **📊 Deployment Monitoring**

Our enhanced Makefile includes comprehensive deployment monitoring:

```bash
# Monitor any deployment in progress
make monitor_deployment WEBAPP_NAME=<app-name>

# Monitor specific apps using Terraform outputs
make monitor_backend_deployment
make monitor_frontend_deployment
```

**Deployment Timeouts:** Large deployments may take 10-15 minutes. If you see timeout messages, the deployment continues in the background. Use the monitoring commands above to check status.

#### **🔧 Available Make Targets**

**Quick Reference:**
```bash
make help                          # Show all available targets

# Environment Management
make generate_env_from_terraform   # Extract config from Terraform
make update_env_with_secrets      # Add Key Vault secrets
make show_env_file               # Display current environment

# Application Deployment  
make deploy_backend              # Deploy FastAPI backend
make deploy_frontend             # Deploy Vite/React frontend
make monitor_backend_deployment  # Monitor backend deployment
make monitor_frontend_deployment # Monitor frontend deployment

# ACS Phone Numbers
make purchase_acs_phone_number   # Purchase phone number
```

#### **🪟 Windows Support**

Windows users can use PowerShell equivalents:

```powershell
# Set environment variables
$env:ARM_SUBSCRIPTION_ID = "<your-subscription-id>"
$env:AZURE_ENV_NAME = "dev"

# Use PowerShell-specific targets
make generate_env_from_terraform_ps
make update_env_with_secrets_ps
make purchase_acs_phone_number_ps
```

#### **🚨 Troubleshooting**

**Common Issues:**

- **Timeout Errors:** Large frontend builds (Vite) take 5-15 minutes. Use `make monitor_frontend_deployment` to check status.
- **Azure CLI Auth:** Run `az login` and `az account set --subscription "<subscription-id>"`
- **Key Vault Access:** Ensure your user has Key Vault Secrets User role
- **VS Code Integration:** Install 'Azure App Service' extension for easy log streaming

**Getting Help:**
- Run `make help` for all available commands
- Use monitoring targets to check deployment progress
- View deployment logs in Azure Portal or VS Code
- **📖 For detailed troubleshooting steps, see [`docs/Troubleshooting.md`](docs/Troubleshooting.md)**

#### **✨ Benefits of This Approach**

- **🎯 Simplified:** Streamlined commands with intelligent defaults
- **📊 Monitoring:** Built-in deployment monitoring and error handling  
- **🔒 Secure:** Uses Azure Key Vault for all sensitive values
- **⚡ Fast:** Optimized deployment artifacts with timeout handling
- **🖥️ Cross-Platform:** Works on Windows, macOS, and Linux
- **🔄 Resumable:** Failed deployments can be easily retried

## **📚 Documentation**

### **🌟 Beautiful API Documentation**

We've created comprehensive, beautiful documentation using MkDocs Material that automatically generates from our enhanced docstrings:

**🌐 [View Live Documentation](https://pablosalvador10.github.io/gbb-ai-audio-agent/)**

### **📖 What's Included**

- **🚀 Quick Start Guide:** Get up and running in minutes
- **📋 Complete API Reference:** Auto-generated from docstrings with examples
- **🏗️ Architecture Overview:** System design and component relationships  
- **🔧 Configuration Guide:** Detailed setup and deployment options
- **💡 Examples & Tutorials:** Real-world usage patterns
- **🔍 Troubleshooting:** Common issues and solutions

### **🛠️ Local Documentation Development**

Build and serve documentation locally:

```bash
# Linux/macOS
chmod +x serve-docs.sh
./serve-docs.sh

# Windows
serve-docs.bat
```

This will:
1. Install documentation dependencies
2. Build the site with mkdocstrings
3. Start a local server at `http://127.0.0.1:8000`
4. Auto-reload when you make changes

### **📝 Documentation Features**

- **📱 Responsive Design:** Beautiful on desktop and mobile
- **🔍 Full-Text Search:** Find anything instantly
- **🎨 Syntax Highlighting:** Code examples with copy buttons
- **🔗 Cross-References:** Navigate between related components
- **📊 Interactive Examples:** Live code samples you can modify

### **🤖 Auto-Generated API Docs**

Our documentation automatically includes:

#### SpeechSynthesizer
- Complete method documentation with examples
- Parameter descriptions and types
- Return value specifications
- Error handling patterns
- Performance considerations

#### StreamingSpeechRecognizer  
- Real-time recognition capabilities
- Callback system documentation
- Language detection features
- Session management patterns

#### Utility Functions
- Text processing helpers
- SSML generation tools
- Authentication utilities

### **📚 Additional Resources**

| Resource | Description |
|----------|-------------|
| [Architecture Guide](docs/Architecture.md) | System design and data flow |
| [Azure Integration](docs/AzureIntegration.md) | Service dependencies and configuration |
| [Troubleshooting](docs/Troubleshooting.md) | Common issues and solutions |
| [Load Testing](docs/LoadTesting.md) | Performance testing guides |

### **🔄 Documentation Deployment**

Documentation automatically deploys to GitHub Pages when you push to `main`:

1. **GitHub Actions** builds the site from your docstrings
2. **mkdocstrings** extracts API documentation  
3. **GitHub Pages** hosts the beautiful site
4. **Auto-updates** whenever code changes

## **Load & Chaos Testing**
Worried about the solution’s ability to scale under your application’s load? Here’s a guide to help you with horizontal scaling tests...


Targets: **<500 ms STT→TTS • 1k+ concurrent calls • >99.5 % success** (WIP)

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