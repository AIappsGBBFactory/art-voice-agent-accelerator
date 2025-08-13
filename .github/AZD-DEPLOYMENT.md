# 🚀 Azure Developer CLI Deployment Guide

This guide explains how to use the simplified Azure Developer CLI (azd) approach for deploying your Real-Time Audio Agent application.

## 🎯 Why Azure Developer CLI?

The Azure Developer CLI provides several advantages over raw Terraform commands:

### ✅ **Simplified Deployment**
- **Single Command**: `azd up` provisions infrastructure and deploys applications
- **Integrated Lifecycle**: Handles the complete deployment lifecycle
- **Configuration Management**: Built-in environment and secret management

### ✅ **Better Developer Experience**
- **Consistent Interface**: Same commands across different projects
- **Rich Output**: Better deployment progress and status information
- **Error Handling**: More informative error messages and recovery guidance

### ✅ **CI/CD Friendly**
- **Non-Interactive Mode**: `--no-prompt` flag for automation
- **Environment Variables**: Easy configuration through env vars
- **Status Reporting**: Better integration with GitHub Actions

## 📁 Workflow Files

### 🚀 Main Deployment Workflow
**File:** [`deploy-azd.yml`](./deploy-azd.yml)

**Features:**
- ✅ Uses Azure Developer CLI for all operations
- ✅ Supports multiple actions: `provision`, `deploy`, `up`, `down`
- ✅ Environment-specific deployments
- ✅ Terraform backend configuration
- ✅ Pull request previews

**Triggers:**
- Manual dispatch with environment and action selection
- Push to main branch (auto-deploy to dev)
- Pull requests (plan preview)
- Called by other workflows

### 🎯 Complete Deployment Pipeline
**File:** [`deploy-azd-complete.yml`](./deploy-azd-complete.yml)

Simplified orchestration workflow for complete deployments with summary reporting.

## 🚀 Quick Start

### 1. Configure GitHub Secrets
Set up the same secrets as described in [SECRETS.md](./SECRETS.md):

```bash
# Azure Authentication (OIDC)
AZURE_CLIENT_ID=12345678-1234-1234-1234-123456789012
AZURE_TENANT_ID=87654321-4321-4321-4321-210987654321
AZURE_SUBSCRIPTION_ID=11111111-2222-3333-4444-555555555555

# Terraform State Storage
TF_STATE_RESOURCE_GROUP=rg-terraform-state-prod
TF_STATE_STORAGE_ACCOUNT=tfstateprod12345
TF_STATE_CONTAINER_NAME=tfstate

# Application Configuration
AZURE_PRINCIPAL_ID=98765432-8765-8765-8765-876543210987
ACS_SOURCE_PHONE_NUMBER=+12345678901
```

### 2. Deploy Everything
```bash
# Option 1: Use GitHub Actions UI
# Navigate to Actions → "🚀 Deploy with Azure Developer CLI"
# Select environment: dev/staging/prod
# Select action: up (for complete deployment)

# Option 2: Use Complete Pipeline
# Navigate to Actions → "🎯 Complete Deployment with AZD"
# Select environment and action
```

### 3. Available Actions

| Action | Description | Use Case |
|--------|-------------|----------|
| `provision` | Infrastructure only | Initial setup, infrastructure changes |
| `deploy` | Application only | Code updates, configuration changes |
| `up` | Both infrastructure and application | Complete deployment, new environments |
| `down` | Destroy everything | Environment cleanup, cost savings |

## 🔄 Deployment Comparison

### Before: Raw Terraform
```yaml
- name: Terraform Init
  run: terraform init
  
- name: Terraform Plan
  run: terraform plan -out=tfplan
  
- name: Terraform Apply
  run: terraform apply tfplan
  
- name: Build Container Images
  run: docker build -t myapp .
  
- name: Push to Registry
  run: docker push myapp
  
- name: Deploy to Container Apps
  run: az containerapp update --image myapp
```

### After: Azure Developer CLI
```yaml
- name: Setup AZD
  uses: Azure/setup-azd@v1.0.0
  
- name: Deploy Everything
  run: azd up --no-prompt
```

## 🌍 Environment Management

### Development (`dev`)
```bash
# Automatic deployment on push to main
azd up --no-prompt

# Manual deployment
azd deploy rtaudio-server --no-prompt
```

### Staging (`staging`)
```bash
# Manual deployment with approval
azd up --environment staging --no-prompt
```

### Production (`prod`)
```bash
# Manual deployment with protection rules
azd up --environment prod --no-prompt
```

## 🔧 Local Development with AZD

### Setup Local Environment
```bash
# Clone repository
git clone <repository-url>
cd gbb-ai-audio-agent-migration-target

# Install Azure Developer CLI
curl -fsSL https://aka.ms/install-azd.sh | bash

# Login to Azure
azd auth login

# Initialize environment
azd env new dev
azd env set AZURE_LOCATION eastus
azd env set AZURE_SUBSCRIPTION_ID <your-subscription-id>

# Deploy
azd up
```

### Development Workflow
```bash
# Make code changes
# ...

# Deploy just the application
azd deploy

# Or deploy everything
azd up

# Monitor deployment
azd monitor

# View logs
azd monitor --logs

# Clean up
azd down --force --purge
```

## 📊 Monitoring and Management

### Deployment Status
```bash
# Check deployment status
azd show

# Get environment values
azd env get-values

# List all environments
azd env list
```

### Resource Management
```bash
# Monitor application
azd monitor

# View logs
azd monitor --logs

# Get service endpoints
azd show --output json | jq '.services'
```

### Troubleshooting
```bash
# Verbose output
azd up --debug

# Force refresh
azd provision --force

# Check Azure resources
az resource list --resource-group <resource-group>
```

## 🔐 Security Features

### OIDC Authentication
- Same federated credentials as before
- No client secrets in workflows
- Short-lived tokens

### Environment Isolation
- Separate azd environments per stage
- Environment-specific configurations
- Resource group isolation

### Secret Management
- Azure Key Vault integration via azd
- Environment variable management
- Secure configuration handling

## 🚀 Migration from Raw Terraform

### Step 1: Update Workflows
Replace the existing `deploy-infrastructure.yml` and `deploy-application.yml` with the new AZD-based workflows.

### Step 2: Test Deployment
```bash
# Test in development environment
azd up --environment dev

# Verify deployment
azd show
azd monitor
```

### Step 3: Update Documentation
Update any deployment documentation to reference the new AZD workflows.

### Step 4: Clean Up
Remove the old workflow files once AZD deployment is validated.

## 📈 Benefits Realized

### ✅ **Simplified Workflows**
- Reduced from ~300 lines to ~200 lines
- Single command for complete deployment
- Better error handling and reporting

### ✅ **Improved Reliability**
- Built-in retry logic
- Better state management
- Consistent deployment process

### ✅ **Enhanced Developer Experience**
- Faster deployments
- Better progress reporting
- Easier troubleshooting

### ✅ **Better Maintainability**
- Fewer workflow files to maintain
- Standardized deployment process
- Easier to extend and customize

## 🆘 Troubleshooting

### Common Issues

**AZD Not Found:**
```bash
# Install Azure Developer CLI
curl -fsSL https://aka.ms/install-azd.sh | bash
```

**Authentication Issues:**
```bash
# Check authentication status
azd auth status

# Re-authenticate
azd auth login
```

**Environment Issues:**
```bash
# List environments
azd env list

# Create new environment
azd env new <name>

# Set required variables
azd env set AZURE_LOCATION eastus
```

**Deployment Failures:**
```bash
# Enable debug output
azd up --debug

# Check Azure portal for resources
# Review deployment logs in GitHub Actions
```

### Getting Help
- 📖 [Azure Developer CLI Documentation](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/)
- 🐛 [GitHub Issues](https://github.com/Azure/azure-dev/issues)
- 💬 [Community Discussions](https://github.com/Azure/azure-dev/discussions)

---

## 🎯 Next Steps

1. **Test AZD Deployment**: Use the new workflows in a development environment
2. **Validate Functionality**: Ensure all services deploy and function correctly
3. **Update Documentation**: Update any references to the old deployment process
4. **Train Team**: Share the new deployment process with your team
5. **Monitor**: Set up monitoring and alerting for the new deployment process

The Azure Developer CLI approach provides a much cleaner, more maintainable, and more reliable deployment process while leveraging the same underlying Terraform infrastructure you've already defined. 🚀
