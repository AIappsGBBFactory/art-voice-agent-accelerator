#!/bin/bash
# ============================================================================
# 🎯 Azure Developer CLI Post-Provisioning Script (v2 - App Config First)
# ============================================================================
#
# This script runs after Terraform provisioning and handles tasks that CANNOT
# be done by Terraform:
#
# 1. Cosmos DB initialization (seeding data - one-time operation)
# 2. ACS phone number provisioning (interactive or CI/CD purchase)
# 3. App Config URL updates (backend/frontend URLs known only after deploy)
#
# REMOVED in v2 (now handled by App Configuration):
# - Container App environment variable patching (apps read from App Config)
# - Environment file generation (use local-dev-setup.sh for local dev)
# - All scattered azd env var lookups for configuration values
#
# CI/CD Mode: Set AZD_SKIP_INTERACTIVE=true to bypass all prompts
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HELPERS_DIR="$SCRIPT_DIR/helpers"

# ============================================================================
# Configuration Detection
# ============================================================================

detect_execution_mode() {
    if [[ "${CI:-false}" == "true" ]] || \
       [[ "${GITHUB_ACTIONS:-false}" == "true" ]] || \
       [[ "${AZD_SKIP_INTERACTIVE:-false}" == "true" ]]; then
        echo "ci"
    else
        echo "interactive"
    fi
}

readonly EXEC_MODE=$(detect_execution_mode)

# Color codes (disabled in CI)
if [[ "$EXEC_MODE" == "interactive" ]] && [[ -t 1 ]]; then
    readonly RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' BLUE='\033[0;34m' NC='\033[0m'
else
    readonly RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# ============================================================================
# Logging
# ============================================================================

log()      { echo -e "${BLUE}ℹ️  $*${NC}"; }
success()  { echo -e "${GREEN}✅ $*${NC}"; }
warn()     { echo -e "${YELLOW}⚠️  $*${NC}"; }
error()    { echo -e "${RED}❌ $*${NC}" >&2; }
section()  { echo -e "\n${BLUE}$1${NC}\n$(printf '═%.0s' {1..60})"; }

# ============================================================================
# AZD Environment Helpers
# ============================================================================

# Get azd environment value with optional fallback
azd_get() {
    local key="$1" fallback="${2:-}"
    local val
    val=$(azd env get-value "$key" 2>/dev/null || echo "")
    if [[ -z "$val" || "$val" == "null" || "$val" == ERROR* ]]; then
        echo "$fallback"
    else
        echo "$val"
    fi
}

# Set azd environment value
azd_set() {
    local key="$1" val="$2"
    azd env set "$key" "$val" 2>/dev/null || warn "Failed to set $key in azd env"
}

# ============================================================================
# App Configuration Helpers
# ============================================================================

# Get the App Configuration endpoint from azd outputs
get_appconfig_endpoint() {
    azd_get "AZURE_APPCONFIG_ENDPOINT"
}

# Update a key in App Configuration
appconfig_set() {
    local endpoint="$1" key="$2" value="$3" label="${4:-}"
    
    if [[ -z "$endpoint" ]]; then
        warn "App Config endpoint not available, skipping key update: $key"
        return 1
    fi
    
    local label_arg=""
    [[ -n "$label" ]] && label_arg="--label $label"
    
    # Use az appconfig kv set with managed identity auth
    if az appconfig kv set \
        --endpoint "$endpoint" \
        --key "$key" \
        --value "$value" \
        $label_arg \
        --yes \
        --output none 2>/dev/null; then
        return 0
    else
        warn "Failed to update App Config key: $key"
        return 1
    fi
}

# Update sentinel to trigger config refresh in running apps
trigger_config_refresh() {
    local endpoint="$1"
    local label="${2:-}"
    local timestamp
    timestamp=$(date +%s)
    
    log "Triggering config refresh (sentinel update)..."
    if appconfig_set "$endpoint" "app/sentinel" "v${timestamp}" "$label"; then
        success "Config refresh triggered"
    fi
}

# ============================================================================
# Task 1: Cosmos DB Initialization
# ============================================================================

task_cosmos_init() {
    section "🗄️ Task 1: Cosmos DB Initialization"
    
    local db_init
    db_init=$(azd_get "DB_INITIALIZED" "false")
    
    if [[ "$db_init" == "true" ]]; then
        log "Cosmos DB already initialized, skipping"
        return 0
    fi
    
    local conn_string
    conn_string=$(azd_get "AZURE_COSMOS_CONNECTION_STRING")
    
    if [[ -z "$conn_string" ]]; then
        warn "AZURE_COSMOS_CONNECTION_STRING not set, skipping Cosmos init"
        return 1
    fi
    
    # Export required environment variables for the Python script
    export AZURE_COSMOS_CONNECTION_STRING="$conn_string"
    export AZURE_COSMOS_DATABASE_NAME="$(azd_get "AZURE_COSMOS_DATABASE_NAME" "audioagentdb")"
    export AZURE_COSMOS_COLLECTION_NAME="$(azd_get "AZURE_COSMOS_COLLECTION_NAME" "audioagentcollection")"
    
    # Install dependencies if requirements file exists
    if [[ -f "$HELPERS_DIR/requirements-cosmos.txt" ]]; then
        log "Installing Cosmos DB Python dependencies..."
        pip3 install -q -r "$HELPERS_DIR/requirements-cosmos.txt" || warn "Dependency install had issues"
    fi
    
    log "Running Cosmos DB initialization..."
    if python3 "$HELPERS_DIR/cosmos_init.py"; then
        success "Cosmos DB initialized"
        azd_set "DB_INITIALIZED" "true"
        return 0
    else
        error "Cosmos DB initialization failed"
        return 1
    fi
}

# ============================================================================
# Task 2: ACS Phone Number Configuration
# ============================================================================

task_phone_number() {
    section "📞 Task 2: ACS Phone Number Configuration"
    
    local endpoint label
    endpoint=$(get_appconfig_endpoint)
    label=$(azd_get "AZURE_ENV_NAME")
    
    # Check if phone already configured in App Config (primary source)
    if [[ -n "$endpoint" ]]; then
        local appconfig_phone
        appconfig_phone=$(az appconfig kv show \
            --endpoint "$endpoint" \
            --key "azure/acs/source-phone-number" \
            --label "$label" \
            --query "value" -o tsv 2>/dev/null || echo "")
        
        if [[ -n "$appconfig_phone" && "$appconfig_phone" =~ ^\+[0-9]{10,15}$ ]]; then
            success "Phone number already in App Config: $appconfig_phone"
            # Sync to azd env for reference
            azd_set "ACS_SOURCE_PHONE_NUMBER" "$appconfig_phone"
            return 0
        fi
    fi
    
    # Fallback: check azd env (legacy)
    local existing
    existing=$(azd_get "ACS_SOURCE_PHONE_NUMBER")
    
    if [[ -n "$existing" && "$existing" =~ ^\+[0-9]{10,15}$ ]]; then
        log "Found phone in azd env, migrating to App Config..."
        update_phone_in_appconfig "$existing"
        success "Phone number migrated to App Config: $existing"
        return 0
    fi
    
    if [[ "$EXEC_MODE" == "ci" ]]; then
        # CI mode: check environment variable or auto-provision flag
        if [[ -n "${ACS_SOURCE_PHONE_NUMBER:-}" ]]; then
            if [[ "$ACS_SOURCE_PHONE_NUMBER" =~ ^\+[0-9]{10,15}$ ]]; then
                update_phone_in_appconfig "$ACS_SOURCE_PHONE_NUMBER"
                azd_set "ACS_SOURCE_PHONE_NUMBER" "$ACS_SOURCE_PHONE_NUMBER"
                success "Phone number set from environment"
                return 0
            else
                warn "Invalid phone format in environment: $ACS_SOURCE_PHONE_NUMBER"
            fi
        fi
        
        if [[ "$(azd_get "ACS_AUTO_PROVISION_PHONE" "false")" == "true" ]]; then
            log "Auto-provisioning phone number..."
            provision_phone_number
            return $?
        fi
        
        log "No phone configured (set ACS_SOURCE_PHONE_NUMBER or ACS_AUTO_PROVISION_PHONE=true)"
        show_manual_phone_instructions
        return 0
    fi
    
    # Interactive mode
    echo ""
    echo "📞 Phone Number Configuration"
    echo ""
    echo "A phone number is required for voice calls. Options:"
    echo ""
    echo "  1) Enter an existing phone number (if you already have one)"
    echo "  2) Provision a new number from Azure (requires payment method)"
    echo "  3) Skip for now (configure later via Azure Portal)"
    echo ""
    read -rp "Choice (1-3): " choice
    
    case "$choice" in
        1)
            read -rp "Enter phone number (E.164 format, e.g., +18001234567): " phone
            if [[ "$phone" =~ ^\+[0-9]{10,15}$ ]]; then
                update_phone_in_appconfig "$phone"
                azd_set "ACS_SOURCE_PHONE_NUMBER" "$phone"
                success "Phone number saved to App Config"
            else
                error "Invalid format. Use E.164 format: +[country code][number]"
                return 1
            fi
            ;;
        2) provision_phone_number ;;
        3)
            log "Skipping phone configuration"
            show_manual_phone_instructions
            ;;
        *) error "Invalid choice" ;;
    esac
}

show_manual_phone_instructions() {
    local endpoint label
    endpoint=$(get_appconfig_endpoint)
    label=$(azd_get "AZURE_ENV_NAME")
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📞 Manual Phone Number Setup"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "To configure a phone number later:"
    echo ""
    echo "1. Go to Azure Portal → Azure Communication Services resource"
    echo "2. Select 'Telephony and SMS' → 'Phone numbers'"
    echo "3. Click '+ Get' to purchase a toll-free or local number"
    echo "4. Update App Configuration with your phone number:"
    echo ""
    if [[ -n "$endpoint" ]]; then
        echo "   az appconfig kv set \\"
        echo "     --endpoint \"$endpoint\" \\"
        echo "     --key \"azure/acs/source-phone-number\" \\"
        echo "     --value \"+1YOUR_PHONE_NUMBER\" \\"
        echo "     --label \"$label\" \\"
        echo "     --yes"
        echo ""
        echo "5. Trigger config refresh:"
        echo ""
        echo "   az appconfig kv set \\"
        echo "     --endpoint \"$endpoint\" \\"
        echo "     --key \"app/sentinel\" \\"
        echo "     --value \"v\$(date +%s)\" \\"
        echo "     --label \"$label\" \\"
        echo "     --yes"
    else
        echo "   (App Config endpoint not available - check deployment)"
    fi
    echo ""
    echo "📄 Full guide: docs/deployment/phone-number-setup.md"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

provision_phone_number() {
    local acs_endpoint
    acs_endpoint=$(azd_get "ACS_ENDPOINT")
    
    if [[ -z "$acs_endpoint" ]]; then
        error "ACS_ENDPOINT not set"
        return 1
    fi
    
    # Ensure dependencies
    az extension add --name communication 2>/dev/null || true
    pip3 install -q azure-identity azure-communication-phonenumbers 2>/dev/null || true
    
    log "Purchasing phone number from Azure..."
    local phone
    phone=$(python3 "$HELPERS_DIR/acs_phone_number_manager.py" \
        --endpoint "$acs_endpoint" purchase 2>/dev/null | grep -o '+[0-9]\+' | head -1)
    
    if [[ -n "$phone" ]]; then
        # Store in App Config (primary) and azd env (reference)
        update_phone_in_appconfig "$phone"
        azd_set "ACS_SOURCE_PHONE_NUMBER" "$phone"
        success "Provisioned and saved to App Config: $phone"
        return 0
    else
        error "Phone provisioning failed"
        echo ""
        warn "You can manually purchase a phone number via Azure Portal."
        show_manual_phone_instructions
        return 1
    fi
}

update_phone_in_appconfig() {
    local phone="$1"
    local endpoint label
    endpoint=$(get_appconfig_endpoint)
    label=$(azd_get "AZURE_ENV_NAME")
    
    if [[ -n "$endpoint" ]]; then
        log "Saving phone number to App Configuration..."
        if appconfig_set "$endpoint" "azure/acs/source-phone-number" "$phone" "$label"; then
            # Trigger refresh so apps pick up the new number
            trigger_config_refresh "$endpoint" "$label"
            return 0
        else
            warn "Failed to save phone to App Config (update manually)"
            return 1
        fi
    else
        warn "App Config not available, phone number only in azd env"
        return 1
    fi
}

# ============================================================================
# Task 3: App Configuration URL Updates
# ============================================================================

task_update_urls() {
    section "🌐 Task 3: App Configuration URL Updates"
    
    local endpoint label backend_url
    endpoint=$(get_appconfig_endpoint)
    label=$(azd_get "AZURE_ENV_NAME")
    
    if [[ -z "$endpoint" ]]; then
        warn "App Config endpoint not available, skipping URL updates"
        return 1
    fi
    
    # Determine backend URL (try multiple sources)
    backend_url=$(azd_get "BACKEND_API_URL")
    [[ -z "$backend_url" ]] && backend_url=$(azd_get "BACKEND_CONTAINER_APP_URL")
    if [[ -z "$backend_url" ]]; then
        local fqdn
        fqdn=$(azd_get "BACKEND_CONTAINER_APP_FQDN")
        [[ -n "$fqdn" ]] && backend_url="https://${fqdn}"
    fi
    
    if [[ -z "$backend_url" ]]; then
        warn "Could not determine backend URL from azd outputs"
        return 1
    fi
    
    # Derive WebSocket URL
    local ws_url="${backend_url/https:\/\//wss://}"
    ws_url="${ws_url/http:\/\//ws://}"
    
    log "Setting backend URL: $backend_url"
    log "Setting WebSocket URL: $ws_url"
    
    # Update App Configuration keys
    local success_count=0
    appconfig_set "$endpoint" "app/backend/base-url" "$backend_url" "$label" && ((success_count++))
    appconfig_set "$endpoint" "app/frontend/backend-url" "$backend_url" "$label" && ((success_count++))
    appconfig_set "$endpoint" "app/frontend/ws-url" "$ws_url" "$label" && ((success_count++))
    
    if [[ $success_count -eq 3 ]]; then
        success "All URL keys updated in App Config"
        
        # Trigger refresh so running apps pick up new URLs
        trigger_config_refresh "$endpoint" "$label"
        return 0
    else
        warn "Some URL updates failed ($success_count/3 succeeded)"
        return 1
    fi
}

# ============================================================================
# Summary
# ============================================================================

show_summary() {
    section "🎯 Post-Provisioning Summary"
    
    local endpoint label
    endpoint=$(get_appconfig_endpoint)
    label=$(azd_get "AZURE_ENV_NAME")
    
    echo ""
    echo "📊 Configuration Source:"
    if [[ -n "$endpoint" ]]; then
        echo "   ✅ Azure App Configuration: $endpoint"
        echo "   ✅ Environment label: $label"
        echo "   All settings are managed centrally in App Config"
    else
        echo "   ⚠️  App Configuration not deployed"
    fi
    
    echo ""
    echo "🔧 Task Results:"
    
    local db_init phone
    db_init=$(azd_get "DB_INITIALIZED" "false")
    phone=$(azd_get "ACS_SOURCE_PHONE_NUMBER")
    
    [[ "$db_init" == "true" ]] && echo "   ✅ Cosmos DB: initialized" || echo "   ⏳ Cosmos DB: pending"
    
    if [[ -n "$phone" ]]; then
        echo "   ✅ Phone: $phone (stored in App Config)"
    else
        echo "   ⏳ Phone: not configured"
        echo "      → See: docs/deployment/phone-number-setup.md"
    fi
    
    [[ -n "$endpoint" ]] && echo "   ✅ URLs: stored in App Config" || echo "   ⏳ URLs: pending"
    
    echo ""
    
    if [[ "$EXEC_MODE" == "interactive" ]]; then
        echo "🚀 Next Steps:"
        echo "   1. Verify deployment: azd show"
        echo "   2. Test health: curl \$(azd env get-value BACKEND_CONTAINER_APP_URL)/health"
        
        if [[ -z "$phone" ]]; then
            echo "   3. Configure phone number (required for voice calls):"
            echo "      → Azure Portal: ACS resource → Telephony and SMS → Phone numbers → + Get"
            echo "      → Then update App Config: azure/acs/source-phone-number"
        fi
        
        if [[ -n "$endpoint" ]]; then
            echo ""
            echo "📋 View App Configuration:"
            echo "   az appconfig kv list --endpoint $endpoint --label $label -o table"
        fi
        
        echo ""
        echo "📄 Documentation:"
        echo "   • Phone setup: docs/deployment/phone-number-setup.md"
        echo "   • Local dev: devops/scripts/azd/helpers/local-dev-setup.sh"
        echo ""
    fi
    
    success "Post-provisioning complete!"
}

# ============================================================================
# Main
# ============================================================================

main() {
    section "🚀 Post-Provisioning v2 (App Config First)"
    
    log "Execution mode: $EXEC_MODE"
    
    # Run tasks (individual failures don't stop execution)
    task_cosmos_init || true
    task_phone_number || true
    task_update_urls || true
    
    show_summary
}

main "$@"
