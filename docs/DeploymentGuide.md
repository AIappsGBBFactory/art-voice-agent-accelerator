
# 🚀 Deployment Guide

> A comprehensive guide to deploy your Real-Time Azure Voice Agentic App with secure SSL and WebSocket connectivity.

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Detailed Deployment Steps](#-detailed-deployment-steps)
    - [1. SSL Certificate Requirements](#1-ssl-certificate-requirements)
    - [2. Environment Configuration](#2-environment-configuration)
    - [3. Infrastructure Provisioning](#3-infrastructure-provisioning)
    - [4. Application Deployment](#4-application-deployment)
    - [5. SSL Certificate and DNS Configuration](#5-ssl-certificate-and-dns-configuration)
    - [6. WebSocket Connectivity Testing](#6-websocket-connectivity-testing)
- [Environment Management](#-environment-management)
- [Certificate Management](#-certificate-management)
- [Monitoring and Troubleshooting](#-monitoring-and-troubleshooting)
- [Cleanup](#-cleanup)
- [Advanced Configuration](#-advanced-configuration)
- [Support](#-support)

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed and configured:

| Tool | Version | Purpose |
|------|---------|---------|
| [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli) | Latest | Azure resource management |
| [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) | Latest | Simplified deployment |
| Node.js | 18+ | Frontend development |
| Python | 3.11+ | Backend development |

**Additional Requirements:**
- ✅ Azure subscription with appropriate permissions
- ✅ **A publicly trusted SSL certificate** for your domain (required for Azure Communication Services WebSocket connections)

> ⚠️ **Important**: Self-signed certificates will not work with Azure Communication Services WebSocket connections.

---

## ⚡ Quick Start

Get up and running in 3 simple steps:

### 1️⃣ Clone and Initialize
```bash
git clone <repository-url>
cd gbb-ai-audio-agent
azd auth login
azd init
```

### 2️⃣ Set Environment Variables
```bash
azd env new <environment-name>
azd env set LOCATION "East US"
azd env set ENVIRONMENT_NAME "<environment-name>"
```

### 3️⃣ Deploy Infrastructure and Code
```bash
azd up
```

---

## 🔧 Detailed Deployment Steps

### 1. SSL Certificate Requirements

> 🔐 **Critical**: Azure Communication Services requires a publicly trusted SSL certificate for WebSocket connections.

#### 📋 Certificate Preparation Checklist

- [ ] **Obtain Certificate**: Purchase from a CA (DigiCert, Let's Encrypt, etc.)
- [ ] **Domain Coverage**: Ensure certificate covers your domain (e.g., `voice-agent.yourdomain.com`)
- [ ] **Format**: Certificate must be in PFX format with password
- [ ] **Trust Chain**: Include full certificate chain for proper validation

#### 🔑 Store Certificate in Key Vault

```bash
# Import certificate to Key Vault
az keyvault certificate import \
    --vault-name kv-voice-agent-prod \
    --name ssl-certificate \
    --file /path/to/your/certificate.pfx \
    --password "your-certificate-password"

# Store certificate password as secret
az keyvault secret set \
    --vault-name kv-voice-agent-prod \
    --name ssl-certificate-password \
    --value "your-certificate-password"

# Configure environment
azd env set AZURE_SSL_KEY_VAULT_SECRET_ID https://kv-voice-agent-prod.vault.azure.net/secrets/ssl-certificate
```

#### 🆔 Configure Managed Identity

```bash
# Create user-assigned managed identity
az identity create \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod

# Get principal ID
IDENTITY_PRINCIPAL_ID=$(az identity show \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod \
        --query principalId -o tsv)

# Grant Key Vault permissions
az keyvault set-policy \
        --name kv-voice-agent-prod \
        --object-id $IDENTITY_PRINCIPAL_ID \
        --certificate-permissions get list \
        --secret-permissions get list

# Set identity for deployment
IDENTITY_RESOURCE_ID=$(az identity show \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod \
        --query id -o tsv)

azd env set AZURE_KEY_VAULT_SECRET_USER_IDENTITY $IDENTITY_RESOURCE_ID
```

### 2. Environment Configuration

Configure your deployment environment with the required parameters:

```bash
# Create production environment
azd env new production

# Set core parameters
azd env set LOCATION "East US"
azd env set RESOURCE_GROUP_NAME "rg-voice-agent-prod"
azd env set PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
azd env set CUSTOM_DOMAIN "voice-agent.yourdomain.com"
```

### 3. Infrastructure Provisioning

Deploy Azure resources using Bicep templates:

| Command | Purpose |
|---------|---------|
| `azd provision` | Deploy infrastructure only |
| `azd deploy` | Deploy code to existing infrastructure |
| `azd up` | Deploy both infrastructure and code |

```bash
# Full deployment (recommended for first deployment)
azd up
```

**📖 Resources Created:**
- Azure Container Apps Environment
- Azure OpenAI Service
- Azure Communication Services
- Redis Cache
- Key Vault
- Application Gateway (with SSL certificate)
- Storage Account
- Cosmos DB
- Private endpoints and networking

> 📚 For detailed infrastructure information, see the [Infrastructure README](../infra/README.md).

### 4. Application Deployment

Deploy your application code to the provisioned infrastructure:

```bash
# Deploy to existing infrastructure
azd deploy
```

### 5. SSL Certificate and DNS Configuration

#### 🌐 Get Application Gateway Public IP

```bash
az network public-ip show \
    --resource-group rg-voice-agent-prod \
    --name pip-appgw-voice-agent \
    --query ipAddress -o tsv
```

#### 📝 Update DNS Records

1. **Go to your DNS provider**
2. **Create/update A record**: `voice-agent.yourdomain.com` → `[Application Gateway IP]`
3. **Wait for DNS propagation** (5-30 minutes)

#### ✅ Verify SSL Certificate

```bash
# Basic health check
curl -I https://voice-agent.yourdomain.com/health

# Check certificate details
openssl s_client -connect voice-agent.yourdomain.com:443 \
    -servername voice-agent.yourdomain.com | \
    openssl x509 -noout -subject -ext subjectAltName

# Verify certificate expiration
openssl s_client -connect voice-agent.yourdomain.com:443 \
    -servername voice-agent.yourdomain.com -showcerts </dev/null 2>/dev/null | \
    openssl x509 -noout -dates
```

**✅ Expected Output:**
- Valid certificate subject matching your domain
- Subject Alternative Names (SAN) including your domain
- Future expiration date

### 6. WebSocket Connectivity Testing

Test WebSocket functionality to ensure real-time communication works:

```bash
# Install wscat
npm install -g wscat

# Test production WebSocket
wscat -c wss://voice-agent.yourdomain.com/ws

# Test local development
wscat -c ws://localhost:8000/ws
```

**✅ Expected Behavior:**
- ✅ Connection establishes successfully
- ✅ Receives connection confirmation message
- ✅ Bidirectional communication works
- ✅ Use `Ctrl+C` to disconnect

**🚨 Troubleshooting WebSocket Issues:**
- Check backend container logs
- Test local backend first
- Verify SSL certificate is trusted
- Ensure DNS is properly configured

---

## 🔄 Environment Management

### Switch Between Environments

```bash
# List all environments
azd env list

# Switch environment
azd env select <environment-name>

# View current variables
azd env get-values
```

### Update Configurations

```bash
# View all environment variables
azd env get-values

# Update domain configuration
azd env set AZURE_DOMAIN_FQDN <your-domain-name>

# Apply changes
azd deploy
```

---

## 🔐 Certificate Management

### 📜 Creating App Service Certificate

For managed certificate creation through Azure Portal:

1. **Navigate to "App Service Certificates"**
2. **Create new certificate** for your domain
3. **Complete domain verification**
4. **Bind certificate** to your application
5. **Configure custom domain** settings

> 📖 **Detailed Guide**: [Secure a custom DNS name with a TLS/SSL binding in Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/tutorial-secure-domain-certificate)

### 🔄 Certificate Updates

```bash
# Import new certificate
az keyvault certificate import \
        --vault-name kv-voice-agent-prod \
        --name ssl-certificate \
        --file /path/to/new/certificate.pfx \
        --password "new-certificate-password"

# Update password secret
az keyvault secret set \
        --vault-name kv-voice-agent-prod \
        --name ssl-certificate-password \
        --value "new-certificate-password"

# Apply changes
azd deploy
```

### 🔗 Full-Chain Certificate Requirements

For third-party certificates (GoDaddy, etc.), create a full-chain bundle:

#### Download Intermediate Bundle

```bash
# GoDaddy G2 bundle
curl -o gd_bundle-g2-g1.crt https://certs.godaddy.com/repository/gd_bundle-g2-g1.crt
```

#### Create Full-Chain PFX

```bash
# Combine certificate with intermediate bundle
cat your-domain.crt gd_bundle-g2-g1.crt > fullchain.crt

# Convert to PFX
openssl pkcs12 -export \
    -out fullchain.pfx \
    -inkey your-domain.key \
    -in fullchain.crt \
    -password pass:your-pfx-password

# Import to Key Vault
az keyvault certificate import \
    --vault-name kv-voice-agent-prod \
    --name ssl-certificate \
    --file fullchain.pfx \
    --password "your-pfx-password"
```

---

## 📊 Monitoring and Troubleshooting

### 🔍 Deployment Monitoring

```bash
# Check deployment status
azd show

# Real-time logs
az containerapp logs show \
    --name ca-voice-agent-backend \
    --resource-group rg-voice-agent-prod \
    --follow

# Recent logs (last 100 lines)
az containerapp logs show \
    --name ca-voice-agent-backend \
    --resource-group rg-voice-agent-prod \
    --tail 100
```

### 🚨 Common Issues & Solutions

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **SSL Not Working** | HTTPS errors, certificate warnings | Verify DNS A record, wait for propagation, check certificate import |
| **WebSocket Fails** | Connection refused, handshake errors | Ensure publicly trusted certificate, test SSL config |
| **Container Won't Start** | App unavailable, startup errors | Check environment variables, verify managed identity permissions |
| **Redis Connection Issues** | Cache errors, timeout issues | Verify private endpoint connectivity, check access keys |

---

## 🧹 Cleanup

Remove all deployed resources:

```bash
# Delete all resources
azd down

# Delete specific environment
azd env delete <environment-name>
```

---

## ⚙️ Advanced Configuration

### 📈 Scaling Configuration

Update container app scaling in `infra/modules/containerapp.bicep`:

```bicep
scale: {
    minReplicas: 1
    maxReplicas: 10
    rules: [
        {
            name: 'http-scaling'
            http: {
                metadata: {
                    concurrentRequests: '100'
                }
            }
        }
    ]
}
```

---

## 🆘 Support

Having deployment issues? Follow this troubleshooting checklist:

1. ✅ **Check Azure Portal** for resource status
2. ✅ **Review container app logs** for error details
3. ✅ **Verify network connectivity** and DNS settings
4. ✅ **Ensure permissions** are properly granted
5. ✅ **Verify SSL certificate** is trusted and properly configured

> 💡 **Pro Tip**: Always test locally first to isolate issues before deploying to Azure.

