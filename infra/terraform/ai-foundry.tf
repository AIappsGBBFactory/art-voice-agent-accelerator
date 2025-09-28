module "ai_foundry" {
  source = "./modules/aifoundry"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  disable_local_auth            = var.disable_local_auth
  foundry_account_name          = local.resource_names.foundry_account
  foundry_custom_subdomain_name = local.resource_names.foundry_account

  project_name         = local.resource_names.foundry_project
  project_display_name = local.foundry_project_display
  project_description  = local.foundry_project_desc

  model_deployments = var.model_deployments

  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  account_principal_ids = {
    backend_identity  = azurerm_user_assigned_identity.backend.principal_id
    frontend_identity = azurerm_user_assigned_identity.frontend.principal_id
    acs_identity      = azapi_resource.acs.identity[0].principal_id
    deployer_identity = local.principal_id
  }

  depends_on = [ azurerm_resource_group.main ]
}


resource "azurerm_monitor_diagnostic_setting" "ai_foundry_account" {
  name                       = "${local.resource_names.foundry_account}-diagnostics"
  target_resource_id         = module.ai_foundry.account_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
