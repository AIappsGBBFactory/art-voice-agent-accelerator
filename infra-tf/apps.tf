# ============================================================================
# AZURE APP SERVICE PLAN
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
# AZURE APP SERVICES
# ============================================================================

# Frontend App Service
resource "azurerm_linux_web_app" "frontend" {
  name                = "${var.name}-frontend-app-${local.resource_token}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.frontend.id]
  }

  site_config {
    application_stack {
      node_version = "22-lts"
    }
    
    always_on = true
    
    app_command_line = "npm start"
  }

  app_settings = {
    # Build-time environment variables (Vite requirements)
    "VITE_AZURE_SPEECH_KEY"     = var.disable_local_auth ? "" : "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=speech-key)"
    "VITE_AZURE_REGION"         = azurerm_cognitive_account.speech.location
    "VITE_BACKEND_BASE_URL"     = "https://${azurerm_linux_web_app.backend.default_hostname}"
    
    # Runtime environment variables
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
    "PORT"                                  = "8080"
    "WEBSITE_NODE_DEFAULT_VERSION"          = "18.x"
    "SCM_DO_BUILD_DURING_DEPLOYMENT"       = "true"
    "ENABLE_ORYX_BUILD"                     = "true"
    
    # Azure Client ID for managed identity
    "AZURE_CLIENT_ID" = azurerm_user_assigned_identity.frontend.client_id
  }

  # Key Vault references require the app service to have access
  key_vault_reference_identity_id = azurerm_user_assigned_identity.frontend.id

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-client"
  })
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
    
    # FastAPI typically runs on uvicorn
    app_command_line = "python -m uvicorn main:app --host 0.0.0.0 --port 8000"
  }

  app_settings = merge({
    # Secrets from Key Vault
    "ACS_CONNECTION_STRING" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=acs-connection-string)"
  }, var.disable_local_auth ? {} : {
    "AZURE_SPEECH_KEY" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=speech-key)"
    "AZURE_OPENAI_KEY" = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=openai-key)"
  }, {
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

  depends_on = [
    azurerm_key_vault_secret.acs_connection_string,
    azurerm_role_assignment.keyvault_backend_secrets
  ]
}

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

output "FRONTEND_APP_SERVICE_NAME" {
  description = "Frontend App Service name"
  value       = azurerm_linux_web_app.frontend.name
}

output "BACKEND_APP_SERVICE_NAME" {
  description = "Backend App Service name"
  value       = azurerm_linux_web_app.backend.name
}

output "FRONTEND_APP_SERVICE_URL" {
  description = "Frontend App Service URL"
  value       = "https://${azurerm_linux_web_app.frontend.default_hostname}"
}

output "BACKEND_APP_SERVICE_URL" {
  description = "Backend App Service URL"
  value       = "https://${azurerm_linux_web_app.backend.default_hostname}"
}

output "APP_SERVICE_PLAN_ID" {
  description = "App Service Plan resource ID"
  value       = azurerm_service_plan.main.id
}