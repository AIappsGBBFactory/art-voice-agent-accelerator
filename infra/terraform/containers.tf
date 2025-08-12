# ============================================================================
# CONTAINER REGISTRY
# ============================================================================

resource "azurerm_container_registry" "main" {
  name                = local.resource_names.container_registry
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false

  public_network_access_enabled = true

  tags = local.tags
}

# RBAC assignments for Container Registry
resource "azurerm_role_assignment" "acr_principal_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = local.principal_id
  principal_type       = local.principal_type
}

resource "azurerm_role_assignment" "acr_principal_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = local.principal_id
  principal_type       = local.principal_type
}

resource "azurerm_role_assignment" "acr_frontend_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.frontend.principal_id
}

resource "azurerm_role_assignment" "acr_backend_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

# ============================================================================
# CONTAINER APPS ENVIRONMENT
# ============================================================================

resource "azurerm_container_app_environment" "main" {
  name                = local.resource_names.container_env
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = local.tags
}

# ============================================================================
# CONTAINER APPS
# ============================================================================

# Frontend Container App
resource "azurerm_container_app" "frontend" {
  name                         = "${var.name}-frontend-${local.resource_token}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  // Image is managed outside of terraform (i.e azd deploy)
  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.frontend.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.frontend.id
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 10

    container {
      name   = "main"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.5
      memory = "1.0Gi"

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      env {
        name  = "PORT"
        value = "8080"
      }
    }
  }

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-client"
  })
}

# Backend Container App
resource "azurerm_container_app" "backend" {
  name                         = "${var.name}-backend-${local.resource_token}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  // Image is managed outside of terraform (i.e azd deploy)
  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.backend.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "acs-connection-string"
    identity            = azurerm_user_assigned_identity.backend.id
    key_vault_secret_id = azurerm_key_vault_secret.acs_connection_string.versionless_id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 10

    container {
      name   = "main"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 1.0
      memory = "2.0Gi"

      # Azure Communication Services Configuration
      env {
        name  = "BASE_URL"
        value = var.backend_api_public_url != null ? var.backend_api_public_url : "https://<REPLACE_ME>"
      }

      env {
        name  = "ACS_AUDIENCE"
        value = azapi_resource.acs.output.properties.immutableResourceId
      }

      dynamic "env" {
        for_each = var.disable_local_auth ? [1] : []
        content {
          name  = "ACS_ENDPOINT"
          value = "https://${azapi_resource.acs.output.properties.hostName}"
        }
      }

      dynamic "env" {
        for_each = var.disable_local_auth ? [] : [1]
        content {
          name        = "ACS_CONNECTION_STRING"
          secret_name = "acs-connection-string"
        }
      }

      env {
        name  = "ACS_STREAMING_MODE"
        value = "media"
      }

      env {
        name = "ACS_SOURCE_PHONE_NUMBER"
        value = (
          var.acs_source_phone_number != null && var.acs_source_phone_number != ""
          ? var.acs_source_phone_number
          : "TODO: Acquire an ACS phone number. See https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/telephony/get-phone-number?tabs=windows&pivots=platform-azp-new"
        )
      }

      env {
        name  = "PORT"
        value = "8000"
      }

      # Azure Client ID for managed identity
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.backend.client_id
      }

      # Application Insights
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      # Redis Configuration
      env {
        name  = "REDIS_HOST"
        value = data.azapi_resource.redis_enterprise_fetched.output.properties.hostName
      }

      env {
        name  = "REDIS_PORT"
        value = tostring(var.redis_port)
      }

      # Azure Speech Services
      env {
        name  = "AZURE_SPEECH_ENDPOINT"
        value = "https://${azurerm_cognitive_account.speech.custom_subdomain_name}.cognitiveservices.azure.com/"
      }

      env {
        name  = "AZURE_SPEECH_DOMAIN_ENDPOINT"
        value = "https://${azurerm_cognitive_account.speech.custom_subdomain_name}.cognitiveservices.azure.com/"
      }

      env {
        name  = "AZURE_SPEECH_RESOURCE_ID"
        value = azurerm_cognitive_account.speech.id
      }

      env {
        name  = "AZURE_SPEECH_REGION"
        value = azurerm_cognitive_account.speech.location
      }

      dynamic "env" {
        for_each = var.disable_local_auth ? [] : [1]
        content {
          name        = "AZURE_SPEECH_KEY"
          secret_name = "speech-key"
        }
      }

      env {
        name  = "TTS_ENABLE_LOCAL_PLAYBACK"
        value = "false"
      }

      # Azure Cosmos DB
      env {
        name  = "AZURE_COSMOS_DATABASE_NAME"
        value = var.mongo_database_name
      }

      env {
        name  = "AZURE_COSMOS_COLLECTION_NAME"
        value = var.mongo_collection_name
      }

      env {
        name = "AZURE_COSMOS_CONNECTION_STRING"
        value = replace(
          data.azapi_resource.mongo_cluster_info.output.properties.connectionString,
          "/mongodb\\+srv:\\/\\/[^@]+@([^?]+)\\?(.*)$/",
          "mongodb+srv://$1?tls=true&authMechanism=MONGODB-OIDC&retrywrites=false&maxIdleTimeMS=120000"
        )
      }

      # Azure OpenAI
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }

      env {
        name  = "AZURE_OPENAI_CHAT_DEPLOYMENT_ID"
        value = "gpt-4o"
      }

      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = "2025-01-01-preview"
      }

      env {
        name  = "AZURE_OPENAI_CHAT_DEPLOYMENT_VERSION"
        value = "2024-10-01-preview"
      }

      dynamic "env" {
        for_each = var.disable_local_auth ? [] : [1]
        content {
          name        = "AZURE_OPENAI_KEY"
          secret_name = "openai-key"
        }
      }

      # Python-specific settings
      env {
        name  = "PYTHONPATH"
        value = "/home/site/wwwroot"
      }
    }
  }

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-server"
  })

  depends_on = [
    azurerm_key_vault_secret.acs_connection_string,
    azurerm_role_assignment.keyvault_backend_secrets
  ]
}

# Container Apps Environment
output "CONTAINER_APPS_ENVIRONMENT_ID" {
  description = "Container Apps Environment resource ID"
  value       = azurerm_container_app_environment.main.id
}

output "CONTAINER_APPS_ENVIRONMENT_NAME" {
  description = "Container Apps Environment name"
  value       = azurerm_container_app_environment.main.name
}

# Container Apps
output "FRONTEND_CONTAINER_APP_NAME" {
  description = "Frontend Container App name"
  value       = azurerm_container_app.frontend.name
}

output "BACKEND_CONTAINER_APP_NAME" {
  description = "Backend Container App name"
  value       = azurerm_container_app.backend.name
}

output "FRONTEND_CONTAINER_APP_FQDN" {
  description = "Frontend Container App FQDN"
  value       = azurerm_container_app.frontend.ingress[0].fqdn
}

output "BACKEND_CONTAINER_APP_FQDN" {
  description = "Backend Container App FQDN"
  value       = azurerm_container_app.backend.ingress[0].fqdn
}

output "FRONTEND_CONTAINER_APP_URL" {
  description = "Frontend Container App URL"
  value       = "https://${azurerm_container_app.frontend.ingress[0].fqdn}"
}

output "BACKEND_CONTAINER_APP_URL" {
  description = "Backend Container App URL"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "AZURE_CONTAINER_REGISTRY_ENDPOINT" {
  description = "Azure Container Registry endpoint"
  value       = azurerm_container_registry.main.login_server
}

output "BACKEND_API_URL" {
  description = "Backend API URL"
  value       = var.backend_api_public_url != null ? var.backend_api_public_url : "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}