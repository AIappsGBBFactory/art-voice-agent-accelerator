# **ARTVoice Infrastructure**

Infrastructure as Code for deploying ARTVoice Accelerator on Azure using Terraform.

## **Quick Start**

```bash
# Authenticate and deploy everything
azd auth login
azd up
```

That's it! The Azure Developer CLI handles infrastructure provisioning and application deployment in ~15 minutes.

---

## **Deployment Details**

### Prerequisites

- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Terraform](https://www.terraform.io/downloads) (installed automatically by azd)
- Azure subscription with Contributor access

### What Gets Deployed

```
AI & Communication
├── Azure OpenAI (GPT-4o)           # Conversational AI
├── Azure AI Speech                 # STT/TTS processing
├── Azure VoiceLive                 # Real-time voice orchestration
└── Azure Communication Services    # Voice/messaging platform

Data & Storage
├── Cosmos DB (MongoDB API)         # Session and user data
├── Redis Enterprise                # High-performance caching
├── Blob Storage                    # Audio/media files
└── Key Vault                       # Secrets management

Compute & Configuration
├── Container Apps                  # Serverless hosting (frontend + backend)
├── Container Registry              # Docker image storage
├── App Configuration               # Centralized configuration management
├── Application Insights            # Monitoring/telemetry
└── Log Analytics                   # Centralized logging
```

---

## **Post-Deployment Configuration**

### Set ACS Phone Number

After deployment, you need to configure an Azure Communication Services phone number:

```bash
# Option 1: Purchase via Azure Portal (recommended)
# Navigate to your ACS resource → Phone numbers → Get

# Option 2: Use the Makefile helper
make purchase_acs_phone_number

# Then set it in App Configuration
make set_phone_number PHONE=+18001234567
```

### View Configuration

```bash
# Show all App Configuration values
make show_appconfig

# Show ACS-specific configuration
make show_appconfig_acs

# Trigger configuration refresh for running apps
make refresh_appconfig
```

---

## **Environment Management**

### azd Commands

```bash
# Deploy everything (infrastructure + apps)
azd up

# Deploy only infrastructure
azd provision

# Deploy only applications
azd deploy

# Destroy all resources
azd down

# View environment variables
azd env get-values

# Switch environments
azd env select <env-name>
```

### Local Development

For local development, the backend reads configuration from Azure App Configuration:

```bash
# Start backend locally
make start_backend

# Start frontend locally  
make start_frontend

# Start dev tunnel for ACS webhooks
make start_tunnel
```

---

## **Monitoring & Troubleshooting**

```bash
# View container app logs
az containerapp logs show --name <app-name> --resource-group <rg-name> --follow

# Check azd deployment outputs
azd env get-values

# Test Redis connection
make test_redis_connection
```

---

## **Directory Structure**

```
infra/
├── terraform/              # Terraform configuration (used by azd)
│   ├── main.tf            # Main infrastructure definitions
│   ├── variables.tf       # Variable definitions
│   ├── outputs.tf         # Output values for azd
│   └── params/            # Environment-specific parameters
│       ├── main.tfvars.dev.json
│       └── main.tfvars.staging.json
└── bicep/                  # Bicep templates (deprecated, not maintained)
```

---

## **Additional Resources**

- [Terraform Configuration Details](terraform/README.md)
- [Architecture Overview](../docs/architecture/README.md)
- [Getting Started Guide](../docs/getting-started/)

---

**🚀 Ready to deploy? Run `azd up` and you're good to go!**
