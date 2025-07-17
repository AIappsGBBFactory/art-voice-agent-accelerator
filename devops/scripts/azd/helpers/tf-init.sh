#!/bin/bash

# ========================================================================
# 🏗️ Terraform Remote State Storage Account Setup
# ========================================================================
# This script creates Azure Storage Account for Terraform remote state
# using fully Entra-backed authentication. Only creates if storage values
# are not already defined in azd environment.

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Constants
readonly SCRIPT_NAME="$(basename "$0")"
readonly REQUIRED_COMMANDS=("az" "azd")

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ️  [INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}✅ [SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}⚠️  [WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}❌ [ERROR]${NC} $*" >&2
}

# Check if required commands exist
check_dependencies() {
    local missing_commands=()
    
    for cmd in "${REQUIRED_COMMANDS[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_commands+=("$cmd")
        fi
    done
    
    if [[ ${#missing_commands[@]} -gt 0 ]]; then
        log_error "Missing required commands: ${missing_commands[*]}"
        log_error "Please install missing dependencies and try again."
        exit 1
    fi
    
    # Check for optional jq command
    if ! command -v jq &> /dev/null; then
        log_warning "jq not found. Will use fallback method for JSON updates."
        log_info "Install jq for better JSON handling: https://stedolan.github.io/jq/"
    fi
}

# Check if user is logged in to Azure
check_azure_auth() {
    log_info "Checking Azure authentication..."
    
    if ! az account show &> /dev/null; then
        log_error "Not logged in to Azure. Please run 'az login' first."
        exit 1
    fi
    
    local account_info
    account_info=$(az account show --query "{subscriptionId: id, tenantId: tenantId, user: user.name}" -o json)
    log_success "Authenticated to Azure:"
    echo "$account_info" | jq -r '. | "  Subscription: \(.subscriptionId)\n  Tenant: \(.tenantId)\n  User: \(.user)"'
}

# Get azd environment variable value
get_azd_env_value() {
    local key="$1"
    local value
    
    if value=$(azd env get-value "$key" 2>/dev/null); then
        echo "$value"
    else
        echo ""
    fi
}

# Check if remote state storage variables are already set
check_existing_state_config() {
    log_info "Checking existing Terraform remote state configuration..."
    
    local storage_account_name
    local storage_container_name
    local resource_group_name
    
    # Check for new RS_* variables first
    storage_account_name=$(get_azd_env_value "RS_STORAGE_ACCOUNT")
    storage_container_name=$(get_azd_env_value "RS_CONTAINER_NAME")
    resource_group_name=$(get_azd_env_value "RS_RESOURCE_GROUP")
    
    # Fall back to old TERRAFORM_STATE_* variables for backward compatibility
    if [[ -z "$storage_account_name" ]]; then
        storage_account_name=$(get_azd_env_value "TERRAFORM_STATE_STORAGE_ACCOUNT")
        storage_container_name=$(get_azd_env_value "TERRAFORM_STATE_CONTAINER")
        resource_group_name=$(get_azd_env_value "TERRAFORM_STATE_RESOURCE_GROUP")
    fi
    
    if [[ -n "$storage_account_name" && -n "$storage_container_name" && -n "$resource_group_name" ]]; then
        log_warning "Terraform remote state configuration already exists:"
        echo "  Storage Account: $storage_account_name"
        echo "  Container: $storage_container_name"
        echo "  Resource Group: $resource_group_name"
        
        # Check if the storage account actually exists
        if az storage account show --name "$storage_account_name" --resource-group "$resource_group_name" &> /dev/null; then
            log_success "Storage account exists and is accessible."
            
            # Set global variables for use by other functions
            STORAGE_ACCOUNT_NAME="$storage_account_name"
            STORAGE_CONTAINER_NAME="$storage_container_name"
            RESOURCE_GROUP_NAME="$resource_group_name"
            
            return 0
        else
            log_warning "Storage account does not exist or is not accessible. Will create new one."
        fi
    fi
    
    return 1
}

# Generate unique names
generate_resource_names() {
    local env_name
    local subscription_id
    local random_suffix
    
    env_name=$(get_azd_env_value "AZURE_ENV_NAME")
    subscription_id=$(az account show --query id -o tsv)
    
    # Create a deterministic but unique suffix based on subscription and env
    random_suffix=$(echo "${subscription_id}${env_name}" | sha256sum | cut -c1-8)
    
    # Storage account names must be lowercase, alphanumeric, 3-24 chars
    STORAGE_ACCOUNT_NAME="tfstate${random_suffix}"
    STORAGE_CONTAINER_NAME="tfstate"
    RESOURCE_GROUP_NAME="rg-tfstate-${env_name}-${random_suffix}"
    
    # Ensure storage account name is within limits
    if [[ ${#STORAGE_ACCOUNT_NAME} -gt 24 ]]; then
        STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:0:24}"
    fi
    
    log_info "Generated resource names:"
    echo "  Storage Account: $STORAGE_ACCOUNT_NAME"
    echo "  Container: $STORAGE_CONTAINER_NAME"
    echo "  Resource Group: $RESOURCE_GROUP_NAME"
}

# Create resource group if it doesn't exist
create_resource_group() {
    local location
    location=$(get_azd_env_value "AZURE_LOCATION")
    
    if [[ -z "$location" ]]; then
        location="eastus2"
        log_warning "AZURE_LOCATION not set, using default: $location"
    fi
    
    log_info "Creating resource group: $RESOURCE_GROUP_NAME"
    
    if az group show --name "$RESOURCE_GROUP_NAME" &> /dev/null; then
        log_success "Resource group already exists."
    else
        az group create \
            --name "$RESOURCE_GROUP_NAME" \
            --location "$location" \
            --output none
        log_success "Resource group created successfully."
    fi
}

# Create storage account with Entra authentication
create_storage_account() {
    log_info "Creating storage account: $STORAGE_ACCOUNT_NAME"
    
    if az storage account show --name "$STORAGE_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP_NAME" &> /dev/null; then
        log_success "Storage account already exists."
    else
        az storage account create \
            --name "$STORAGE_ACCOUNT_NAME" \
            --resource-group "$RESOURCE_GROUP_NAME" \
            --location "$(az group show --name "$RESOURCE_GROUP_NAME" --query location -o tsv)" \
            --sku Standard_LRS \
            --kind StorageV2 \
            --access-tier Hot \
            --enable-hierarchical-namespace false \
            --allow-blob-public-access false \
            --min-tls-version TLS1_2 \
            --tags "hidden-title=TFState Real Time Audio ${AZURE_ENV_NAME}" \
            --output none

        log_success "Storage account created successfully."
    fi
    
    # Enable versioning for state file protection
    log_info "Enabling blob versioning..."
    az storage account blob-service-properties update \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --enable-versioning true \
        --output none
        
    # Enable change feed for auditing
    az storage account blob-service-properties update \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --enable-change-feed true \
        --output none
        
    log_success "Storage account configured with versioning and change feed."
}

# Create storage container
create_storage_container() {
    log_info "Creating storage container: $STORAGE_CONTAINER_NAME"
    
    # Check if container exists using Entra auth
    if az storage container show \
        --name "$STORAGE_CONTAINER_NAME" \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --auth-mode login \
        &> /dev/null; then
        log_success "Storage container already exists."
    else
        az storage container create \
            --name "$STORAGE_CONTAINER_NAME" \
            --account-name "$STORAGE_ACCOUNT_NAME" \
            --auth-mode login \
            --output none
            
        log_success "Storage container created successfully."
    fi
}

# Assign Storage Blob Data Contributor role to current user
assign_storage_permissions() {
    local current_user_id
    local storage_account_id
    
    log_info "Assigning Storage Blob Data Contributor permissions..."
    
    current_user_id=$(az ad signed-in-user show --query id -o tsv)
    storage_account_id=$(az storage account show \
        --name "$STORAGE_ACCOUNT_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --query id -o tsv)
    
    # Check if role assignment already exists
    if az role assignment list \
        --assignee "$current_user_id" \
        --scope "$storage_account_id" \
        --role "Storage Blob Data Contributor" \
        --query "length(@)" -o tsv | grep -q "1"; then
        log_success "Storage permissions already assigned."
    else
        az role assignment create \
            --assignee "$current_user_id" \
            --role "Storage Blob Data Contributor" \
            --scope "$storage_account_id" \
            --output none
            
        log_success "Storage permissions assigned successfully."
    fi
}

# Set azd environment variables for Terraform remote state
set_azd_environment_variables() {
    log_info "Setting azd environment variables..."
    
    azd env set RS_STORAGE_ACCOUNT "$STORAGE_ACCOUNT_NAME"
    azd env set RS_CONTAINER_NAME "$STORAGE_CONTAINER_NAME" 
    azd env set RS_RESOURCE_GROUP "$RESOURCE_GROUP_NAME"
    azd env set RS_STATE_KEY "terraform.tfstate"
    
    log_success "Environment variables set:"
    echo "  RS_STORAGE_ACCOUNT=$STORAGE_ACCOUNT_NAME"
    echo "  RS_CONTAINER_NAME=$STORAGE_CONTAINER_NAME"
    echo "  RS_RESOURCE_GROUP=$RESOURCE_GROUP_NAME"
    echo "  RS_STATE_KEY=terraform.tfstate"
}

# Ensure infra-tf directory exists
ensure_terraform_directory() {
    local infra_dir="./infra-tf"
    
    log_info "Ensuring Terraform directory exists..."
    
    if [[ ! -d "$infra_dir" ]]; then
        mkdir -p "$infra_dir"
        log_success "Created Terraform directory: $infra_dir"
    else
        log_success "Terraform directory already exists: $infra_dir"
    fi
}

# Update Terraform variables file with azd environment values
update_terraform_vars() {
    local tfvars_file="./infra-tf/main.tfvars.json"
    local provider_conf_file="./infra-tf/provider.conf.json"
    local env_name
    local location
    local subscription_id
    
    log_info "Updating Terraform variables and configuration files..."
    
    # Get azd environment values
    env_name=$(get_azd_env_value "AZURE_ENV_NAME")
    location=$(get_azd_env_value "AZURE_LOCATION")
    subscription_id=$(az account show --query id -o tsv)
    
    # Set defaults if not found
    if [[ -z "$env_name" ]]; then
        env_name="tfdev"
        log_warning "AZURE_ENV_NAME not set, using default: $env_name"
    fi
    
    if [[ -z "$location" ]]; then
        location="eastus2"
        log_warning "AZURE_LOCATION not set, using default: $location"
    fi
    
    # Create or update the tfvars file
    if [[ -f "$tfvars_file" ]]; then
        log_info "Updating existing tfvars file: $tfvars_file"
        
        # Use jq to update existing values while preserving other properties
        if command -v jq &> /dev/null; then
            local temp_file
            temp_file=$(mktemp)
            
            jq --arg env_name "$env_name" --arg location "$location" \
                '.environment_name = $env_name | .location = $location' \
                "$tfvars_file" > "$temp_file" && mv "$temp_file" "$tfvars_file"
                
            log_success "Updated tfvars file using jq."
        else
            # Fallback: recreate the file if jq is not available
            log_warning "jq not found, recreating tfvars file (may lose other variables)."
            cat > "$tfvars_file" << EOF
{
  "environment_name": "$env_name",
  "location": "$location"
}
EOF
        fi
    else
        log_info "Creating new tfvars file: $tfvars_file"
        cat > "$tfvars_file" << EOF
{
  "environment_name": "$env_name",
  "location": "$location"
}
EOF
    fi
    
    # Create provider configuration file
    log_info "Creating provider configuration file: $provider_conf_file"
    cat > "$provider_conf_file" << EOF
{
  "subscription_id": "$subscription_id",
  "environment_name": "$env_name",
  "location": "$location",
  "terraform_state_storage_account": "$STORAGE_ACCOUNT_NAME",
  "terraform_state_container": "$STORAGE_CONTAINER_NAME",
  "terraform_state_resource_group": "$RESOURCE_GROUP_NAME"
}
EOF
    
    log_success "Terraform configuration files updated:"
    echo "  environment_name: $env_name"
    echo "  location: $location"
    echo "  subscription_id: $subscription_id"
    echo "  Files: $tfvars_file, $provider_conf_file"
}

# Create Terraform backend configuration file
create_provider_config() {
    local provider_config_file="./infra-tf/provider.conf.json"
    
    log_info "Creating azd Terraform provider configuration..."
    
    cat > "$provider_config_file" << EOF
{
    "resource_group_name": "\${RS_RESOURCE_GROUP}",
    "storage_account_name": "\${RS_STORAGE_ACCOUNT}",
    "container_name": "\${RS_CONTAINER_NAME}",
    "key": "azd/\${AZURE_ENV_NAME}.tfstate"
}
EOF
    
    log_success "Provider configuration created: $provider_config_file"
    
    # No need to add to gitignore since provider.conf.json contains template variables,
    # not hardcoded values. This file should be committed to version control.
}

# Validate the setup
validate_setup() {
    log_info "Validating Terraform remote state setup..."
    
    # Test storage access
    if az storage blob list \
        --container-name "$STORAGE_CONTAINER_NAME" \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --auth-mode login \
        --output none &> /dev/null; then
        log_success "Storage access validated successfully."
    else
        log_error "Failed to access storage container. Please check permissions."
        return 1
    fi
    
    # Test Terraform initialization if terraform is available
    if command -v terraform &> /dev/null; then
        if (cd infra-tf && terraform init -input=false &> /dev/null); then
            log_success "Terraform initialization successful."
        else
            log_warning "Terraform initialization failed. You may need to run 'terraform init' manually."
        fi
    else
        log_info "Terraform not found. Skipping initialization test."
    fi
}

# Main function
main() {
    echo "========================================================================="
    echo "🏗️  Terraform Remote State Storage Setup"
    echo "========================================================================="
    
    # Check dependencies and authentication
    check_dependencies
    check_azure_auth
    
    # Check if remote state is already configured
    if check_existing_state_config; then
        log_success "Terraform remote state is already configured and accessible."
        
        # Still need to create provider.conf.json and set environment variables for azd
        log_info "Creating azd provider configuration for existing remote state..."
        set_azd_environment_variables
        create_provider_config
        
        echo ""
        log_success "✅ azd Terraform provider configuration completed!"
        echo ""
        echo "📋 Next steps:"
        echo "   1. Verify configuration with 'azd env get-values | grep RS_'"
        echo "   2. Run 'azd up' to deploy your infrastructure"
        echo ""
        echo "📁 Files updated:"
        echo "   - infra-tf/provider.conf.json (azd Terraform provider configuration)"
        exit 0
    fi
    
    # Generate resource names
    generate_resource_names
    
    # Create resources
    create_resource_group
    create_storage_account
    create_storage_container
    assign_storage_permissions
    
    # Configure azd and Terraform
    set_azd_environment_variables
    update_terraform_vars
    create_provider_config
    
    # Validate setup
    validate_setup
    
    echo "========================================================================="
    log_success "Terraform remote state storage setup completed successfully!"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Run 'terraform init' in the infra-tf directory"
    echo "   2. Run 'azd up' to deploy your infrastructure"
    echo ""
    echo "� Files updated:"
    echo "   - infra-tf/provider.conf.json (azd Terraform provider configuration)"
    echo "   - infra-tf/main.tfvars.json (Terraform variables from azd env)"
    echo ""
    echo "�🔒 Security notes:"
    echo "   - Remote state uses Entra ID authentication"
    echo "   - Storage account has versioning enabled"
    echo "   - All access is audited via change feed"
    echo "========================================================================="
}

# Handle script interruption
trap 'log_error "Script interrupted by user"; exit 130' INT

# Run main function
main "$@"
