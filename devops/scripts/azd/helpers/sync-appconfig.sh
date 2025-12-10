#!/bin/bash
# ============================================================================
# 📦 App Configuration Sync
# ============================================================================
# Syncs ALL configuration to Azure App Configuration:
#   1. Infrastructure keys from azd env (Azure endpoints, connection strings)
#   2. Application settings from config/appconfig.json (pools, voice, etc.)
#
# Usage: ./sync-appconfig.sh [--endpoint URL] [--label LABEL] [--config FILE]
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DEFAULT_CONFIG="$SCRIPT_DIR/../../../../config/appconfig.json"

# ============================================================================
# Logging
# ============================================================================

log()     { echo "│ $*"; }
info()    { echo "│ ℹ️  $*"; }
success() { echo "│ ✅ $*"; }
warn()    { echo "│ ⚠️  $*"; }
fail()    { echo "│ ❌ $*" >&2; }

# ============================================================================
# Parse Arguments
# ============================================================================

ENDPOINT=""
LABEL=""
CONFIG_FILE="$DEFAULT_CONFIG"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --endpoint) ENDPOINT="$2"; shift 2 ;;
        --label) LABEL="$2"; shift 2 ;;
        --config) CONFIG_FILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--endpoint URL] [--label LABEL] [--config FILE] [--dry-run]"
            exit 0
            ;;
        *) fail "Unknown option: $1"; exit 1 ;;
    esac
done

# Get from azd env if not provided
if [[ -z "$ENDPOINT" ]]; then
    ENDPOINT=$(azd env get-value AZURE_APPCONFIG_ENDPOINT 2>/dev/null || echo "")
fi
if [[ -z "$LABEL" ]]; then
    LABEL=$(azd env get-value AZURE_ENV_NAME 2>/dev/null || echo "")
fi

if [[ -z "$ENDPOINT" ]]; then
    fail "App Config endpoint not set. Use --endpoint or set AZURE_APPCONFIG_ENDPOINT"
    exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    fail "Config file not found: $CONFIG_FILE"
    exit 1
fi

# ============================================================================
# App Config Helper
# ============================================================================

set_key() {
    local key="$1" value="$2"
    local label_arg=""
    [[ -n "$LABEL" ]] && label_arg="--label $LABEL"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would set: $key = $value"
        return 0
    fi
    
    az appconfig kv set \
        --endpoint "$ENDPOINT" \
        --key "$key" \
        --value "$value" \
        $label_arg \
        --auth-mode login \
        --yes \
        --output none 2>/dev/null
}

set_feature() {
    local key="$1" enabled="$2"
    local label_arg=""
    [[ -n "$LABEL" ]] && label_arg="--label $LABEL"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would set feature: $key = $enabled"
        return 0
    fi
    
    if [[ "$enabled" == "true" ]]; then
        az appconfig feature set \
            --endpoint "$ENDPOINT" \
            --feature "$key" \
            $label_arg \
            --auth-mode login \
            --yes \
            --output none 2>/dev/null
        az appconfig feature enable \
            --endpoint "$ENDPOINT" \
            --feature "$key" \
            $label_arg \
            --auth-mode login \
            --yes \
            --output none 2>/dev/null
    else
        az appconfig feature set \
            --endpoint "$ENDPOINT" \
            --feature "$key" \
            $label_arg \
            --auth-mode login \
            --yes \
            --output none 2>/dev/null
        az appconfig feature disable \
            --endpoint "$ENDPOINT" \
            --feature "$key" \
            $label_arg \
            --auth-mode login \
            --yes \
            --output none 2>/dev/null
    fi
}

# ============================================================================
# Main
# ============================================================================

echo ""
echo "╭─────────────────────────────────────────────────────────────"
echo "│ 📦 App Configuration Sync"
echo "├─────────────────────────────────────────────────────────────"
info "Endpoint: $ENDPOINT"
info "Label: ${LABEL:-<none>}"
info "Config: $CONFIG_FILE"
[[ "$DRY_RUN" == "true" ]] && warn "DRY RUN - no changes will be made"
echo "├─────────────────────────────────────────────────────────────"

count=0
errors=0

# ============================================================================
# SECTION 1: Infrastructure Keys from azd env
# ============================================================================
log ""
log "Syncing infrastructure keys from azd env..."

# Helper to get azd env value and set it
sync_infra_key() {
    local app_key="$1"
    local env_var="$2"
    local value
    value=$(azd env get-value "$env_var" 2>/dev/null || echo "")
    if [[ -n "$value" ]]; then
        if set_key "$app_key" "$value"; then
            count=$((count + 1))
            log "  ✓ $app_key"
        else
            errors=$((errors + 1))
            warn "Failed to set: $app_key"
        fi
    else
        log "  ⊘ $app_key (not set)"
    fi
}

# Helper for Key Vault references
sync_keyvault_ref() {
    local app_key="$1"
    local secret_name="$2"
    local kv_uri
    kv_uri=$(azd env get-value AZURE_KEY_VAULT_ENDPOINT 2>/dev/null || echo "")
    if [[ -n "$kv_uri" ]]; then
        local ref_value="{\"uri\":\"${kv_uri}secrets/${secret_name}\"}"
        local label_arg=""
        [[ -n "$LABEL" ]] && label_arg="--label $LABEL"
        
        if [[ "$DRY_RUN" == "true" ]]; then
            log "  [DRY-RUN] Would set KV ref: $app_key"
            return 0
        fi
        
        if az appconfig kv set-keyvault \
            --endpoint "$ENDPOINT" \
            --key "$app_key" \
            --secret-identifier "${kv_uri}secrets/${secret_name}" \
            $label_arg \
            --auth-mode login \
            --yes \
            --output none 2>/dev/null; then
            count=$((count + 1))
            log "  ✓ $app_key (KV ref)"
        else
            errors=$((errors + 1))
            warn "Failed to set KV ref: $app_key"
        fi
    fi
}

# Azure OpenAI
sync_infra_key "azure/openai/endpoint" "AZURE_OPENAI_ENDPOINT"
sync_infra_key "azure/openai/deployment-id" "AZURE_OPENAI_CHAT_DEPLOYMENT_ID"
sync_infra_key "azure/openai/api-version" "AZURE_OPENAI_API_VERSION"

# Azure Speech
sync_infra_key "azure/speech/endpoint" "AZURE_SPEECH_ENDPOINT"
sync_infra_key "azure/speech/region" "AZURE_SPEECH_REGION"
sync_infra_key "azure/speech/resource-id" "AZURE_SPEECH_RESOURCE_ID"

# Azure Communication Services
sync_infra_key "azure/acs/endpoint" "ACS_ENDPOINT"
sync_infra_key "azure/acs/immutable-id" "ACS_IMMUTABLE_ID"
sync_keyvault_ref "azure/acs/connection-string" "acs-connection-string"

# Redis
sync_infra_key "azure/redis/hostname" "REDIS_HOSTNAME"
sync_infra_key "azure/redis/port" "REDIS_PORT"

# Cosmos DB
sync_infra_key "azure/cosmos/database-name" "AZURE_COSMOS_DATABASE_NAME"
sync_infra_key "azure/cosmos/collection-name" "AZURE_COSMOS_COLLECTION_NAME"
sync_infra_key "azure/cosmos/connection-string" "AZURE_COSMOS_CONNECTION_STRING"

# Storage
sync_infra_key "azure/storage/account-name" "AZURE_STORAGE_ACCOUNT_NAME"
sync_infra_key "azure/storage/container-url" "AZURE_STORAGE_CONTAINER_URL"

# App Insights
sync_infra_key "azure/appinsights/connection-string" "APPLICATIONINSIGHTS_CONNECTION_STRING"

# Voice Live (optional)
sync_infra_key "azure/voicelive/endpoint" "AZURE_VOICELIVE_ENDPOINT"
sync_infra_key "azure/voicelive/model" "AZURE_VOICELIVE_MODEL"
sync_infra_key "azure/voicelive/resource-id" "AZURE_VOICELIVE_RESOURCE_ID"

# Environment metadata
sync_infra_key "app/environment" "AZURE_ENV_NAME"

# ============================================================================
# SECTION 2: Application Settings from config/appconfig.json
# ============================================================================
log ""
log "Syncing application settings from config file..."

# Process each section
for section in pools connections session voice aoai warm-pool monitoring; do
    # Get all keys in section
    keys=$(jq -r ".[\"$section\"] // {} | keys[]" "$CONFIG_FILE" 2>/dev/null || echo "")
    for key in $keys; do
        value=$(jq -r ".[\"$section\"][\"$key\"]" "$CONFIG_FILE")
        full_key="app/$section/$key"
        if set_key "$full_key" "$value"; then
            count=$((count + 1))
            log "  ✓ $full_key"
        else
            errors=$((errors + 1))
            warn "Failed to set: $full_key"
        fi
    done
done

# ============================================================================
# SECTION 3: Feature Flags
# ============================================================================
log ""
log "Syncing feature flags..."
features=$(jq -r '.features // {} | keys[]' "$CONFIG_FILE" 2>/dev/null || echo "")
for feature in $features; do
    enabled=$(jq -r ".features[\"$feature\"]" "$CONFIG_FILE")
    if set_feature "$feature" "$enabled"; then
        count=$((count + 1))
        log "  ✓ $feature = $enabled"
    else
        errors=$((errors + 1))
        warn "Failed to set feature: $feature"
    fi
done

# Trigger refresh
if [[ "$DRY_RUN" != "true" ]]; then
    set_key "app/sentinel" "v$(date +%s)" || true
fi

echo "├─────────────────────────────────────────────────────────────"
if [[ $errors -eq 0 ]]; then
    success "Synced $count settings"
else
    warn "Synced $count settings with $errors errors"
fi
echo "╰─────────────────────────────────────────────────────────────"
echo ""
