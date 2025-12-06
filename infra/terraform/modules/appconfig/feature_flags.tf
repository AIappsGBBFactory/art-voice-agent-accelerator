# ============================================================================
# APP CONFIGURATION - FEATURE FLAGS
# ============================================================================
# Feature flags use the standard Azure App Configuration format:
# Key: .appconfig.featureflag/<feature-name>
# Content-Type: application/vnd.microsoft.appconfig.ff+json;charset=utf-8
# ============================================================================

resource "azurerm_app_configuration_feature" "dtmf_validation" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "dtmf-validation"
  label                  = local.label
  enabled                = var.feature_dtmf_validation
  description            = "Enable DTMF tone validation for caller input"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "auth_validation" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "auth-validation"
  label                  = local.label
  enabled                = var.feature_auth_validation
  description            = "Enable Entra ID authentication validation for API requests"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "call_recording" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "call-recording"
  label                  = local.label
  enabled                = var.feature_call_recording
  description            = "Enable ACS call recording for compliance and quality assurance"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "warm_pool" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "warm-pool"
  label                  = local.label
  enabled                = var.feature_warm_pool
  description            = "Enable pre-warmed connection pool for low-latency speech services"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "session_persistence" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "session-persistence"
  label                  = local.label
  enabled                = var.feature_session_persistence
  description            = "Enable session state persistence to Redis for failover support"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "performance_logging" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "performance-logging"
  label                  = local.label
  enabled                = var.feature_performance_logging
  description            = "Enable detailed performance logging for latency analysis"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "tracing" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "tracing"
  label                  = local.label
  enabled                = var.feature_tracing
  description            = "Enable distributed tracing with OpenTelemetry"

  depends_on = [azurerm_role_assignment.deployer_owner]
}

resource "azurerm_app_configuration_feature" "connection_limits" {
  configuration_store_id = azurerm_app_configuration.main.id
  name                   = "connection-limits"
  label                  = local.label
  enabled                = var.feature_connection_limits
  description            = "Enable WebSocket connection limits and throttling"

  depends_on = [azurerm_role_assignment.deployer_owner]
}
