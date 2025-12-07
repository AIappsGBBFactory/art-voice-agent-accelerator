# ============================================================================
# APP CONFIGURATION
# ============================================================================
# Centralized configuration store for all application settings.
# This is an ADDITIVE resource - existing Container App env vars are unchanged.
# ============================================================================

module "appconfig" {
  source = "./modules/appconfig"

  name                = "appconfig-${var.environment_name}-${local.resource_token}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment_name    = var.environment_name
  sku                 = "standard"
  tags                = local.tags

  # Identity access
  backend_identity_principal_id  = azurerm_user_assigned_identity.backend.principal_id
  frontend_identity_principal_id = azurerm_user_assigned_identity.frontend.principal_id
  deployer_principal_id          = local.principal_id
  deployer_principal_type        = local.principal_type

  # Key Vault integration
  key_vault_id  = azurerm_key_vault.main.id
  key_vault_uri = azurerm_key_vault.main.vault_uri

  # Azure OpenAI
  azure_openai_endpoint      = module.ai_foundry.openai_endpoint
  azure_openai_deployment_id = "gpt-4o"
  azure_openai_api_version   = "2025-01-01-preview"

  # Azure Speech
  azure_speech_endpoint    = module.ai_foundry.endpoint
  azure_speech_region      = module.ai_foundry.location
  azure_speech_resource_id = module.ai_foundry.account_id

  # Azure Communication Services
  acs_endpoint            = "https://${azapi_resource.acs.output.properties.hostName}"
  acs_immutable_id        = azapi_resource.acs.output.properties.immutableResourceId
  acs_source_phone_number = var.acs_source_phone_number != null ? var.acs_source_phone_number : ""

  # Redis
  redis_hostname = data.azapi_resource.redis_enterprise_fetched.output.properties.hostName
  redis_port     = var.redis_port

  # Cosmos DB
  cosmos_database_name   = var.mongo_database_name
  cosmos_collection_name = var.mongo_collection_name

  # Storage
  storage_account_name  = azurerm_storage_account.main.name
  storage_container_url = "${azurerm_storage_account.main.primary_blob_endpoint}${azurerm_storage_container.audioagent.name}"

  # Voice Live (conditional)
  enable_voice_live   = var.enable_voice_live
  voice_live_endpoint = var.enable_voice_live ? (local.should_create_voice_live_account ? module.ai_foundry_voice_live[0].endpoint : module.ai_foundry.endpoint) : null
  voice_live_model    = var.enable_voice_live ? local.voice_live_model_name : null

  # Pool settings
  pool_size_tts        = var.tts_pool_size
  pool_size_stt        = var.stt_pool_size
  aoai_pool_size       = var.aoai_pool_size
  pool_low_water_mark  = 10
  pool_high_water_mark = 45
  pool_acquire_timeout = 5

  # Connection settings
  max_websocket_connections     = 200
  connection_queue_size         = 50
  connection_warning_threshold  = 150
  connection_critical_threshold = 180
  connection_timeout_seconds    = 300
  heartbeat_interval_seconds    = 30

  # Session settings
  session_ttl_seconds      = 1800
  session_cleanup_interval = 300
  session_state_ttl        = 86400
  max_concurrent_sessions  = 1000

  # Scaling (informational)
  container_min_replicas = var.container_app_min_replicas
  container_max_replicas = var.container_app_max_replicas

  # Voice & TTS settings
  tts_sample_rate_ui     = 48000
  tts_sample_rate_acs    = 16000
  tts_chunk_size         = 1024
  tts_processing_timeout = 8
  stt_processing_timeout = 10
  silence_duration_ms    = 1300
  recognized_languages   = "en-US,es-ES,fr-FR,ko-KR,it-IT,pt-PT,pt-BR"
  default_tts_voice      = "en-US-EmmaMultilingualNeural"

  # Azure OpenAI behavior
  aoai_default_temperature = 0.7
  aoai_default_max_tokens  = 500
  aoai_request_timeout     = 30

  # Warm pool settings
  warm_pool_tts_size         = 3
  warm_pool_stt_size         = 2
  warm_pool_refresh_interval = 30
  warm_pool_session_max_age  = 1800

  # Monitoring settings
  metrics_collection_interval = 60
  pool_metrics_interval       = 30

  # Feature flags (defaults - can be overridden in Azure Portal)
  feature_dtmf_validation     = false
  feature_auth_validation     = false
  feature_call_recording      = false
  feature_warm_pool           = true
  feature_session_persistence = true
  feature_performance_logging = true
  feature_tracing             = true
  feature_connection_limits   = true

  # Secrets (Key Vault references and connection strings)
  acs_connection_string_secret_id = azurerm_key_vault_secret.acs_connection_string.versionless_id
  cosmos_connection_string = replace(
    data.azapi_resource.mongo_cluster_info.output.properties.connectionString,
    "/mongodb\\+srv:\\/\\/[^@]+@([^?]+)\\?(.*)$/",
    "mongodb+srv://$1?tls=true&authMechanism=MONGODB-OIDC&retrywrites=false&maxIdleTimeMS=120000"
  )
  appinsights_connection_string = azurerm_application_insights.main.connection_string

  depends_on = [
    azurerm_key_vault.main,
    azurerm_role_assignment.keyvault_admin,
    module.ai_foundry,
    azapi_resource.acs,
    azurerm_storage_account.main,
    azurerm_key_vault_secret.acs_connection_string,
  ]
}
