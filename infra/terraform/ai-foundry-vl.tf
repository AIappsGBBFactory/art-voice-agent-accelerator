module "ai_foundry_voice_live" {
  count  = local.should_create_voice_live_account ? 1 : 0
  source = "./modules/ai"

  resource_group_id = azurerm_resource_group.main.id
  location          = local.voice_live_primary_region
  tags              = local.tags

  disable_local_auth            = var.disable_local_auth
  foundry_account_name          = local.resource_names.voice_live_foundry_account
  foundry_custom_subdomain_name = local.resource_names.voice_live_foundry_account

  project_name         = local.resource_names.voice_live_foundry_project
  project_display_name = local.voice_live_project_display
  project_description  = local.voice_live_project_desc

  model_deployments = local.voice_live_model_deployments

  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  # Connect the Voice Live project to Application Insights for GenAI tracing /
  # Monitoring (Foundry portal Traces + Application analytics).
  enable_application_insights_connection = true
  application_insights_id                = azurerm_application_insights.main.id
  application_insights_connection_string = azurerm_application_insights.main.connection_string
}

resource "azurerm_role_assignment" "ai_foundry_voice_live_account_role_for_backend_container" {
  count = local.should_create_voice_live_account ? 1 : 0

  scope                = module.ai_foundry_voice_live[count.index].account_id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "ai_foundry_voice_live_account_role_for_deployment_principal" {
  count = local.should_create_voice_live_account ? 1 : 0

  scope                = module.ai_foundry_voice_live[count.index].account_id
  role_definition_name = "Cognitive Services User"
  principal_id         = local.principal_id
}

resource "azurerm_monitor_diagnostic_setting" "ai_foundry_voice_live_account" {
  count = local.should_create_voice_live_account ? 1 : 0

  name                       = module.ai_foundry_voice_live[count.index].account_name
  target_resource_id         = module.ai_foundry_voice_live[count.index].account_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  # Per-request model-inference usage: emits ModelDeploymentName / ModelName /
  # ModelVersion so the VoiceLive model bound at connect can be validated
  # against the agent's selected model in Log Analytics.
  enabled_log {
    category = "AzureOpenAIRequestUsage"
  }

  # Detailed inference trace logs for debugging model routing end-to-end.
  enabled_log {
    category = "Trace"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}

# Project-level diagnostic settings for the Voice Live project. The project
# sub-resource only supports Audit + Trace (per-request usage is at the account
# level above).
resource "azurerm_monitor_diagnostic_setting" "ai_foundry_voice_live_project" {
  count = local.should_create_voice_live_account ? 1 : 0

  name                       = module.ai_foundry_voice_live[count.index].project_name
  target_resource_id         = module.ai_foundry_voice_live[count.index].project_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "Trace"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
