# ============================================================================
# APP CONFIGURATION KEYS - SERVICE ENDPOINTS & SETTINGS
# ============================================================================
# Non-sensitive configuration values stored directly in App Configuration.
# Organized by Azure service domain for clarity.
# ============================================================================

# ============================================================================
# AZURE OPENAI CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "openai_endpoint" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/endpoint"
  label                  = local.label
  value                  = var.azure_openai_endpoint
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "openai_deployment" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/deployment-id"
  label                  = local.label
  value                  = var.azure_openai_deployment_id
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "openai_api_version" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/api-version"
  label                  = local.label
  value                  = var.azure_openai_api_version
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# AZURE SPEECH SERVICES CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "speech_endpoint" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/speech/endpoint"
  label                  = local.label
  value                  = var.azure_speech_endpoint
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "speech_region" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/speech/region"
  label                  = local.label
  value                  = var.azure_speech_region
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "speech_resource_id" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/speech/resource-id"
  label                  = local.label
  value                  = var.azure_speech_resource_id
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# AZURE COMMUNICATION SERVICES CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "acs_endpoint" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/acs/endpoint"
  label                  = local.label
  value                  = var.acs_endpoint
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "acs_immutable_id" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/acs/immutable-id"
  label                  = local.label
  value                  = var.acs_immutable_id
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "acs_source_phone" {
  count                  = var.acs_source_phone_number != "" ? 1 : 0
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/acs/source-phone-number"
  label                  = local.label
  value                  = var.acs_source_phone_number
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# REDIS CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "redis_hostname" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/redis/hostname"
  label                  = local.label
  value                  = var.redis_hostname
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "redis_port" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/redis/port"
  label                  = local.label
  value                  = tostring(var.redis_port)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# COSMOS DB CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "cosmos_database" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/cosmos/database-name"
  label                  = local.label
  value                  = var.cosmos_database_name
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "cosmos_collection" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/cosmos/collection-name"
  label                  = local.label
  value                  = var.cosmos_collection_name
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# STORAGE CONFIGURATION
# ============================================================================

resource "azurerm_app_configuration_key" "storage_account" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/storage/account-name"
  label                  = local.label
  value                  = var.storage_account_name
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "storage_container_url" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/storage/container-url"
  label                  = local.label
  value                  = var.storage_container_url
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# VOICE LIVE CONFIGURATION (OPTIONAL)
# ============================================================================

resource "azurerm_app_configuration_key" "voice_live_endpoint" {
  count                  = var.voice_live_endpoint != "" ? 1 : 0
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/voicelive/endpoint"
  label                  = local.label
  value                  = var.voice_live_endpoint
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "voice_live_model" {
  count                  = var.voice_live_model != "" ? 1 : 0
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/voicelive/model"
  label                  = local.label
  value                  = var.voice_live_model
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# APPLICATION POOL SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "pool_tts_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/tts-size"
  label                  = local.label
  value                  = tostring(var.pool_size_tts)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_stt_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/stt-size"
  label                  = local.label
  value                  = tostring(var.pool_size_stt)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_aoai_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/aoai-size"
  label                  = local.label
  value                  = tostring(var.aoai_pool_size)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_low_water_mark" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/low-water-mark"
  label                  = local.label
  value                  = tostring(var.pool_low_water_mark)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_high_water_mark" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/high-water-mark"
  label                  = local.label
  value                  = tostring(var.pool_high_water_mark)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_acquire_timeout" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/acquire-timeout"
  label                  = local.label
  value                  = tostring(var.pool_acquire_timeout)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# CONNECTION SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "connections_max" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/max-websocket"
  label                  = local.label
  value                  = tostring(var.max_websocket_connections)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "connection_queue_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/queue-size"
  label                  = local.label
  value                  = tostring(var.connection_queue_size)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "connection_warning_threshold" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/warning-threshold"
  label                  = local.label
  value                  = tostring(var.connection_warning_threshold)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "connection_critical_threshold" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/critical-threshold"
  label                  = local.label
  value                  = tostring(var.connection_critical_threshold)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "connection_timeout" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/timeout-seconds"
  label                  = local.label
  value                  = tostring(var.connection_timeout_seconds)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "heartbeat_interval" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/connections/heartbeat-interval"
  label                  = local.label
  value                  = tostring(var.heartbeat_interval_seconds)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "session_ttl" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/session/ttl-seconds"
  label                  = local.label
  value                  = tostring(var.session_ttl_seconds)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "session_cleanup_interval" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/session/cleanup-interval"
  label                  = local.label
  value                  = tostring(var.session_cleanup_interval)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "session_state_ttl" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/session/state-ttl"
  label                  = local.label
  value                  = tostring(var.session_state_ttl)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "max_concurrent_sessions" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/session/max-concurrent"
  label                  = local.label
  value                  = tostring(var.max_concurrent_sessions)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# SCALING SETTINGS
# ============================================================================
# Note: These are informational only - Container App scaling is managed by Terraform.
# Apps can read these to understand their scaling context.
# ============================================================================

resource "azurerm_app_configuration_key" "scaling_min_replicas" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/scaling/min-replicas"
  label                  = local.label
  value                  = tostring(var.container_min_replicas)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "scaling_max_replicas" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/scaling/max-replicas"
  label                  = local.label
  value                  = tostring(var.container_max_replicas)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# VOICE & TTS SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "tts_sample_rate_ui" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/tts-sample-rate-ui"
  label                  = local.label
  value                  = tostring(var.tts_sample_rate_ui)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "tts_sample_rate_acs" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/tts-sample-rate-acs"
  label                  = local.label
  value                  = tostring(var.tts_sample_rate_acs)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "tts_chunk_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/tts-chunk-size"
  label                  = local.label
  value                  = tostring(var.tts_chunk_size)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "tts_processing_timeout" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/tts-processing-timeout"
  label                  = local.label
  value                  = tostring(var.tts_processing_timeout)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "stt_processing_timeout" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/stt-processing-timeout"
  label                  = local.label
  value                  = tostring(var.stt_processing_timeout)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "silence_duration_ms" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/silence-duration-ms"
  label                  = local.label
  value                  = tostring(var.silence_duration_ms)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "recognized_languages" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/recognized-languages"
  label                  = local.label
  value                  = var.recognized_languages
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "default_tts_voice" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/voice/default-tts-voice"
  label                  = local.label
  value                  = var.default_tts_voice
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# AZURE OPENAI BEHAVIOR SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "aoai_temperature" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/default-temperature"
  label                  = local.label
  value                  = tostring(var.aoai_default_temperature)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "aoai_max_tokens" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/default-max-tokens"
  label                  = local.label
  value                  = tostring(var.aoai_default_max_tokens)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "aoai_request_timeout" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/openai/request-timeout"
  label                  = local.label
  value                  = tostring(var.aoai_request_timeout)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# WARM POOL SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "warm_pool_tts_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/warm-tts-size"
  label                  = local.label
  value                  = tostring(var.warm_pool_tts_size)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "warm_pool_stt_size" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/warm-stt-size"
  label                  = local.label
  value                  = tostring(var.warm_pool_stt_size)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "warm_pool_refresh_interval" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/warm-refresh-interval"
  label                  = local.label
  value                  = tostring(var.warm_pool_refresh_interval)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "warm_pool_session_max_age" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/pools/warm-session-max-age"
  label                  = local.label
  value                  = tostring(var.warm_pool_session_max_age)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# MONITORING SETTINGS
# ============================================================================

resource "azurerm_app_configuration_key" "metrics_collection_interval" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/monitoring/metrics-interval"
  label                  = local.label
  value                  = tostring(var.metrics_collection_interval)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "pool_metrics_interval" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/monitoring/pool-metrics-interval"
  label                  = local.label
  value                  = tostring(var.pool_metrics_interval)
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# ENVIRONMENT METADATA
# ============================================================================

resource "azurerm_app_configuration_key" "environment" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/environment"
  label                  = local.label
  value                  = var.environment_name
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

# ============================================================================
# APPLICATION URL CONFIGURATION
# ============================================================================
# These keys are populated by postprovision after Container Apps are deployed.
# The initial values are placeholders that get updated with actual URLs.
# Apps use dynamic refresh to pick up the new values without restart.
# ============================================================================

resource "azurerm_app_configuration_key" "backend_base_url" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/backend/base-url"
  label                  = local.label
  value                  = var.backend_base_url != "" ? var.backend_base_url : "https://placeholder.azurecontainerapps.io"
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]

  # Value is updated by postprovision script after deployment
  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_app_configuration_key" "frontend_backend_url" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/frontend/backend-url"
  label                  = local.label
  value                  = var.backend_base_url != "" ? var.backend_base_url : "https://placeholder.azurecontainerapps.io"
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]

  # Value is updated by postprovision script after deployment
  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_app_configuration_key" "frontend_ws_url" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/frontend/ws-url"
  label                  = local.label
  value                  = var.backend_base_url != "" ? replace(var.backend_base_url, "https://", "wss://") : "wss://placeholder.azurecontainerapps.io"
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]

  # Value is updated by postprovision script after deployment
  lifecycle {
    ignore_changes = [value]
  }
}

# ============================================================================
# SENTINEL KEY (Phase 4: Dynamic Configuration)
# ============================================================================
# The sentinel key is used to detect configuration changes.
# Update its value (e.g., timestamp or version) to trigger a cache refresh
# in running applications that have dynamic refresh enabled.
#
# To trigger a config refresh, run:
#   az appconfig kv set --endpoint <endpoint> --key app/sentinel --value "v$(date +%s)"
# ============================================================================

resource "azurerm_app_configuration_key" "sentinel" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "app/sentinel"
  label                  = local.label
  value                  = "v1"
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]

  # Ignore changes to the value - it's meant to be updated externally
  lifecycle {
    ignore_changes = [value]
  }
}

# ============================================================================
# KEY VAULT REFERENCES (SECRETS)
# ============================================================================
# These keys reference secrets stored in Key Vault. The App Configuration
# client will automatically resolve these references at runtime using the
# managed identity's Key Vault access.
# ============================================================================

resource "azurerm_app_configuration_key" "acs_connection_string" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/acs/connection-string"
  label                  = local.label
  type                   = "vault"
  vault_key_reference    = var.acs_connection_string_secret_id
  content_type           = local.content_type_kv_ref

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "cosmos_connection_string" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/cosmos/connection-string"
  label                  = local.label
  value                  = var.cosmos_connection_string
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_key" "appinsights_connection_string" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "azure/appinsights/connection-string"
  label                  = local.label
  value                  = var.appinsights_connection_string
  content_type           = local.content_type_text

  depends_on = [azurerm_role_assignment.deployer_owner]
}
