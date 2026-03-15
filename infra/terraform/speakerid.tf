# ============================================================================
# SPEAKER ID - MANAGED IDENTITY
# ============================================================================
#
# SpeechBrain ECAPA-TDNN speaker verification microservice.
# Stateless — no database, no Azure service dependencies.
# Only needs ACR pull for container image.
# ============================================================================

resource "azurerm_user_assigned_identity" "speakerid" {
  name                = "${var.name}-speakerid-${local.resource_token}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

# ============================================================================
# SPEAKER ID - ACR PULL PERMISSIONS
# ============================================================================

resource "azurerm_role_assignment" "acr_speakerid_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.speakerid.principal_id
}

# ============================================================================
# SPEAKER ID - CONTAINER APP
# ============================================================================
#
# Internal-only service called by the backend for speaker verification.
# Needs 1 CPU / 2Gi memory for the ECAPA-TDNN model (~300MB in memory).
# ============================================================================

resource "azurerm_container_app" "speakerid" {
  name                         = "speakerid-${local.resource_token}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.speakerid.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.speakerid.id
  }

  ingress {
    external_enabled = false # Internal only — backend calls this
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "main"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 1
      memory = "2.0Gi"

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/ready"
        initial_delay           = 10
        failure_count_threshold = 10
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        failure_count_threshold = 30
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }
    }
  }

  tags = merge(local.tags, {
    "azd-service-name" = "speakerid"
  })

  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }
}

# ============================================================================
# SPEAKER ID - OUTPUTS
# ============================================================================

output "SPEAKERID_CONTAINER_APP_NAME" {
  description = "Speaker ID Container App name"
  value       = azurerm_container_app.speakerid.name
}

output "SPEAKERID_FQDN" {
  description = "Speaker ID internal FQDN"
  value       = azurerm_container_app.speakerid.ingress[0].fqdn
}

output "SPEAKERID_SERVICE_URL" {
  description = "Speaker ID service URL (for backend SPEAKERID_SERVICE_URL env var)"
  value       = "https://${azurerm_container_app.speakerid.ingress[0].fqdn}"
}
