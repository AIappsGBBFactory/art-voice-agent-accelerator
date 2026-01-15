# Infrastructure Resources

This document provides a comprehensive list of all Azure resources deployed by the ART Voice Agent Accelerator, along with documentation links for configuring private networking on each resource.

---

## 📋 Resource Overview

The following resources are automatically deployed when you run `azd up`:

### AI & Voice Services

| Resource | Purpose | Private Networking Documentation |
|----------|---------|----------------------------------|
| **Azure OpenAI (AI Foundry)** | GPT-4o model deployments for conversational AI | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks) |
| **Azure AI Speech Services** | Speech-to-Text (STT) and Text-to-Speech (TTS) | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-private-link) |
| **Azure VoiceLive (AI Foundry)** | Real-time voice-to-voice with gpt-4o-realtime (optional, based on region availability) | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks) |
| **Azure Communication Services** | Call Automation and Media Streaming for telephony | [Configure Private Link](https://learn.microsoft.com/en-us/azure/communication-services/concepts/networking/private-link) |
| **Azure Email Communication Service** | Email domain management (managed domain) | Part of ACS private networking |

---

### Data & Storage Services

| Resource | Purpose | Private Networking Documentation |
|----------|---------|----------------------------------|
| **Cosmos DB (MongoDB API)** | Persistent storage for conversation history and agent state | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-configure-private-endpoints) |
| **Azure Cache for Redis (Enterprise)** | In-memory caching for session state and low-latency data access | [Configure Private Link](https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-private-link) |
| **Azure Storage Account** | Blob storage for audio recordings, prompts, and media files | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/storage/common/storage-private-endpoints) |
| **Azure Key Vault** | Secure storage for secrets, connection strings, and API keys | [Configure Private Link](https://learn.microsoft.com/en-us/azure/key-vault/general/private-link-service) |
| **Azure App Configuration** | Centralized configuration management for all application settings | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/azure-app-configuration/concept-private-endpoint) |

---

### Compute & Hosting Services

| Resource | Purpose | Private Networking Documentation |
|----------|---------|----------------------------------|
| **Azure Container Apps** | Hosts the FastAPI backend and React frontend applications | [VNet Integration](https://learn.microsoft.com/en-us/azure/container-apps/vnet-custom) |
| **Container Apps Environment** | Shared environment for container apps with logging integration | [Workload Profiles in VNets](https://learn.microsoft.com/en-us/azure/container-apps/workload-profiles-overview) |
| **Azure Container Registry** | Private Docker image repository for application containers | [Configure Private Link](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-private-link) |

---

### Monitoring & Configuration Services

| Resource | Purpose | Private Networking Documentation |
|----------|---------|----------------------------------|
| **Application Insights** | Distributed tracing, telemetry, and performance monitoring | [Private Link Scope](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/private-link-security) |
| **Log Analytics Workspace** | Centralized log aggregation and query engine | [Private Link Scope](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/private-link-security) |
| **Event Grid System Topic** | Event subscription for ACS incoming call notifications | [Configure Private Endpoints](https://learn.microsoft.com/en-us/azure/event-grid/configure-private-endpoints) |

---

### Identity & Access Management

| Resource | Purpose | Private Networking Documentation |
|----------|---------|----------------------------------|
| **User-Assigned Managed Identity (Backend)** | Identity for backend container app to access Azure resources | N/A - Uses Microsoft Entra ID endpoints |
| **User-Assigned Managed Identity (Frontend)** | Identity for frontend container app to access Azure resources | N/A - Uses Microsoft Entra ID endpoints |

---

## 🔐 Production Private Networking Architecture

For production deployments, all services should be placed behind private endpoints within a Virtual Network (VNet). The recommended architecture includes:

```
Internet → Application Gateway (WAF) → Container Apps (VNet integrated)
                                        ↓
                          Private Endpoints (all Azure services)
```

### Key Benefits:
- **Security**: No public internet exposure for data and AI services
- **Compliance**: Meet regulatory requirements for data isolation
- **Performance**: Lower latency through Azure backbone network
- **Cost**: Reduced data egress charges

### Implementation Guide:

For detailed guidance on implementing a fully private network architecture, see:
- [Production Deployment Guide](production.md#network-perimeter)
- [Azure Well-Architected Framework - Networking](https://learn.microsoft.com/en-us/azure/well-architected/networking/)
- [Hub-and-Spoke Network Topology](https://learn.microsoft.com/en-us/azure/architecture/networking/architecture/hub-spoke)

---

## 📊 Resource Groups & Naming Conventions

All resources are deployed into a single resource group with consistent naming:

```
Resource Group: rg-{environment_name}-{resource_token}
Example: rg-dev-abc123xyz
```

Individual resources follow this pattern:
```
{service-prefix}-{name}-{resource_token}
```

---

## 🔍 Finding Your Resources

After deployment, you can find all resources in the Azure Portal:

1. Navigate to the resource group shown in `azd env get-values | grep AZURE_RESOURCE_GROUP`
2. Or use Azure CLI:
   ```bash
   az resource list --resource-group <your-resource-group> --output table
   ```

---

## 📚 Additional Resources

- [Infrastructure Overview](../../infra/README.md) - Terraform configuration details
- [Quick Start Guide](../getting-started/quickstart.md) - Deploy infrastructure in 15 minutes
- [Production Deployment](production.md) - Security hardening and best practices
- [Troubleshooting](../operations/troubleshooting.md) - Common deployment issues

---

## 💡 Cost Considerations

The deployed infrastructure uses consumption-based and low-tier SKUs by default to minimize costs during development. For production workloads, consider:

- Upgrading to higher SKUs for better performance and SLA
- Enabling reserved capacity for predictable workloads
- Implementing auto-scaling policies
- See [Cost Optimization](production.md#cost-optimization) for detailed strategies
