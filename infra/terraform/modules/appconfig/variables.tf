# ============================================================================
# APP CONFIGURATION MODULE - VARIABLES
# ============================================================================

variable "name" {
  description = "Name for the App Configuration resource"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region for the App Configuration"
  type        = string
}

variable "environment_name" {
  description = "Environment name (dev, staging, prod) - used as label"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "sku" {
  description = "SKU for App Configuration (free or standard)"
  type        = string
  default     = "standard"
  validation {
    condition     = contains(["free", "standard"], var.sku)
    error_message = "SKU must be 'free' or 'standard'."
  }
}

# ============================================================================
# IDENTITY VARIABLES
# ============================================================================

variable "backend_identity_principal_id" {
  description = "Principal ID of the backend managed identity"
  type        = string
}

variable "frontend_identity_principal_id" {
  description = "Principal ID of the frontend managed identity"
  type        = string
}

variable "deployer_principal_id" {
  description = "Principal ID of the deployer (for admin access)"
  type        = string
}

variable "deployer_principal_type" {
  description = "Type of deployer principal (User or ServicePrincipal)"
  type        = string
  default     = "User"
}

# ============================================================================
# KEY VAULT INTEGRATION
# ============================================================================

variable "key_vault_id" {
  description = "Resource ID of the Key Vault for secret references"
  type        = string
}

variable "key_vault_uri" {
  description = "URI of the Key Vault for secret references"
  type        = string
}

# ============================================================================
# AZURE SERVICE ENDPOINTS
# ============================================================================

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint"
  type        = string
  default     = ""
}

variable "azure_openai_deployment_id" {
  description = "Azure OpenAI chat deployment ID"
  type        = string
  default     = "gpt-4o"
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2025-01-01-preview"
}

variable "azure_speech_endpoint" {
  description = "Azure Speech Services endpoint"
  type        = string
  default     = ""
}

variable "azure_speech_region" {
  description = "Azure Speech Services region"
  type        = string
  default     = ""
}

variable "azure_speech_resource_id" {
  description = "Azure Speech Services resource ID"
  type        = string
  default     = ""
}

variable "acs_endpoint" {
  description = "Azure Communication Services endpoint"
  type        = string
  default     = ""
}

variable "acs_immutable_id" {
  description = "Azure Communication Services immutable resource ID"
  type        = string
  default     = ""
}

variable "acs_source_phone_number" {
  description = "ACS source phone number for outbound calls"
  type        = string
  default     = ""
}

variable "redis_hostname" {
  description = "Redis Enterprise hostname"
  type        = string
  default     = ""
}

variable "redis_port" {
  description = "Redis port"
  type        = number
  default     = 10000
}

variable "cosmos_database_name" {
  description = "Cosmos DB database name"
  type        = string
  default     = "audioagentdb"
}

variable "cosmos_collection_name" {
  description = "Cosmos DB collection name"
  type        = string
  default     = "audioagentcollection"
}

variable "storage_account_name" {
  description = "Storage account name"
  type        = string
  default     = ""
}

variable "storage_container_url" {
  description = "Storage container URL"
  type        = string
  default     = ""
}

# ============================================================================
# VOICE LIVE (OPTIONAL)
# ============================================================================

variable "voice_live_endpoint" {
  description = "Azure Voice Live endpoint (if enabled)"
  type        = string
  default     = ""
}

variable "voice_live_model" {
  description = "Azure Voice Live model name"
  type        = string
  default     = ""
}

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

variable "pool_size_tts" {
  description = "TTS pool size"
  type        = number
  default     = 50
}

variable "pool_size_stt" {
  description = "STT pool size"
  type        = number
  default     = 50
}

variable "aoai_pool_size" {
  description = "Azure OpenAI pool size"
  type        = number
  default     = 50
}

variable "pool_low_water_mark" {
  description = "Pool low water mark threshold"
  type        = number
  default     = 10
}

variable "pool_high_water_mark" {
  description = "Pool high water mark threshold"
  type        = number
  default     = 45
}

variable "pool_acquire_timeout" {
  description = "Pool acquire timeout in seconds"
  type        = number
  default     = 5
}

variable "max_websocket_connections" {
  description = "Maximum WebSocket connections"
  type        = number
  default     = 200
}

variable "connection_queue_size" {
  description = "Connection queue size"
  type        = number
  default     = 50
}

variable "connection_warning_threshold" {
  description = "Connection warning threshold"
  type        = number
  default     = 150
}

variable "connection_critical_threshold" {
  description = "Connection critical threshold"
  type        = number
  default     = 180
}

variable "connection_timeout_seconds" {
  description = "Connection timeout in seconds"
  type        = number
  default     = 300
}

variable "heartbeat_interval_seconds" {
  description = "Heartbeat interval in seconds"
  type        = number
  default     = 30
}

variable "session_ttl_seconds" {
  description = "Session TTL in seconds"
  type        = number
  default     = 1800
}

variable "session_cleanup_interval" {
  description = "Session cleanup interval in seconds"
  type        = number
  default     = 300
}

variable "session_state_ttl" {
  description = "Session state TTL in seconds"
  type        = number
  default     = 86400
}

variable "max_concurrent_sessions" {
  description = "Maximum concurrent sessions"
  type        = number
  default     = 1000
}

variable "container_min_replicas" {
  description = "Container app minimum replicas"
  type        = number
  default     = 5
}

variable "container_max_replicas" {
  description = "Container app maximum replicas"
  type        = number
  default     = 50
}

# ============================================================================
# VOICE & TTS SETTINGS
# ============================================================================

variable "tts_sample_rate_ui" {
  description = "TTS sample rate for UI clients"
  type        = number
  default     = 48000
}

variable "tts_sample_rate_acs" {
  description = "TTS sample rate for ACS (telephony)"
  type        = number
  default     = 16000
}

variable "tts_chunk_size" {
  description = "TTS audio chunk size in bytes"
  type        = number
  default     = 1024
}

variable "tts_processing_timeout" {
  description = "TTS processing timeout in seconds"
  type        = number
  default     = 8
}

variable "stt_processing_timeout" {
  description = "STT processing timeout in seconds"
  type        = number
  default     = 10
}

variable "silence_duration_ms" {
  description = "Silence duration for VAD in milliseconds"
  type        = number
  default     = 1300
}

variable "recognized_languages" {
  description = "Comma-separated list of supported languages for recognition"
  type        = string
  default     = "en-US,es-ES,fr-FR,ko-KR,it-IT,pt-PT,pt-BR"
}

variable "default_tts_voice" {
  description = "Default TTS voice (fallback when agent voice not available)"
  type        = string
  default     = "en-US-EmmaMultilingualNeural"
}

# ============================================================================
# AZURE OPENAI BEHAVIOR SETTINGS
# ============================================================================

variable "aoai_default_temperature" {
  description = "Default LLM temperature for response randomness"
  type        = number
  default     = 0.7
}

variable "aoai_default_max_tokens" {
  description = "Default maximum tokens per response"
  type        = number
  default     = 500
}

variable "aoai_request_timeout" {
  description = "AOAI request timeout in seconds"
  type        = number
  default     = 30
}

# ============================================================================
# WARM POOL SETTINGS
# ============================================================================

variable "warm_pool_tts_size" {
  description = "Pre-warmed TTS pool size for low latency"
  type        = number
  default     = 3
}

variable "warm_pool_stt_size" {
  description = "Pre-warmed STT pool size for low latency"
  type        = number
  default     = 2
}

variable "warm_pool_refresh_interval" {
  description = "Warm pool refresh interval in seconds"
  type        = number
  default     = 30
}

variable "warm_pool_session_max_age" {
  description = "Maximum age for warm pool sessions in seconds"
  type        = number
  default     = 1800
}

# ============================================================================
# MONITORING SETTINGS
# ============================================================================

variable "metrics_collection_interval" {
  description = "Metrics collection interval in seconds"
  type        = number
  default     = 60
}

variable "pool_metrics_interval" {
  description = "Pool metrics collection interval in seconds"
  type        = number
  default     = 30
}

# ============================================================================
# FEATURE FLAGS
# ============================================================================

variable "feature_dtmf_validation" {
  description = "Enable DTMF validation feature"
  type        = bool
  default     = false
}

variable "feature_auth_validation" {
  description = "Enable authentication validation"
  type        = bool
  default     = false
}

variable "feature_call_recording" {
  description = "Enable ACS call recording"
  type        = bool
  default     = false
}

variable "feature_warm_pool" {
  description = "Enable warm pool for low-latency connections"
  type        = bool
  default     = true
}

variable "feature_session_persistence" {
  description = "Enable session persistence"
  type        = bool
  default     = true
}

variable "feature_performance_logging" {
  description = "Enable performance logging"
  type        = bool
  default     = true
}

variable "feature_tracing" {
  description = "Enable distributed tracing"
  type        = bool
  default     = true
}

variable "feature_connection_limits" {
  description = "Enable WebSocket connection limits"
  type        = bool
  default     = true
}

# ============================================================================
# APPLICATION URL CONFIGURATION
# ============================================================================
# These are set by postprovision after deployment completes.
# Initial values can be empty or placeholder; the App Config keys use
# lifecycle { ignore_changes = [value] } to prevent Terraform overwriting.
# ============================================================================

variable "backend_base_url" {
  description = "Backend application public URL (set by postprovision)"
  type        = string
  default     = ""
}

# ============================================================================
# SECRETS (Key Vault References)
# ============================================================================

variable "acs_connection_string_secret_id" {
  description = "Key Vault secret ID for ACS connection string"
  type        = string
  default     = ""
}

variable "cosmos_connection_string" {
  description = "Cosmos DB connection string (with OIDC auth)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "appinsights_connection_string" {
  description = "Application Insights connection string"
  type        = string
  default     = ""
}
