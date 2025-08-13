# 🔧 DevOps Scripts for RTVoice Accelerator

This directory contains automation scripts for setting up and managing the Azure deployment pipeline for the RTVoice Accelerator project.

## 🚀 Quick Start - CI/CD Setup

### New to the project? Start here:

```bash
# Setup CI/CD configuration for azd deployment
./setup-gha-config.sh --interactive
```

This will:
1. ✅ Create Azure App Registration for OIDC authentication
2. ✅ Configure GitHub Actions federated credentials
3. ✅ Set up Azure permissions and Terraform state storage
4. ✅ Optionally configure GitHub secrets/variables automatically

## 📁 Script Directory

### 🎯 **CI/CD Setup (Recommended)**
- **[`setup-gha-config.sh`](./setup-gha-config.sh)** - **START HERE** - Complete CI/CD setup for azd deployment

### 🏗️ **Azure Developer CLI (AZD) Helpers**
- **[`azd/`](./azd/)** - AZD lifecycle hooks and helper scripts
  - [`postprovision.sh`](./azd/postprovision.sh) - Post-deployment configuration
  - [`preprovision.sh`](./azd/preprovision.sh) - Pre-deployment setup
  - [`helpers/`](./azd/helpers/) - Utility scripts for AZD workflows

### 🗄️ **Terraform & Infrastructure**
- **[`generate-env-from-terraform.sh`](./generate-env-from-terraform.sh)** - Generate .env from Terraform outputs
- **[`Generate-EnvFromTerraform.ps1`](./Generate-EnvFromTerraform.ps1)** - PowerShell version
- **[`validate-terraform-backend.sh`](./validate-terraform-backend.sh)** - Validate Terraform backend configuration

### 🔗 **Integration & Configuration**
- **[`eventgrid-appconfig.sh`](./eventgrid-appconfig.sh)** - Event Grid integration setup
- **[`EventGrid-AppConfig.ps1`](./eventgrid-appconfig.ps1)** - PowerShell version
- **[`webapp-deploy.sh`](./webapp-deploy.sh)** - Direct webapp deployment

## 📋 Prerequisites

Before running any scripts, ensure you have:

### Required Tools
- **Azure CLI** (`az`) - [Install Guide](https://docs.microsoft.com/cli/azure/install-azure-cli)
- **Azure Developer CLI** (`azd`) - [Install Guide](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- **jq** - JSON processor
- **OpenSSL** - For generating random values

### Optional Tools
- **GitHub CLI** (`gh`) - For automatic secret configuration
- **Terraform** - If using direct Terraform deployment

### Permissions
- **Azure**: Contributor + User Access Administrator on target subscription
- **GitHub**: Admin access to repository for secrets/variables configuration

## 🔐 Authentication Setup

### Azure Authentication
```bash
# Login to Azure
az login

# Set default subscription (if needed)
az account set --subscription "your-subscription-id"
```

### GitHub Authentication (Optional)
```bash
# Login to GitHub CLI (for automatic secret setup)
gh auth login
```

## 🎯 Usage Examples

### Interactive Setup (Recommended for first-time users)
```bash
./setup-gha-config.sh --interactive
```

### Automated Setup with Environment Variables
```bash
export GITHUB_ORG="your-org"
export GITHUB_REPO="your-repo"
export AZURE_LOCATION="eastus"
export AZURE_ENV_NAME="dev"

./setup-gha-config.sh
```

### Production Environment Setup
```bash
AZURE_ENV_NAME=prod AZURE_LOCATION=westus2 ./setup-gha-config.sh
```

## 📤 Output

After running the setup script, you'll get:

### 1. **Azure Resources Created**
- App Registration for OIDC authentication
- Service Principal with proper permissions
- Terraform remote state storage account
- Federated credentials for GitHub Actions

### 2. **GitHub Configuration**
- Repository secrets for Azure authentication
- Repository variables for deployment configuration
- Ready-to-use workflows in `.github/workflows/`

### 3. **Configuration Summary**
- Saved to `.azd-cicd-config.txt` in project root
- Contains all IDs, names, and next steps

## 🔍 Troubleshooting

### Common Issues

**Permission Denied Errors:**
```bash
# Check your Azure permissions
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --output table
```

**GitHub CLI Not Authenticated:**
```bash
# Re-authenticate to GitHub
gh auth login --git-protocol https
```

**Storage Account Access Issues:**
```bash
# Test storage access
az storage container list --account-name YOUR_STORAGE_ACCOUNT --auth-mode login
```

### Debug Mode
```bash
# Run with debug output
bash -x ./setup-gha-config.sh --interactive
```

## 🔄 Updating Configuration

To update existing configuration:

1. **Add new environments**: Run script with `AZURE_ENV_NAME=newenv`
2. **Update permissions**: Re-run the script (it's idempotent)
3. **Rotate credentials**: Delete app registration and re-run

## 📚 Related Documentation

- [GitHub Secrets Configuration Guide](../../.github/SECRETS.md)
- [Azure Developer CLI Deployment](../../docs/AZD-DEPLOYMENT.md)
- [CI/CD Pipeline Guide](../../docs/CICDGuide.md)
- [Microsoft Docs: Container Apps GitHub Actions](https://learn.microsoft.com/azure/container-apps/github-actions-cli)

## 💡 Best Practices

1. **Start with dev environment** - Test thoroughly before production
2. **Use environment-specific configurations** - Separate dev/staging/prod
3. **Review permissions regularly** - Follow principle of least privilege
4. **Monitor deployment logs** - Use Azure Monitor and GitHub Actions logs
5. **Keep secrets up to date** - Rotate credentials periodically

## 🆘 Support

Need help? Check these resources:

1. **Script help**: `./setup-gha-config.sh --help`
2. **Project documentation**: Check `docs/` directory
3. **Azure support**: [Azure Portal Support](https://portal.azure.com/#blade/Microsoft_Azure_Support/HelpAndSupportBlade)
4. **GitHub support**: [GitHub Actions documentation](https://docs.github.com/actions)

---

**Happy Deploying! 🚀**
