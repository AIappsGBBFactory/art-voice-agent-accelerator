# 🔐 GitHub Actions Secrets Configuration Guide

This guide explains how to configure GitHub repository secrets for automated deployment of your Real-Time Audio Agent application.

## 📋 Required Secrets

### 🏗️ Azure Authentication (OIDC) - **RECOMMENDED**

For secure, password-less authentication using OpenID Connect:

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `AZURE_CLIENT_ID` | Azure App Registration Client ID | `12345678-1234-1234-1234-123456789012` |
| `AZURE_TENANT_ID` | Azure Active Directory Tenant ID | `87654321-4321-4321-4321-210987654321` |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID | `11111111-2222-3333-4444-555555555555` |

### 🗄️ Terraform Remote State Configuration

Configure these repository variables for Terraform backend state storage:

| Variable Name | Type | Description | Example Value |
|---------------|------|-------------|---------------|
| `RS_RESOURCE_GROUP` | Repository Variable | Resource group containing state storage | `rg-terraform-state-prod` |
| `RS_STORAGE_ACCOUNT` | Repository Variable | Storage account for Terraform state | `tfstateprod12345` |
| `RS_CONTAINER_NAME` | Repository Variable | Blob container for state files | `tfstate` |
| `AZURE_LOCATION` | Repository Variable | Azure region for deployments | `eastus` |
| `AZURE_ENV_NAME` | Repository Variable | Environment name for deployments | `dev` |

### 🔧 Application Configuration

| Secret Name | Description | Required | Example Value |
|-------------|-------------|----------|---------------|
| `AZURE_PRINCIPAL_ID` | Service Principal Object ID for RBAC | Yes | `98765432-8765-8765-8765-876543210987` |
| `ACS_SOURCE_PHONE_NUMBER` | Azure Communication Services phone number | Optional* | `+12345678901` |

\* *If not provided, will attempt auto-provisioning or skip phone configuration*

---

## 🚀 Setup Instructions

### Step 1: Create Azure App Registration for OIDC

```bash
# Create the App Registration
az ad app create --display-name "GitHub-Actions-RTAudio-OIDC"

# Get the Application (Client) ID
APP_ID=$(az ad app list --display-name "GitHub-Actions-RTAudio-OIDC" --query "[0].appId" -o tsv)
echo "AZURE_CLIENT_ID: $APP_ID"

# Get your Tenant ID
TENANT_ID=$(az account show --query "tenantId" -o tsv)
echo "AZURE_TENANT_ID: $TENANT_ID"

# Get your Subscription ID
SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
echo "AZURE_SUBSCRIPTION_ID: $SUBSCRIPTION_ID"

# Create Service Principal
az ad sp create --id $APP_ID

# Get Service Principal Object ID (for AZURE_PRINCIPAL_ID)
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query "id" -o tsv)
echo "AZURE_PRINCIPAL_ID: $SP_OBJECT_ID"
```

### Step 2: Configure OIDC Federated Credentials

```bash
# Replace with your GitHub repository details
GITHUB_ORG="your-org"
GITHUB_REPO="your-repo"

# Create federated credential for main branch
az ad app federated-credential create \
    --id $APP_ID \
    --parameters '{
        "name": "main-branch",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:'$GITHUB_ORG'/'$GITHUB_REPO':ref:refs/heads/main",
        "description": "Main branch deployments",
        "audiences": ["api://AzureADTokenExchange"]
    }'

# Create federated credential for pull requests
az ad app federated-credential create \
    --id $APP_ID \
    --parameters '{
        "name": "pull-requests",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:'$GITHUB_ORG'/'$GITHUB_REPO':pull_request",
        "description": "Pull request validation",
        "audiences": ["api://AzureADTokenExchange"]
    }'

# Create federated credential for manual workflows
az ad app federated-credential create \
    --id $APP_ID \
    --parameters '{
        "name": "workflow-dispatch",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:'$GITHUB_ORG'/'$GITHUB_REPO':environment:dev",
        "description": "Manual workflow triggers",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

### Step 3: Assign Azure Permissions

```bash
# Assign Contributor role for resource management
az role assignment create \
    --assignee $SP_OBJECT_ID \
    --role "Contributor" \
    --scope "/subscriptions/$SUBSCRIPTION_ID"

# Assign User Access Administrator for RBAC management (needed for Terraform)
az role assignment create \
    --assignee $SP_OBJECT_ID \
    --role "User Access Administrator" \
    --scope "/subscriptions/$SUBSCRIPTION_ID"
```

### Step 4: Create Terraform State Storage

```bash
# Create resource group for Terraform state
az group create \
    --name "rg-terraform-state-prod" \
    --location "eastus"

# Create storage account for Terraform state
STORAGE_ACCOUNT="tfstateprod$(openssl rand -hex 4)"
az storage account create \
    --name $STORAGE_ACCOUNT \
    --resource-group "rg-terraform-state-prod" \
    --location "eastus" \
    --sku "Standard_LRS" \
    --encryption-services blob

# Create container for state files
az storage container create \
    --name "tfstate" \
    --account-name $STORAGE_ACCOUNT \
    --auth-mode login

echo "RS_STORAGE_ACCOUNT: $STORAGE_ACCOUNT"
```

### Step 5: Configure GitHub Repository Secrets and Variables

Navigate to your GitHub repository → Settings → Secrets and variables → Actions

#### Repository Secrets
Add these secrets under "Repository secrets":
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`  
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_PRINCIPAL_ID`
- `ACS_SOURCE_PHONE_NUMBER` (optional)

#### Repository Variables  
Add these variables under "Repository variables":
- `RS_RESOURCE_GROUP`
- `RS_STORAGE_ACCOUNT`
- `RS_CONTAINER_NAME`
- `AZURE_LOCATION`
- `AZURE_ENV_NAME`

---

## 🌍 Environment-Specific Configuration

### Development Environment
- No additional secrets required
- Uses default configurations

### Staging Environment
Create environment-specific secrets in GitHub:
- Go to Settings → Environments → Create "staging"
- Add environment-specific secrets if needed

### Production Environment
Create environment-specific secrets in GitHub:
- Go to Settings → Environments → Create "prod"
- Add production-specific secrets
- Enable protection rules (require reviewers, etc.)

---

## 🔍 Validation

Test your configuration:

```bash
# Test Azure CLI authentication
az login --service-principal \
    --username $APP_ID \
    --password $SP_SECRET \
    --tenant $TENANT_ID

# Verify permissions
az account show
az group list --query "[].name" -o table
```

---

## 🚨 Security Best Practices

1. **Use OIDC**: Preferred over client secrets for enhanced security
2. **Least Privilege**: Only assign necessary permissions
3. **Environment Protection**: Use GitHub environment protection rules for production
4. **Secret Rotation**: Regularly rotate any client secrets (if used)
5. **Audit**: Monitor deployment logs and Azure activity logs

---

## 🆘 Troubleshooting

### Common Issues

**Permission Denied Errors:**
```bash
# Verify role assignments
az role assignment list --assignee $SP_OBJECT_ID --output table
```

**Terraform State Access Issues:**
```bash
# Verify storage account permissions
az storage container show \
    --name "tfstate" \
    --account-name $STORAGE_ACCOUNT \
    --auth-mode login
```

**OIDC Authentication Failures:**
- Verify federated credentials are correctly configured
- Check repository name and organization match exactly
- Ensure environment names match between GitHub and workflow

---

## 📞 Support

For additional help:
- Review workflow logs in GitHub Actions
- Check Azure Activity Log for permission issues
- Consult Azure documentation for OIDC configuration
