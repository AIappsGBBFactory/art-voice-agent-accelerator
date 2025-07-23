# Environment Generation Scripts

This directory contains scripts for generating environment files from Terraform remote state.

## Scripts

### Bash Script: `generate-env-from-terraform.sh`

Cross-platform bash script that works on macOS, Linux, and Windows (with WSL or Git Bash).

**Usage:**
```bash
# Generate environment file
./devops/scripts/generate-env-from-terraform.sh [environment_name] [subscription_id] [action]

# Examples
./devops/scripts/generate-env-from-terraform.sh dev
./devops/scripts/generate-env-from-terraform.sh prod $AZURE_SUBSCRIPTION_ID
./devops/scripts/generate-env-from-terraform.sh dev $AZURE_SUBSCRIPTION_ID update-secrets
```

**Actions:**
- `generate` - Generate .env file from Terraform state (default)
- `update-secrets` - Update .env file with Key Vault secrets  
- `show` - Show current .env file information

### PowerShell Script: `Generate-EnvFromTerraform.ps1`

Native PowerShell script for Windows environments.

**Usage:**
```powershell
# Generate environment file
.\devops\scripts\Generate-EnvFromTerraform.ps1 [-EnvironmentName <string>] [-SubscriptionId <string>] [-Action <string>]

# Examples
.\devops\scripts\Generate-EnvFromTerraform.ps1 -EnvironmentName dev
.\devops\scripts\Generate-EnvFromTerraform.ps1 -EnvironmentName prod -SubscriptionId $env:AZURE_SUBSCRIPTION_ID
.\devops\scripts\Generate-EnvFromTerraform.ps1 -Action update-secrets
```

**Parameters:**
- `-EnvironmentName` - Environment name (default: dev)
- `-SubscriptionId` - Azure subscription ID (auto-detected if not provided)
- `-Action` - Action to perform: generate, update-secrets, show (default: generate)

## Makefile Integration

Both scripts are integrated into the Makefile for easy access:

**Bash (recommended for macOS/Linux):**
```bash
make generate_env_from_terraform
make show_env_file
make update_env_with_secrets
```

**PowerShell (for Windows):**
```bash
make generate_env_from_terraform_ps
make show_env_file_ps
make update_env_with_secrets_ps
```

## Requirements

- Terraform CLI installed and configured
- Azure CLI installed and authenticated (`az login`)
- Terraform state properly initialized with remote backend
- Appropriate permissions to read from Key Vault (for secret updates)

## Environment Variables

The scripts use these environment variables with fallback defaults:

- `AZURE_ENV_NAME` - Environment name (default: "dev")
- `AZURE_SUBSCRIPTION_ID` - Azure subscription ID (auto-detected from Azure CLI)

## Generated Environment File

The scripts generate a `.env.{environment}` file with the following sections:

- Application Insights Configuration
- Azure OpenAI Configuration  
- Azure Speech Services Configuration
- Base URL Configuration
- Azure Communication Services Configuration
- Redis Configuration
- Azure Storage Configuration
- Azure Cosmos DB Configuration
- Azure Identity Configuration
- Azure Resource Configuration
- Application Configuration
- Logging Configuration

## Security Notes

- Sensitive values (keys, connection strings) are initially empty
- Use the `update-secrets` action to populate from Azure Key Vault
- Never commit environment files containing secrets to version control
- Consider using `.env.*` in your `.gitignore` file
