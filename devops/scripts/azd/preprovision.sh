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

write_tfvars() {
    local tfvars_file="$SCRIPT_DIR/../../../infra/terraform/main.tfvars.json"
    local deployer
    deployer=$(get_deployer_identity)
    
    cat > "$tfvars_file" << EOF
{
  "environment_name": "$AZURE_ENV_NAME",
  "location": "$AZURE_LOCATION",
  "deployed_by": "$deployer"
}
EOF
    
    info "Deployer: $deployer"
    success "Written main.tfvars.json"
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
    
    # If AZURE_LOCATION is not set, try to extract it from the environment-specific tfvars file
    if [[ -z "${AZURE_LOCATION:-}" ]]; then
        local tfvars_file="$SCRIPT_DIR/../../../infra/terraform/params/main.tfvars.${AZURE_ENV_NAME}.json"
        if [[ -f "$tfvars_file" ]]; then
            AZURE_LOCATION=$(jq -r '.location // empty' "$tfvars_file" 2>/dev/null || true)
            if [[ -n "$AZURE_LOCATION" ]]; then
                info "Extracted location from tfvars: $AZURE_LOCATION"
                export AZURE_LOCATION
            fi
        fi
    fi
    
    # Final validation
    if [[ -z "${AZURE_LOCATION:-}" ]]; then
        fail "AZURE_LOCATION is not set and could not be extracted from tfvars"
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
    
    # In CI mode, the workflow already creates main.tfvars.json with all parameters
    # Only write tfvars in local/interactive mode
    if is_ci && [[ -f "$SCRIPT_DIR/../../../infra/terraform/main.tfvars.json" ]]; then
        info "CI mode: main.tfvars.json already exists (created by workflow), skipping write"
    else
        log "Writing Terraform variables..."
        write_tfvars
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
