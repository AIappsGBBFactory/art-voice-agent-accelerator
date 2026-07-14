module "ai_foundry" {
  source = "./modules/ai"

  resource_group_id = azurerm_resource_group.main.id
  location          = azurerm_resource_group.main.location
  tags              = local.tags

  disable_local_auth            = var.disable_local_auth
  foundry_account_name          = local.resource_names.foundry_account
  foundry_custom_subdomain_name = local.resource_names.foundry_account

  project_name         = local.resource_names.foundry_project
  project_display_name = local.foundry_project_display
  project_description  = local.foundry_project_desc

  model_deployments = local.combined_model_deployments

  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  # Connect the project to Application Insights for GenAI tracing / Monitoring
  # (Foundry portal Traces + Application analytics; continuous eval source).
  application_insights_id                = azurerm_application_insights.main.id
  application_insights_connection_string = azurerm_application_insights.main.connection_string
}

resource "azurerm_role_assignment" "ai_foundry_account_role_for_backend_container" {
  scope                = module.ai_foundry.account_id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "ai_foundry_account_role_for_deployment_principal" {
  scope                = module.ai_foundry.account_id
  role_definition_name = "Cognitive Services User"
  principal_id         = local.principal_id

}

resource "azurerm_monitor_diagnostic_setting" "ai_foundry_account" {
  name                       = module.ai_foundry.account_name
  target_resource_id         = module.ai_foundry.account_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  # Per-request model-inference usage: emits ModelDeploymentName / ModelName /
  # ModelVersion so the deployment that actually served each cascade (Azure
  # OpenAI) request can be validated against the agent's selected model.
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

# Project-level diagnostic settings. The project sub-resource
# (Microsoft.CognitiveServices/accounts/projects) only supports the Audit + Trace
# log categories (per-request RequestResponse / AzureOpenAIRequestUsage are emitted
# at the account level above). Trace carries the per-project model-inference detail
# used to validate agent/model activity scoped to this project.
resource "azurerm_monitor_diagnostic_setting" "ai_foundry_project" {
  name                       = module.ai_foundry.project_name
  target_resource_id         = module.ai_foundry.project_id
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
