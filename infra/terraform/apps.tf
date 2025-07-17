# ============================================================================
# AZURE APP SERVICE PLAN (for Backend only)
# ============================================================================

resource "azurerm_service_plan" "main" {
  name                = local.resource_names.app_service_plan
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "B1"  # Basic tier - adjust as needed

  tags = local.tags
}

# ============================================================================
# AZURE STATIC WEB APP (Frontend) & APP SERVICE (Backend)
# ============================================================================

# Frontend Static Web App
# Note: Deployment to Static Web Apps typically happens via:
# 1. GitHub Actions (recommended) - using the api_key output
# 2. Azure Static Web Apps CLI
# 3. Azure DevOps pipelines
# The app_settings here are available at build time and runtime
# Generate a random password for the frontend Static Web App
resource "random_password" "frontend_swa_password" {
  length     = 16
  special    = true
  numeric    = true
  min_numeric = 1
}

# Store the password in Azure Key Vault
resource "azurerm_key_vault_secret" "frontend_swa_password" {
  name         = "frontend-swa-password"
  value        = random_password.frontend_swa_password.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [
    azurerm_key_vault.main,
    azurerm_role_assignment.keyvault_admin
  ]
}

resource "azurerm_static_web_app" "frontend" {
  name                = "${var.name}-frontend-swa-${local.resource_token}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku_tier            = "Standard"
  sku_size            = "Standard"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.frontend.id]
  }

  # Build-time environment variables for Vite
  app_settings = {
    "VITE_AZURE_SPEECH_KEY"     = var.disable_local_auth ? "" : "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=speech-key)"
    "VITE_AZURE_REGION"         = azurerm_cognitive_account.speech.location
    "VITE_BACKEND_BASE_URL"     = "https://${azurerm_linux_web_app.backend.default_hostname}"
    # Azure Client ID for managed identity
    "AZURE_CLIENT_ID" = azurerm_user_assigned_identity.frontend.client_id
  }
  basic_auth {
    environments = "AllEnvironments"
    password = random_password.frontend_swa_password.result
  }

  configuration_file_changes_enabled = true
  preview_environments_enabled       = true
  public_network_access_enabled      = true

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-client"
  })
}

# Output the password for local use (not recommended for production)
output "FRONTEND_SWA_PASSWORD" {
  description = "Frontend Static Web App password for local use"
  value       = random_password.frontend_swa_password.result
  sensitive   = true
}


# Backend App Service  
resource "azurerm_linux_web_app" "backend" {
  name                = "${var.name}-backend-app-${local.resource_token}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.backend.id]
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }
    
    always_on = true
    
    # FastAPI startup command matching deployment script expectations
    # This will be overridden by the deployment script with agent-specific path
    app_command_line = "python -m uvicorn rtagents.RTAgent.backend.main:app --host 0.0.0.0 --port 8000"
  }
  # Use lifecycle block to prevent unnecessary updates to app_settings unless values actually change

  app_settings = merge({
    # Secrets from Key Vault
    "ACS_CONNECTION_STRING" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=acs-connection-string)"
    "ACS_ENDPOINT" = "https://${azurerm_communication_service.main.hostname}"
  }, var.disable_local_auth ? {} : {
    "AZURE_SPEECH_KEY" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=speech-key)"
    "AZURE_OPENAI_KEY" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=openai-key)"
  }, var.acs_source_phone_number != null && var.acs_source_phone_number != "" ? {
    "ACS_SOURCE_PHONE_NUMBER" = var.acs_source_phone_number
  } : {}, {
    "PORT"                                  = "8000"

    # Regular environment variables - matching container app configuration
    "AZURE_CLIENT_ID"                       = azurerm_user_assigned_identity.backend.client_id
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
    
    # Redis Configuration
    "REDIS_HOST" = data.azapi_resource.redis_enterprise_fetched.output.properties.hostName
    "REDIS_PORT" = tostring(var.redis_port)
    
    # Azure Speech Services
    "AZURE_SPEECH_ENDPOINT"    = azurerm_cognitive_account.speech.endpoint
    "AZURE_SPEECH_RESOURCE_ID" = azurerm_cognitive_account.speech.id
    "AZURE_SPEECH_REGION"      = azurerm_cognitive_account.speech.location
    
    # Azure Cosmos DB
    "AZURE_COSMOS_DATABASE_NAME"    = var.mongo_database_name
    "AZURE_COSMOS_COLLECTION_NAME"  = var.mongo_collection_name
    "AZURE_COSMOS_CONNECTION_STRING" = replace(
      data.azapi_resource.mongo_cluster_info.output.properties.connectionString,
      "/mongodb\\+srv:\\/\\/[^@]+@([^?]+)\\?(.*)$/",
      "mongodb+srv://$1?tls=true&authMechanism=MONGODB-OIDC&retrywrites=false&maxIdleTimeMS=120000"
    )
    
    # Azure OpenAI
    "AZURE_OPENAI_ENDPOINT"           = azurerm_cognitive_account.openai.endpoint
    "AZURE_OPENAI_CHAT_DEPLOYMENT_ID" = "gpt-4o"
    "AZURE_OPENAI_API_VERSION"        = "2025-01-01-preview"
    
    # Python-specific settings
    "PYTHONPATH"                    = "/home/site/wwwroot"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
    "ENABLE_ORYX_BUILD"             = "true"
  })

  # Key Vault references require the app service to have access
  key_vault_reference_identity_id = azurerm_user_assigned_identity.backend.id

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-server"
  })
  lifecycle {
    ignore_changes = [
      app_settings,
      site_config[0].app_command_line,
      tags
    ]
  }

  depends_on = [
    azurerm_key_vault_secret.acs_connection_string,
    azurerm_role_assignment.keyvault_backend_secrets
  ]
}

# Diagnostic settings for backend App Service
resource "azurerm_monitor_diagnostic_setting" "backend_app_service" {
  name                       = "${azurerm_linux_web_app.backend.name}-diagnostics"
  target_resource_id         = azurerm_linux_web_app.backend.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  # Supported App Service log categories
  enabled_log {
    category = "AppServiceConsoleLogs"
  }

  enabled_log {
    category = "AppServiceHTTPLogs"
  }

  enabled_log {
    category = "AppServicePlatformLogs"
  }

  enabled_log {
    category = "AppServiceAppLogs"
  }
}

# # Diagnostic settings for frontend Static Web App
# resource "azurerm_monitor_diagnostic_setting" "frontend_static_web_app" {
#   name                       = "${azurerm_static_web_app.frontend.name}-diagnostics"
#   target_resource_id         = azurerm_static_web_app.frontend.id
#   log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

#   enabled_log {
#     category = ""
#     }
# }

# ============================================================================
# RBAC ASSIGNMENTS FOR APP SERVICES
# ============================================================================

# Key Vault access for frontend app service
resource "azurerm_role_assignment" "keyvault_frontend_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.frontend.principal_id
}

# The backend already has Key Vault access from keyvault.tf

# ============================================================================
# OUTPUTS FOR APP SERVICES
# ============================================================================

output "FRONTEND_STATIC_WEB_APP_NAME" {
  description = "Frontend Static Web App name"
  value       = azurerm_static_web_app.frontend.name
}

output "BACKEND_APP_SERVICE_NAME" {
  description = "Backend App Service name"
  value       = azurerm_linux_web_app.backend.name
}

output "FRONTEND_STATIC_WEB_APP_URL" {
  description = "Frontend Static Web App URL"
  value       = "https://${azurerm_static_web_app.frontend.default_host_name}"
}

output "BACKEND_APP_SERVICE_URL" {
  description = "Backend App Service URL"
  value       = "https://${azurerm_linux_web_app.backend.default_hostname}"
}

output "FRONTEND_STATIC_WEB_APP_API_KEY" {
  description = "Frontend Static Web App deployment token for CI/CD"
  value       = azurerm_static_web_app.frontend.api_key
  sensitive   = true
}

output "APP_SERVICE_PLAN_ID" {
  description = "App Service Plan resource ID (for backend only)"
  value       = azurerm_service_plan.main.id
}

# ============================================================================
# DEPLOYMENT NOTES
# ============================================================================
# 
# Frontend (Static Web App):
# - Deployment via GitHub Actions (recommended) using api_key output
# - Alternative: Azure Static Web Apps CLI with: swa deploy --deployment-token <api_key>
# - Update deployment scripts to use Static Web App deployment instead of App Service
#
# Backend (App Service):
# - Continues to use existing App Service deployment via scripts/azd/helpers/appsvc-deploy.sh
# - No changes needed for backend deployment process
#
# Environment Variables:
# - Frontend: Vite build-time vars (VITE_*) are available during build and runtime
# - Backend: Continues to use existing App Service app settings
# ============================================================================