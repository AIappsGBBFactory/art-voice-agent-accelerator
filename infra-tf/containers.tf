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
}

resource "azurerm_role_assignment" "acr_principal_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = local.principal_id
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
    target_port      = 5173
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
        name  = "VITE_BACKEND_BASE_URL"
        value = azurerm_container_app.backend.ingress[0].fqdn
      }

      env {
        name  = "PORT"
        value = "5173"
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
    name  = "acs-connection-string"
    identity = azurerm_user_assigned_identity.backend.id
    key_vault_secret_id = azurerm_key_vault_secret.acs_connection_string.versionless_id
  }

#   dynamic "secret" {
#     for_each = var.disable_local_auth ? [] : [1]
#     content {
#       name  = "cosmos-connection-string"
#       identity = azurerm_user_assigned_identity.backend.id
#       key_vault_secret_id = azurerm_key_vault_secret.cosmos_connection_string[0].versionless_id
#     }
#   }

  dynamic "secret" {
    for_each = var.disable_local_auth ? [] : [1]
    content {
      name  = "speech-key"
      identity = azurerm_user_assigned_identity.backend.id
      key_vault_secret_id = azurerm_key_vault_secret.speech_key[0].versionless_id
    }
  }

  dynamic "secret" {
    for_each = var.disable_local_auth ? [] : [1]
    content {
      name  = "openai-key"
      identity = azurerm_user_assigned_identity.backend.id
      key_vault_secret_id = azurerm_key_vault_secret.openai_key[0].versionless_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8010
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

      # Environment variables from secrets
      env {
        name        = "ACS_CONNECTION_STRING"
        secret_name = "acs-connection-string"
      }

    #   dynamic "env" {
    #     for_each = var.disable_local_auth ? [] : [1]
    #     content {
    #       name        = "AZURE_COSMOS_CONNECTION_STRING"
    #       secret_name = "cosmos-connection-string"
    #     }
    #   }

      dynamic "env" {
        for_each = var.disable_local_auth ? [] : [1]
        content {
          name        = "AZURE_SPEECH_KEY"
          secret_name = "speech-key"
        }
      }

      dynamic "env" {
        for_each = var.disable_local_auth ? [] : [1]
        content {
          name        = "AZURE_OPENAI_KEY"
          secret_name = "openai-key"
        }
      }

      # Regular environment variables
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.backend.client_id
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      env {
        name  = "REDIS_HOST"
        value = data.azapi_resource.redis_enterprise_fetched.output.properties.hostName
      }

      env {
        name  = "REDIS_PORT"
        value = var.redis_port
      }

      env {
        name  = "AZURE_SPEECH_ENDPOINT"
        value = azurerm_cognitive_account.speech.endpoint
      }

      env {
        name  = "AZURE_SPEECH_RESOURCE_ID"
        value = azurerm_cognitive_account.speech.id
      }

      env {
        name  = "AZURE_SPEECH_REGION"
        value = azurerm_cognitive_account.speech.location
      }

      env {
        name  = "AZURE_COSMOS_DATABASE_NAME"
        value = var.mongo_database_name
      }

      env {
        name  = "AZURE_COSMOS_COLLECTION_NAME"
        value = var.mongo_collection_name
      }

      env {
        name  = "AZURE_COSMOS_CONNECTION_STRING"
          value       = replace(
                          data.azapi_resource.mongo_cluster_info.output.properties.connectionString,
                          "/mongodb\\+srv:\\/\\/[^@]+@([^?]+)\\?(.*)$/",
                          "mongodb+srv://$1?tls=true&authMechanism=MONGODB-OIDC&retrywrites=false&maxIdleTimeMS=120000"
                        )
      }

      # Add Cosmos DB endpoint when using managed identity (no connection string)
      # dynamic "env" {
      #   for_each = var.disable_local_auth ? [1] : []
      #   content {
      #     name  = "AZURE_COSMOS_DB_ENDPOINT"
      #     # value = azurerm_cosmosdb_account.main.endpoint
      #     value = azurerm_mongo_cluster.main.
      #   }
      # }

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
    }
  }

  tags = merge(local.tags, {
    "azd-service-name" = "rtaudio-server"
  })

  depends_on = [
    azurerm_key_vault_secret.acs_connection_string,
  ]
}
