#!/bin/bash
# ============================================================================
# 🎯 Azure Developer CLI Pre-Provisioning Script
# ============================================================================
# Runs before azd provisions Azure resources. Handles:
#   - Terraform: Remote state setup + tfvars generation
#   - Bicep: SSL certificate configuration
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROVIDER="${1:-}"

# ============================================================================
# Logging (unified style)
# ============================================================================

is_ci() {
    [[ "${CI:-}" == "true" || "${GITHUB_ACTIONS:-}" == "true" || "${AZD_SKIP_INTERACTIVE:-}" == "true" ]]
}

log()     { echo "│ $*"; }
info()    { echo "│ ℹ️  $*"; }
success() { echo "│ ✅ $*"; }
warn()    { echo "│ ⚠️  $*"; }
fail()    { echo "│ ❌ $*" >&2; }

header() {
    echo ""
    echo "╭─────────────────────────────────────────────────────────────"
    echo "│ $*"
    echo "├─────────────────────────────────────────────────────────────"
}

footer() {
    echo "╰─────────────────────────────────────────────────────────────"
    echo ""
}

# ============================================================================
# Helpers
# ============================================================================

get_deployer_identity() {
    local name=""
    
    # Try git config first
    if command -v git &>/dev/null; then
        local git_name git_email
        git_name=$(git config --get user.name 2>/dev/null || true)
        git_email=$(git config --get user.email 2>/dev/null || true)
        [[ -n "$git_name" && -n "$git_email" ]] && name="$git_name <$git_email>"
        [[ -z "$name" && -n "$git_email" ]] && name="$git_email"
    fi
    
    # Fallback to Azure CLI
    if [[ -z "$name" ]] && command -v az &>/dev/null; then
        name=$(az account show --query user.name -o tsv 2>/dev/null || true)
        [[ "$name" == "None" ]] && name=""
    fi
    
    echo "${name:-unknown}"
}

# Resolve location with fallback chain: env var → env-specific tfvars → default tfvars → prompt
resolve_location() {
    local params_dir="$SCRIPT_DIR/../../../infra/terraform/params"
    
    # 1. Already set via environment
    if [[ -n "${AZURE_LOCATION:-}" ]]; then
        info "Using AZURE_LOCATION from environment: $AZURE_LOCATION"
        return 0
    fi
    
    # 2. Try environment-specific tfvars (e.g., main.tfvars.staging.json)
    local env_tfvars="$params_dir/main.tfvars.${AZURE_ENV_NAME}.json"
    if [[ -f "$env_tfvars" ]]; then
        AZURE_LOCATION=$(jq -r '.location // empty' "$env_tfvars" 2>/dev/null || true)
        if [[ -n "$AZURE_LOCATION" ]]; then
            info "Resolved location from $env_tfvars: $AZURE_LOCATION"
            export AZURE_LOCATION
            return 0
        fi
    fi
    
    # 3. Try default tfvars
    local default_tfvars="$params_dir/main.tfvars.default.json"
    if [[ -f "$default_tfvars" ]]; then
        AZURE_LOCATION=$(jq -r '.location // empty' "$default_tfvars" 2>/dev/null || true)
        if [[ -n "$AZURE_LOCATION" ]]; then
            info "Resolved location from default tfvars: $AZURE_LOCATION"
            export AZURE_LOCATION
            return 0
        fi
    fi
    
    # 4. Interactive prompt (local dev only)
    if ! is_ci; then
        log "No location found in tfvars files."
        read -rp "│ Enter Azure location (e.g., eastus, westus2): " AZURE_LOCATION
        if [[ -n "$AZURE_LOCATION" ]]; then
            export AZURE_LOCATION
            return 0
        fi
    fi
    
    return 1
}

# Set Terraform variables using azd env (stored in .azure/<env>/.env as TF_VAR_*)
# This is the azd best practice - azd automatically exports TF_VAR_* to Terraform
set_terraform_env_vars() {
    local deployer
    deployer=$(get_deployer_identity)
    
    log "Setting Terraform variables via azd env..."
    
    # Set TF_VAR_* variables - azd stores these in .azure/<env>/.env
    # and automatically exports them when running terraform
    azd env set TF_VAR_environment_name "$AZURE_ENV_NAME"
    azd env set TF_VAR_location "$AZURE_LOCATION"
    azd env set TF_VAR_deployed_by "$deployer"
    
    info "Deployer: $deployer"
    success "Set TF_VAR_* in azd environment"
}

# ============================================================================
# Providers
# ============================================================================

provider_terraform() {
    header "🏗️  Terraform Pre-Provisioning"
    
    # Validate required variables
    if [[ -z "${AZURE_ENV_NAME:-}" ]]; then
        fail "AZURE_ENV_NAME is not set"
        footer
        exit 1
    fi
    
    # Resolve location using fallback chain
    if ! resolve_location; then
        fail "Could not resolve AZURE_LOCATION. Set it via 'azd env set AZURE_LOCATION <region>' or add to tfvars."
        footer
        exit 1
    fi
    
    info "Environment: $AZURE_ENV_NAME"
    info "Location: $AZURE_LOCATION"
    log ""
    
    # Run remote state initialization
    local tf_init="$SCRIPT_DIR/helpers/initialize-terraform.sh"
    if [[ -f "$tf_init" ]]; then
        is_ci && export TF_INIT_SKIP_INTERACTIVE=true
        log "Setting up Terraform remote state..."
        bash "$tf_init"
    else
        warn "initialize-terraform.sh not found, skipping remote state setup"
    fi
    
    log ""
    
    # Set Terraform variables via azd env
    # In CI, the workflow may pre-set TF_VAR_* - check before overwriting
    if is_ci; then
        # CI: Only set if not already configured by workflow
        if [[ -z "${TF_VAR_environment_name:-}" ]]; then
            log "Setting Terraform variables..."
            set_terraform_env_vars
        else
            info "CI mode: TF_VAR_* already set by workflow, skipping"
        fi
    else
        # Local: Always set to ensure consistency
        log "Setting Terraform variables..."
        set_terraform_env_vars
    fi
    
    footer
}

provider_bicep() {
    header "🔧 Bicep Pre-Provisioning"
    
    local ssl_script="$SCRIPT_DIR/helpers/ssl-preprovision.sh"
    
    if [[ ! -f "$ssl_script" ]]; then
        warn "ssl-preprovision.sh not found"
        footer
        return 0
    fi
    
    if is_ci; then
        info "CI/CD mode: Checking for SSL certificates..."
        if [[ -n "${SSL_CERT_BASE64:-}" && -n "${SSL_KEY_BASE64:-}" ]]; then
            echo "$SSL_CERT_BASE64" | base64 -d > "$SCRIPT_DIR/helpers/ssl-cert.pem"
            echo "$SSL_KEY_BASE64" | base64 -d > "$SCRIPT_DIR/helpers/ssl-key.pem"
            success "SSL certificates configured from environment"
        else
            warn "No SSL certificates in environment (set SSL_CERT_BASE64 and SSL_KEY_BASE64)"
        fi
    else
        log "Running SSL pre-provisioning..."
        bash "$ssl_script"
    fi
    
    footer
}

# ============================================================================
# Main
# ============================================================================

main() {
    if [[ -z "$PROVIDER" ]]; then
        fail "Usage: $0 <bicep|terraform>"
        exit 1
    fi
    
    is_ci && info "🤖 CI/CD mode detected"
    
    case "$PROVIDER" in
        terraform) provider_terraform ;;
        bicep)     provider_bicep ;;
        *)
            fail "Invalid provider: $PROVIDER (must be 'bicep' or 'terraform')"
            exit 1
            ;;
    esac
    
    success "Pre-provisioning complete!"
}

main "$@"
