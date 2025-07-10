#!/bin/bash

# ============================================================================
# AZURE REAL-TIME AUDIO AGENT - TERRAFORM DEPLOYMENT SCRIPT
# ============================================================================

set -e

echo "🚀 Starting Azure Real-Time Audio Agent Terraform Deployment"

# Check if Azure CLI is installed and user is logged in
if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI is not installed. Please install it first."
    exit 1
fi

# Check if user is logged in
if ! az account show &> /dev/null; then
    echo "❌ Not logged into Azure. Please run 'az login' first."
    exit 1
fi

# Check if Terraform is installed
if ! command -v terraform &> /dev/null; then
    echo "❌ Terraform is not installed. Please install it first."
    exit 1
fi

# Get current user information
CURRENT_USER=$(az ad signed-in-user show --query id -o tsv)
CURRENT_ACCOUNT=$(az account show --query name -o tsv)

echo "✅ Azure CLI and Terraform are available"
echo "👤 Current user: $(az ad signed-in-user show --query displayName -o tsv)"
echo "📋 Current subscription: $CURRENT_ACCOUNT"

# Prompt for environment configuration if terraform.tfvars doesn't exist
if [ ! -f "terraform.tfvars" ]; then
    echo ""
    echo "📝 Creating terraform.tfvars file..."
    
    read -p "Environment name (default: dev): " ENV_NAME
    ENV_NAME=${ENV_NAME:-dev}
    
    read -p "Application name (default: rtaudioagent): " APP_NAME
    APP_NAME=${APP_NAME:-rtaudioagent}
    
    read -p "Azure region (default: eastus): " LOCATION
    LOCATION=${LOCATION:-eastus}
    
    read -p "ACS data location (default: United States): " ACS_LOCATION
    ACS_LOCATION=${ACS_LOCATION:-"United States"}
    
    read -p "Redis SKU (default: Enterprise_E10): " REDIS_SKU
    REDIS_SKU=${REDIS_SKU:-Enterprise_E10}
    
    cat > terraform.tfvars << EOF
# Auto-generated terraform.tfvars
environment_name = "$ENV_NAME"
name            = "$APP_NAME"
location        = "$LOCATION"
principal_id    = "$CURRENT_USER"
principal_type  = "User"
acs_data_location = "$ACS_LOCATION"
disable_local_auth = true
redis_sku = "$REDIS_SKU"

openai_models = [
  {
    name     = "gpt-4o"
    version  = "2024-11-20"
    sku_name = "Standard"
    capacity = 50
  }
]
EOF
    
    echo "✅ Created terraform.tfvars"
fi

echo ""
echo "🔧 Initializing Terraform..."
terraform init

echo ""
echo "✅ Validating Terraform configuration..."
terraform validate

echo ""
echo "📋 Planning deployment..."
terraform plan

echo ""
read -p "Do you want to proceed with the deployment? (y/N): " CONFIRM
if [[ $CONFIRM =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 Deploying infrastructure..."
    terraform apply -auto-approve
    
    echo ""
    echo "✅ Deployment completed successfully!"
    echo ""
    echo "📊 Key outputs:"
    echo "Resource Group: $(terraform output -raw AZURE_RESOURCE_GROUP)"
    echo "Container Registry: $(terraform output -raw AZURE_CONTAINER_REGISTRY_ENDPOINT)"
    echo "OpenAI Endpoint: $(terraform output -raw AZURE_OPENAI_ENDPOINT)"
    echo "Speech Endpoint: $(terraform output -raw AZURE_SPEECH_ENDPOINT)"
    echo "Key Vault: $(terraform output -raw AZURE_KEY_VAULT_NAME)"
    echo ""
    echo "🎯 Next steps:"
    echo "1. Deploy your container applications to Container Apps"
    echo "2. Provision an ACS phone number for voice capabilities"
    echo "3. Configure your application with the output values above"
    echo ""
    echo "🔗 Useful links:"
    echo "- Azure Portal: https://portal.azure.com"
    echo "- Resource Group: https://portal.azure.com/#@/resource$(terraform output -raw AZURE_RESOURCE_GROUP | sed 's/^/\/subscriptions\//'$(az account show --query id -o tsv)'/resourceGroups\//')"
    
else
    echo "❌ Deployment cancelled."
    exit 0
fi
