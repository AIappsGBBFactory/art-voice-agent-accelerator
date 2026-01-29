#!/bin/bash
# ============================================================================
# 🎤 Speech Containers Setup Script (Beta)
# ============================================================================
# Configures Azure Speech Container deployment on ACI with optional TLS.
# Called from preprovision.sh for the Terraform provider.
#
# Features:
#   - Enables/disables Speech containers (STT/TTS) on Azure Container Instances
#   - Optional TLS termination via nginx sidecar
#   - Auto-generates self-signed certificates or accepts user-provided certs
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly LOG_IN_BOX="${AZD_LOG_IN_BOX:-false}"

# ============================================================================
# Logging (inherited style from parent scripts)
# ============================================================================

if [[ -z "${BLUE+x}" ]]; then BLUE=$'\033[0;34m'; fi
if [[ -z "${GREEN+x}" ]]; then GREEN=$'\033[0;32m'; fi
if [[ -z "${GREEN_BOLD+x}" ]]; then GREEN_BOLD=$'\033[1;32m'; fi
if [[ -z "${YELLOW+x}" ]]; then YELLOW=$'\033[1;33m'; fi
if [[ -z "${RED+x}" ]]; then RED=$'\033[0;31m'; fi
if [[ -z "${CYAN+x}" ]]; then CYAN=$'\033[0;36m'; fi
if [[ -z "${DIM+x}" ]]; then DIM=$'\033[2m'; fi
if [[ -z "${NC+x}" ]]; then NC=$'\033[0m'; fi
readonly BLUE GREEN GREEN_BOLD YELLOW RED CYAN DIM NC

log()          { printf '│ %s%s%s\n' "$DIM" "$*" "$NC"; }
info()         { printf '│ %s%s%s\n' "$BLUE" "$*" "$NC"; }
success()      { printf '│ %s✔%s %s\n' "$GREEN" "$NC" "$*"; }
phase_success(){ printf '│ %s✔ %s%s\n' "$GREEN_BOLD" "$*" "$NC"; }
warn()         { printf '│ %s⚠%s  %s\n' "$YELLOW" "$NC" "$*"; }
fail()         { printf '│ %s✖%s %s\n' "$RED" "$NC" "$*" >&2; }

header() {
    if [[ "$LOG_IN_BOX" == "true" ]]; then
        printf '│ %s%s%s\n' "$CYAN" "$*" "$NC"
        return
    fi
    echo ""
    echo "╭─────────────────────────────────────────────────────────────"
    echo "│ ${CYAN}$*${NC}"
    echo "├─────────────────────────────────────────────────────────────"
}

footer() {
    if [[ "$LOG_IN_BOX" == "true" ]]; then
        return
    fi
    echo "╰─────────────────────────────────────────────────────────────"
    echo ""
}

prompt() {
    local prompt_text="$1"
    local __var="$2"
    if [[ "$LOG_IN_BOX" == "true" ]]; then
        read -rp "│ ${prompt_text}" "$__var"
    else
        read -rp "${prompt_text}" "$__var"
    fi
}

is_ci() {
    [[ "${CI:-}" == "true" || "${GITHUB_ACTIONS:-}" == "true" || "${AZD_SKIP_INTERACTIVE:-}" == "true" ]]
}

# Helper to safely get azd env value
get_azd_env_value() {
    local value
    value=$(azd env get-value "$1" 2>/dev/null | head -n1)
    local exit_code=${PIPESTATUS[0]}
    if [[ $exit_code -ne 0 ]] || [[ -z "$value" ]] || [[ "$value" == ERROR:* ]] || [[ "$value" == *"not found"* ]]; then
        echo ""
    else
        echo "$value"
    fi
}

# ============================================================================
# Certificate Generation
# ============================================================================

generate_self_signed_cert() {
    local fqdn_prefix="$1"
    local location="${2:-eastus}"
    local temp_dir
    temp_dir=$(mktemp -d)
    
    local cert_file="$temp_dir/ssl.crt"
    local key_file="$temp_dir/ssl.key"
    local csr_file="$temp_dir/ssl.csr"
    
    log "Generating self-signed TLS certificate..."
    
    # Get environment name for DNS names
    local env_name="${AZURE_ENV_NAME:-dev}"
    
    # Generate private key
    openssl genrsa -out "$key_file" 2048 2>/dev/null
    
    # Generate CSR with SAN (Subject Alternative Names)
    cat > "$temp_dir/ssl.cnf" << EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = ${fqdn_prefix}-speech.${location}.azurecontainer.io
O = Azure Speech Containers
OU = Voice Agent Accelerator

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${fqdn_prefix}-stt-*.${location}.azurecontainer.io
DNS.2 = ${fqdn_prefix}-tts-*.${location}.azurecontainer.io
DNS.3 = localhost
EOF
    
    # Generate CSR
    openssl req -new -key "$key_file" -out "$csr_file" -config "$temp_dir/ssl.cnf" 2>/dev/null
    
    # Generate self-signed certificate (valid for 1 year)
    openssl x509 -req -days 365 -in "$csr_file" -signkey "$key_file" -out "$cert_file" \
        -extensions req_ext -extfile "$temp_dir/ssl.cnf" 2>/dev/null
    
    # Base64 encode
    local cert_base64 key_base64
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS base64 doesn't have -w option
        cert_base64=$(base64 -i "$cert_file")
        key_base64=$(base64 -i "$key_file")
    else
        # Linux base64
        cert_base64=$(base64 -w0 "$cert_file")
        key_base64=$(base64 -w0 "$key_file")
    fi
    
    # Clean up temp files
    rm -rf "$temp_dir"
    
    # Return values via global variables (bash limitation)
    GENERATED_CERT_BASE64="$cert_base64"
    GENERATED_KEY_BASE64="$key_base64"
    
    success "Generated self-signed TLS certificate"
}

# ============================================================================
# Voice and Locale Selection
# ============================================================================
# Curated list of popular TTS voices and STT locales.
# Container tags follow the pattern:
#   TTS: <version>-amd64-<locale>-<voicename>neural
#   STT: <version>-amd64-<locale>
# See: https://mcr.microsoft.com/artifact/mar/azure-cognitive-services/speechservices/neural-text-to-speech/tags
# ============================================================================

# TTS voice options: display_name|locale|voice_name|container_tag_suffix
# Container tag suffix format: <locale>-<voicename>neural (version prefix added dynamically)
readonly TTS_VOICES=(
    "Jenny (US English, Female)|en-US|JennyNeural|en-us-jennyneural"
    "Aria (US English, Female)|en-US|AriaNeural|en-us-arianeural"
    "Guy (US English, Male)|en-US|GuyNeural|en-us-guyneural"
    "Davis (US English, Male)|en-US|DavisNeural|en-us-davisneural"
    "Sonia (British English, Female)|en-GB|SoniaNeural|en-gb-sonianeural"
    "Ryan (British English, Male)|en-GB|RyanNeural|en-gb-ryanneural"
    "Natasha (Australian English, Female)|en-AU|NatashNeural|en-au-natashaneural"
    "Xiaoxiao (Chinese Mandarin, Female)|zh-CN|XiaoxiaoNeural|zh-cn-xiaoxiaoneural"
    "Xiaoyi (Chinese Mandarin, Female)|zh-CN|XiaoyiNeural|zh-cn-xiaoyineural"
    "Elvira (Spanish Spain, Female)|es-ES|ElviraNeural|es-es-elviraneural"
    "Alvaro (Spanish Spain, Male)|es-ES|AlvaroNeural|es-es-alvaroneural"
    "Dalia (Mexican Spanish, Female)|es-MX|DaliaNeural|es-mx-dalianeural"
    "Denise (French, Female)|fr-FR|DeniseNeural|fr-fr-deniseneural"
    "Henri (French, Male)|fr-FR|HenriNeural|fr-fr-henrineural"
    "Katja (German, Female)|de-DE|KatjaNeural|de-de-katjaneural"
    "Serafina (Italian, Female)|it-IT|SerafinaNeural|it-it-serafinaneural"
    "Nanami (Japanese, Female)|ja-JP|NanamiNeural|ja-jp-nanamineural"
    "SunHi (Korean, Female)|ko-KR|SunHiNeural|ko-kr-sunhineural"
    "Fernanda (Brazilian Portuguese, Female)|pt-BR|FranciscaNeural|pt-br-franciscaneural"
)

# STT locale options: display_name|locale|container_tag_suffix
readonly STT_LOCALES=(
    "English (United States)|en-US|en-us"
    "English (United Kingdom)|en-GB|en-gb"
    "English (Australia)|en-AU|en-au"
    "Chinese (Mandarin, Simplified)|zh-CN|zh-cn"
    "Spanish (Spain)|es-ES|es-es"
    "Spanish (Mexico)|es-MX|es-mx"
    "French (France)|fr-FR|fr-fr"
    "German (Germany)|de-DE|de-de"
    "Italian (Italy)|it-IT|it-it"
    "Japanese (Japan)|ja-JP|ja-jp"
    "Korean (Korea)|ko-KR|ko-kr"
    "Portuguese (Brazil)|pt-BR|pt-br"
)

# Current container versions (update these when new versions are released)
readonly TTS_CONTAINER_VERSION="2.21.0"
readonly STT_CONTAINER_VERSION="4.8.0"

select_voice_and_locale() {
    log ""
    log "🎙️ Voice Selection"
    log "=================="
    log ""
    log "Choose a voice for the Text-to-Speech (TTS) container."
    log "Each voice requires a separate container image (~5-8GB)."
    log ""
    log "${DIM}Note: In beta, only one TTS voice is deployed per environment.${NC}"
    log ""
    
    # Display TTS voice options
    local i=1
    for voice in "${TTS_VOICES[@]}"; do
        IFS='|' read -r display_name locale voice_name tag_suffix <<< "$voice"
        printf '│   %s%2d)%s %s\n' "$CYAN" "$i" "$NC" "$display_name"
        ((i++))
    done
    
    log ""
    prompt "Select TTS voice (1-${#TTS_VOICES[@]}) [1 for Jenny]: " tts_choice
    tts_choice="${tts_choice:-1}"
    
    # Validate choice
    if ! [[ "$tts_choice" =~ ^[0-9]+$ ]] || (( tts_choice < 1 || tts_choice > ${#TTS_VOICES[@]} )); then
        warn "Invalid choice, defaulting to Jenny (US English)"
        tts_choice=1
    fi
    
    # Parse selected voice
    local selected_voice="${TTS_VOICES[$((tts_choice-1))]}"
    IFS='|' read -r tts_display_name tts_locale tts_voice_name tts_tag_suffix <<< "$selected_voice"
    
    # Construct full container tag
    local tts_container_tag="${TTS_CONTAINER_VERSION}-amd64-${tts_tag_suffix}"
    
    azd env set TF_VAR_tts_container_tag "$tts_container_tag"
    success "TTS Voice: $tts_display_name"
    log "   Container tag: $tts_container_tag"
    
    # STT Locale Selection
    log ""
    log "🎧 Speech Recognition Locale"
    log "============================"
    log ""
    log "Choose a locale for the Speech-to-Text (STT) container."
    log "This determines what language/accent the system will recognize."
    log ""
    
    # Find matching STT locale based on TTS selection
    local default_stt_choice=1
    i=1
    for locale_entry in "${STT_LOCALES[@]}"; do
        IFS='|' read -r display_name locale tag_suffix <<< "$locale_entry"
        printf '│   %s%2d)%s %s\n' "$CYAN" "$i" "$NC" "$display_name"
        # Set default to match TTS locale if possible
        if [[ "$locale" == "$tts_locale" ]]; then
            default_stt_choice=$i
        fi
        ((i++))
    done
    
    log ""
    prompt "Select STT locale (1-${#STT_LOCALES[@]}) [$default_stt_choice]: " stt_choice
    stt_choice="${stt_choice:-$default_stt_choice}"
    
    # Validate choice
    if ! [[ "$stt_choice" =~ ^[0-9]+$ ]] || (( stt_choice < 1 || stt_choice > ${#STT_LOCALES[@]} )); then
        warn "Invalid choice, defaulting to English (United States)"
        stt_choice=1
    fi
    
    # Parse selected locale
    local selected_locale="${STT_LOCALES[$((stt_choice-1))]}"
    IFS='|' read -r stt_display_name stt_locale stt_tag_suffix <<< "$selected_locale"
    
    # Construct full container tag
    local stt_container_tag="${STT_CONTAINER_VERSION}-amd64-${stt_tag_suffix}"
    
    azd env set TF_VAR_stt_container_tag "$stt_container_tag"
    success "STT Locale: $stt_display_name"
    log "   Container tag: $stt_container_tag"
    
    # Show summary
    log ""
    log "📋 Voice Configuration Summary"
    log "==============================="
    log "   TTS: $tts_display_name ($tts_voice_name)"
    log "   STT: $stt_display_name"
    log ""
}

# ============================================================================
# Main Setup Function
# ============================================================================

setup_speech_containers() {
    header "🎤 Speech Containers Configuration (Beta)"
    
    # Check existing configuration
    local existing_enabled
    existing_enabled=$(get_azd_env_value TF_VAR_enable_speech_containers)
    
    # Check TLS configuration early 
    local existing_tls
    existing_tls=$(get_azd_env_value TF_VAR_speech_container_enable_tls)
    
    if [[ "$existing_enabled" == "true" ]]; then
        success "Speech containers already enabled"
        
        # Show existing voice configuration
        local existing_tts_tag
        existing_tts_tag=$(get_azd_env_value TF_VAR_tts_container_tag)
        if [[ -n "$existing_tts_tag" ]]; then
            log "   TTS container: $existing_tts_tag"
        fi
        
        local existing_stt_tag
        existing_stt_tag=$(get_azd_env_value TF_VAR_stt_container_tag)
        if [[ -n "$existing_stt_tag" ]]; then
            log "   STT container: $existing_stt_tag"
        fi
        
        # Show TLS configuration status
        if [[ "$existing_tls" == "true" ]]; then
            success "TLS termination: enabled (HTTPS/WSS)"
        else
            log "   TLS termination: disabled (HTTP/WS)"
        fi
        
        log ""
        prompt "Would you like to reconfigure speech containers? (y/n): " reconfigure
        
        if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
            log "Keeping existing configuration"
            footer
            return 0
        fi
        
        # User wants to reconfigure - clear existing TLS settings if they exist
        if [[ "$existing_tls" == "true" ]]; then
            log ""
            prompt "Would you also like to reconfigure TLS settings? (y/n): " reconfigure_tls
            if [[ "$reconfigure_tls" =~ ^[Yy]$ ]]; then
                # Clear TLS settings so they get re-prompted
                azd env set TF_VAR_speech_container_enable_tls ""
                azd env set TF_VAR_speech_container_tls_cert_base64 ""
                azd env set TF_VAR_speech_container_tls_key_base64 ""
                existing_tls=""
                info "TLS settings cleared - you'll be prompted to reconfigure"
            fi
        fi
    fi
    
    # In CI mode, check for environment variables
    if is_ci; then
        info "CI/CD mode: Using environment variables for speech container config"
        
        if [[ "${ENABLE_SPEECH_CONTAINERS:-}" == "true" ]]; then
            azd env set TF_VAR_enable_speech_containers "true"
            success "Speech containers enabled via CI environment"
            
            # Voice/Locale configuration from CI env vars
            # TTS_CONTAINER_TAG can be full tag or just voice suffix
            if [[ -n "${TTS_CONTAINER_TAG:-}" ]]; then
                azd env set TF_VAR_tts_container_tag "$TTS_CONTAINER_TAG"
                success "TTS container tag: $TTS_CONTAINER_TAG"
            else
                # Default to Jenny (US English)
                local default_tts="${TTS_CONTAINER_VERSION}-amd64-en-us-jennyneural"
                azd env set TF_VAR_tts_container_tag "$default_tts"
                info "Using default TTS voice: Jenny (en-US)"
            fi
            
            # STT_CONTAINER_TAG can be full tag or just locale suffix
            if [[ -n "${STT_CONTAINER_TAG:-}" ]]; then
                azd env set TF_VAR_stt_container_tag "$STT_CONTAINER_TAG"
                success "STT container tag: $STT_CONTAINER_TAG"
            else
                # Default to US English
                local default_stt="${STT_CONTAINER_VERSION}-amd64-en-us"
                azd env set TF_VAR_stt_container_tag "$default_stt"
                info "Using default STT locale: en-US"
            fi
            
            if [[ "${SPEECH_CONTAINER_ENABLE_TLS:-}" == "true" ]]; then
                azd env set TF_VAR_speech_container_enable_tls "true"
                
                # Check for provided certificates
                if [[ -n "${SPEECH_CONTAINER_TLS_CERT_BASE64:-}" && -n "${SPEECH_CONTAINER_TLS_KEY_BASE64:-}" ]]; then
                    azd env set TF_VAR_speech_container_tls_cert_base64 "$SPEECH_CONTAINER_TLS_CERT_BASE64"
                    azd env set TF_VAR_speech_container_tls_key_base64 "$SPEECH_CONTAINER_TLS_KEY_BASE64"
                    success "TLS certificates configured from CI environment"
                else
                    info "No TLS certificates provided - Terraform will generate self-signed"
                fi
            fi
        else
            azd env set TF_VAR_enable_speech_containers "false"
            info "Speech containers disabled in CI environment"
        fi
        
        footer
        return 0
    fi
    
    # Interactive setup
    log ""
    log "🧪 ${YELLOW}BETA FEATURE${NC}: Self-hosted Azure Speech containers on ACI"
    log ""
    log "This feature deploys Speech-to-Text (STT) and Text-to-Speech (TTS)"
    log "containers on Azure Container Instances for lower latency and"
    log "data residency requirements."
    log ""
    log "Benefits:"
    log "  • Reduced network latency (containers in your Azure region)"
    log "  • Data stays within your Azure environment"
    log "  • Predictable performance with dedicated resources"
    log ""
    log "Considerations:"
    log "  • Additional compute costs (~\$200-400/month for recommended SKUs)"
    log "  • Requires Speech Services cognitive account for billing"
    log "  • Container startup time: 1-2 minutes for model loading"
    log ""
    
    prompt "Would you like to enable Speech containers? (y/n): " enable_containers
    
    if [[ ! "$enable_containers" =~ ^[Yy]$ ]]; then
        log ""
        info "Speech containers will not be deployed"
        azd env set TF_VAR_enable_speech_containers "false"
        footer
        return 0
    fi
    
    # Enable speech containers
    azd env set TF_VAR_enable_speech_containers "true"
    success "Speech containers will be deployed"
    
    # Voice/Locale Selection
    select_voice_and_locale
    
    # TLS Configuration - skip if already configured
    if [[ "$existing_tls" == "true" ]]; then
        log ""
        success "TLS already configured (HTTPS/WSS enabled)"
        log ""
        log "   To reconfigure TLS, run:"
        log "   ${CYAN}azd env set TF_VAR_speech_container_enable_tls \"\"${NC}"
        log "   ${CYAN}azd env set TF_VAR_speech_container_tls_cert_base64 \"\"${NC}"
        log "   ${CYAN}azd env set TF_VAR_speech_container_tls_key_base64 \"\"${NC}"
        log "   Then re-run: ${CYAN}azd provision${NC}"
        log ""
        phase_success "Speech containers configuration complete"
        footer
        return 0
    fi
    
    # TLS Configuration
    log ""
    log "🔒 TLS Configuration"
    log "===================="
    log ""
    log "By default, speech containers expose HTTP/WebSocket endpoints."
    log "You can enable TLS termination via nginx sidecar for HTTPS/WSS."
    log ""
    log "TLS is recommended if:"
    log "  • Containers are publicly accessible (external ingress)"
    log "  • You need encrypted communication for compliance"
    log ""
    log "TLS may be skipped if:"
    log "  • Containers are only accessed within a private VNet"
    log "  • You're testing/developing locally"
    log ""
    
    prompt "Would you like to enable TLS (HTTPS/WSS) for speech containers? (y/n): " enable_tls
    
    if [[ ! "$enable_tls" =~ ^[Yy]$ ]]; then
        log ""
        info "Speech containers will use HTTP/WS (unencrypted)"
        azd env set TF_VAR_speech_container_enable_tls "false"
        footer
        return 0
    fi
    
    # TLS enabled - check for existing cert or generate
    azd env set TF_VAR_speech_container_enable_tls "true"
    success "TLS termination will be enabled"
    
    log ""
    log "📜 TLS Certificate Options"
    log "=========================="
    log ""
    log "1. Generate self-signed certificate (for dev/test)"
    log "2. Provide your own certificate (for production)"
    log "3. Let Terraform generate certificate during deployment"
    log ""
    
    prompt "Choose certificate option (1/2/3) [3]: " cert_option
    cert_option="${cert_option:-3}"
    
    case "$cert_option" in
        1)
            log ""
            log "Generating self-signed certificate..."
            
            # Get location for DNS names
            local location
            location=$(get_azd_env_value AZURE_LOCATION)
            location="${location:-eastus}"
            
            # Get project name for DNS prefix
            local name
            name=$(get_azd_env_value TF_VAR_name)
            name="${name:-artagent}"
            
            generate_self_signed_cert "$name" "$location"
            
            azd env set TF_VAR_speech_container_tls_cert_base64 "$GENERATED_CERT_BASE64"
            azd env set TF_VAR_speech_container_tls_key_base64 "$GENERATED_KEY_BASE64"
            
            success "Self-signed certificate generated and configured"
            warn "Note: Browsers will show security warnings for self-signed certs"
            ;;
        2)
            log ""
            log "🔑 Provide Your TLS Certificate"
            log "================================"
            log ""
            log "You'll need:"
            log "  • PEM-encoded certificate file (ssl.crt)"
            log "  • PEM-encoded private key file (ssl.key)"
            log ""
            
            prompt "Path to certificate file (ssl.crt): " cert_path
            prompt "Path to private key file (ssl.key): " key_path
            
            if [[ -f "$cert_path" && -f "$key_path" ]]; then
                local cert_base64 key_base64
                if [[ "$(uname)" == "Darwin" ]]; then
                    cert_base64=$(base64 -i "$cert_path")
                    key_base64=$(base64 -i "$key_path")
                else
                    cert_base64=$(base64 -w0 "$cert_path")
                    key_base64=$(base64 -w0 "$key_path")
                fi
                
                azd env set TF_VAR_speech_container_tls_cert_base64 "$cert_base64"
                azd env set TF_VAR_speech_container_tls_key_base64 "$key_base64"
                
                success "TLS certificate and key configured"
            else
                warn "Certificate files not found"
                log "You can set them later via:"
                log "  azd env set TF_VAR_speech_container_tls_cert_base64 '<base64-cert>'"
                log "  azd env set TF_VAR_speech_container_tls_key_base64 '<base64-key>'"
                log ""
                info "Terraform will generate a self-signed certificate during deployment"
            fi
            ;;
        3|*)
            log ""
            info "Terraform will generate a self-signed certificate during deployment"
            log "The certificate will be stored in Terraform state."
            ;;
    esac
    
    log ""
    phase_success "Speech containers configuration complete"
    footer
}

# ============================================================================
# Main
# ============================================================================

setup_speech_containers "$@"
