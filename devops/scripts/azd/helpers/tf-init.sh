#!/bin/bash

# ========================================================================
# 🏗️ Terraform Remote State Storage Account Setup
# ========================================================================
# This script creates Azure Storage Account for Terraform remote state
# using fully Entra-backed authentication.

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Helper functions
log_info() { echo -e "${BLUE}ℹ️  [INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}✅ [SUCCESS]${NC} $*"; }
log_warning() { echo -e "${YELLOW}⚠️  [WARNING]${NC} $*"; }
log_error() { echo -e "${RED}❌ [ERROR]${NC} $*" >&2; }

# Check dependencies
check_dependencies() {
    local deps=("az" "azd")
    for cmd in "${deps[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "Missing required command: $cmd"
            exit 1
        fi
    done
    
    if ! az account show &> /dev/null; then
        log_error "Not logged in to Azure. Please run 'az login' first."
        exit 1
    fi
}

# Get azd environment variable value
get_azd_env() {
    azd env get-value "$1" 2>/dev/null || echo ""
}

# Check if storage account exists and is accessible
storage_exists() {
    local account="$1"
    local rg="$2"
    az storage account show --name "$account" --resource-group "$rg" &> /dev/null
}

# Generate unique resource names
generate_names() {
    local env_name="${1:-tfdev}"
    local sub_id="$2"
    local suffix=$(echo "${sub_id}${env_name}" | sha256sum | cut -c1-8)
    
    echo "tfstate${suffix}" # storage account
    echo "tfstate" # container
    echo "rg-tfstate-${env_name}-${suffix}" # resource group
}

# Create storage resources
create_storage() {
    local storage_account="$1"
    local container="$2"
    local resource_group="$3"
    local location="${4:-eastus2}"
    
    # Create resource group
    if ! az group show --name "$resource_group" &> /dev/null; then
        log_info "Creating resource group: $resource_group"
        az group create --name "$resource_group" --location "$location" --output none
    fi
    
    # Create storage account
    if ! storage_exists "$storage_account" "$resource_group"; then
        log_info "Creating storage account: $storage_account"
        az storage account create \
            --name "$storage_account" \
            --resource-group "$resource_group" \
            --location "$location" \
            --sku Standard_LRS \
            --kind StorageV2 \
            --allow-blob-public-access false \
            --min-tls-version TLS1_2 \
            --output none
            
        # Enable versioning and change feed
        az storage account blob-service-properties update \
            --account-name "$storage_account" \
            --resource-group "$resource_group" \
            --enable-versioning true \
            --enable-change-feed true \
            --output none
    fi
    
    # Create container
    if ! az storage container show \
        --name "$container" \
        --account-name "$storage_account" \
        --auth-mode login &> /dev/null; then
        log_info "Creating storage container: $container"
        az storage container create \
            --name "$container" \
            --account-name "$storage_account" \
            --auth-mode login \
            --output none
    fi
    
    # Assign permissions
    local user_id=$(az ad signed-in-user show --query id -o tsv)
    local storage_id=$(az storage account show \
        --name "$storage_account" \
        --resource-group "$resource_group" \
        --query id -o tsv)
        
    if ! az role assignment list \
        --assignee "$user_id" \
        --scope "$storage_id" \
        --role "Storage Blob Data Contributor" \
        --query "length(@)" -o tsv | grep -q "1"; then
        log_info "Assigning storage permissions..."
        az role assignment create \
            --assignee "$user_id" \
            --role "Storage Blob Data Contributor" \
            --scope "$storage_id" \
            --output none
    fi
}

# Check if JSON file has meaningful content
has_json_content() {
    local file="$1"
    
    # If file doesn't exist or is empty, return false
    [[ ! -f "$file" ]] || [[ ! -s "$file" ]] && return 1
    
    # Remove whitespace and check if it's just empty braces
    local content=$(tr -d '[:space:]' < "$file")
    [[ "$content" == "{}" ]] && return 1
    
    # Check if file has any JSON keys
    if python3 -c "import json; data=json.load(open('$file')); exit(0 if data else 1)" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Update tfvars file only if empty or non-existent
update_tfvars() {
    local tfvars_file="./infra/terraform/main.tfvars.json"
    local env_name="${1:-tfdev}"
    local location="${2:-eastus2}"
    
    # Ensure directory exists
    mkdir -p "$(dirname "$tfvars_file")"
    
    # Check if file has actual content
    if has_json_content "$tfvars_file"; then
        log_info "tfvars file already contains values, skipping update"
        return 0
    fi
    
    log_info "Creating/updating tfvars file: $tfvars_file"
    
    # Write the tfvars content
    cat > "$tfvars_file" << EOF
{
  "environment_name": "$env_name",
  "location": "$location"
}
EOF
    log_success "Updated $tfvars_file"
}

# Main execution
main() {
    echo "========================================================================="
    echo "🏗️  Terraform Remote State Storage Setup"
    echo "========================================================================="
    
    check_dependencies
    
    # Get environment values
    local env_name=$(get_azd_env "AZURE_ENV_NAME")
    local location=$(get_azd_env "AZURE_LOCATION")
    local sub_id=$(az account show --query id -o tsv)
    
    # Use defaults if not set
    env_name="${env_name:-tfdev}"
    location="${location:-eastus2}"
    
    # Check existing configuration
    local storage_account=$(get_azd_env "RS_STORAGE_ACCOUNT")
    local container=$(get_azd_env "RS_CONTAINER_NAME")
    local resource_group=$(get_azd_env "RS_RESOURCE_GROUP")
    
    # If not configured or doesn't exist, create new
    if [[ -z "$storage_account" ]] || ! storage_exists "$storage_account" "$resource_group"; then
        log_info "Setting up new Terraform remote state storage..."
        read storage_account container resource_group <<< $(generate_names "$env_name" "$sub_id")
        create_storage "$storage_account" "$container" "$resource_group" "$location"
        
        # Set azd environment variables
        azd env set RS_STORAGE_ACCOUNT "$storage_account"
        azd env set RS_CONTAINER_NAME "$container"
        azd env set RS_RESOURCE_GROUP "$resource_group"
        azd env set RS_STATE_KEY "terraform.tfstate"
    else
        log_success "Using existing remote state configuration"
    fi
    
    # Update tfvars file (only if empty or doesn't exist)
    update_tfvars "$env_name" "$location"
    

    
    log_success "✅ Terraform remote state setup completed!"
    echo ""
    echo "📋 Configuration:"
    echo "   Storage Account: $storage_account"
    echo "   Container: $container"
    echo "   Resource Group: $resource_group"
    echo ""
    echo "📁 Files created/updated:"
    echo "   - infra/terraform/provider.conf.json"
    echo "   - infra/terraform/main.tfvars.json (only if empty/new)"
}

# Handle script interruption
trap 'log_error "Script interrupted"; exit 130' INT

# Run main function
main "$@"