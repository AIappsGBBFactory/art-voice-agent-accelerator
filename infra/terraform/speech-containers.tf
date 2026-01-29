# ============================================================================
# AZURE SPEECH CONTAINERS (STT & TTS)
# ============================================================================
# Deploys Azure Cognitive Services Speech containers on Azure Container Instances.
# ACI provides simple container deployment without orchestration overhead.
#
# Container images:
# - STT: mcr.microsoft.com/azure-cognitive-services/speechservices/speech-to-text
# - TTS: mcr.microsoft.com/azure-cognitive-services/speechservices/neural-text-to-speech
#
# Resource requirements (per MS documentation):
# - STT: 8 core, 8GB minimum (recommended), +4-8GB for model loading
# - TTS: 8 core, 16GB minimum (recommended)
#
# References:
# - https://learn.microsoft.com/azure/ai-services/speech-service/speech-container-howto
# - https://learn.microsoft.com/azure/container-instances/container-instances-overview
# ============================================================================

# ============================================================================
# SPEECH SERVICES COGNITIVE ACCOUNT (for billing endpoint)
# ============================================================================

resource "azurerm_cognitive_account" "speech" {
  count               = var.enable_speech_containers ? 1 : 0
  name                = local.resource_names.speech
  location            = var.speech_container_location != null ? var.speech_container_location : var.location
  resource_group_name = azurerm_resource_group.main.name
  kind                = "SpeechServices"
  sku_name            = "S0"

  custom_subdomain_name         = local.resource_names.speech
  public_network_access_enabled = true

  tags = local.tags
}

# Diagnostic settings for Speech Services
resource "azurerm_monitor_diagnostic_setting" "speech_diagnostics" {
  count                      = var.enable_speech_containers ? 1 : 0
  name                       = "${azurerm_cognitive_account.speech[0].name}-diagnostics"
  target_resource_id         = azurerm_cognitive_account.speech[0].id
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

# ============================================================================
# USER-ASSIGNED MANAGED IDENTITY FOR SPEECH CONTAINERS
# ============================================================================

resource "azurerm_user_assigned_identity" "speech_containers" {
  count               = var.enable_speech_containers ? 1 : 0
  name                = "${var.name}-speech-containers-${local.resource_token}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

# RBAC: Speech containers identity needs Cognitive Services User role
resource "azurerm_role_assignment" "speech_containers_user" {
  count                = var.enable_speech_containers ? 1 : 0
  scope                = azurerm_cognitive_account.speech[0].id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.speech_containers[0].principal_id
}

# ============================================================================
# SPEECH-TO-TEXT (STT) CONTAINER INSTANCE
# ============================================================================
# STT uses WebSocket protocol on port 5000
# Minimum: 4 core, 4GB | Recommended: 8 core, 8-16GB
# ============================================================================

resource "azurerm_container_group" "stt" {
  count               = var.enable_speech_containers ? 1 : 0
  name                = "${var.name}-stt-${local.resource_token}"
  location            = var.speech_container_location != null ? var.speech_container_location : var.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  ip_address_type     = var.speech_container_external_ingress ? "Public" : "Private"
  dns_name_label      = var.speech_container_external_ingress ? "${var.name}-stt-${local.resource_token}" : null
  restart_policy      = "Always"

  # Managed identity for Azure resource access
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.speech_containers[0].id]
  }

  container {
    name   = "stt"
    image  = "mcr.microsoft.com/azure-cognitive-services/speechservices/speech-to-text:${var.stt_container_tag}"
    cpu    = var.stt_container_cpu
    memory = var.stt_container_memory

    ports {
      port     = 5000
      protocol = "TCP"
    }

    # Required environment variables for Speech containers
    # See: https://learn.microsoft.com/azure/ai-services/speech-service/speech-container-howto
    # Note: Use double underscores (__) instead of colons for ASP.NET Core config in ACI
    environment_variables = {
      "Eula"                                    = "accept"
      "Billing"                                 = azurerm_cognitive_account.speech[0].endpoint
      "Logging__Console__LogLevel__Default"     = var.speech_container_log_level
      "Logging__Console__LogLevel__Microsoft"   = "Warning"
      "APPLICATIONINSIGHTS_CONNECTION_STRING"   = azurerm_application_insights.main.connection_string
    }

    secure_environment_variables = {
      "ApiKey" = azurerm_cognitive_account.speech[0].primary_access_key
    }

    # Liveness probe - checks if container is healthy
    liveness_probe {
      http_get {
        path   = "/status"
        port   = 5000
        scheme = "http"
      }
      initial_delay_seconds = 120  # Models take time to load
      period_seconds        = 30
      timeout_seconds       = 10
      failure_threshold     = 3
    }

    # Readiness probe - checks if container is ready to serve requests
    readiness_probe {
      http_get {
        path   = "/ready"
        port   = 5000
        scheme = "http"
      }
      initial_delay_seconds = 60
      period_seconds        = 10
      timeout_seconds       = 5
      failure_threshold     = 3
    }
  }

  # Send container logs to Log Analytics
  diagnostics {
    log_analytics {
      workspace_id  = azurerm_log_analytics_workspace.main.workspace_id
      workspace_key = azurerm_log_analytics_workspace.main.primary_shared_key
      log_type      = "ContainerInsights"
    }
  }

  tags = merge(local.tags, {
    "service-type" = "speech-to-text"
  })

  depends_on = [
    azurerm_cognitive_account.speech
  ]
}

# ============================================================================
# NEURAL TEXT-TO-SPEECH (TTS) CONTAINER INSTANCE
# ============================================================================
# TTS uses HTTP protocol on port 5000
# Minimum: 6 core, 12GB | Recommended: 8 core, 16GB
# ============================================================================

resource "azurerm_container_group" "tts" {
  count               = var.enable_speech_containers ? 1 : 0
  name                = "${var.name}-tts-${local.resource_token}"
  location            = var.speech_container_location != null ? var.speech_container_location : var.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  ip_address_type     = var.speech_container_external_ingress ? "Public" : "Private"
  dns_name_label      = var.speech_container_external_ingress ? "${var.name}-tts-${local.resource_token}" : null
  restart_policy      = "Always"

  # Managed identity for Azure resource access
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.speech_containers[0].id]
  }

  container {
    name   = "tts"
    image  = "mcr.microsoft.com/azure-cognitive-services/speechservices/neural-text-to-speech:${var.tts_container_tag}"
    cpu    = var.tts_container_cpu
    memory = var.tts_container_memory

    ports {
      port     = 5000
      protocol = "TCP"
    }

    # Required environment variables for Speech containers
    # See: https://learn.microsoft.com/azure/ai-services/speech-service/speech-container-ntts
    # Note: Use double underscores (__) instead of colons for ASP.NET Core config in ACI
    environment_variables = {
      "Eula"                                    = "accept"
      "Billing"                                 = azurerm_cognitive_account.speech[0].endpoint
      "Logging__Console__LogLevel__Default"     = var.speech_container_log_level
      "Logging__Console__LogLevel__Microsoft"   = "Warning"
      "APPLICATIONINSIGHTS_CONNECTION_STRING"   = azurerm_application_insights.main.connection_string
    }

    secure_environment_variables = {
      "ApiKey" = azurerm_cognitive_account.speech[0].primary_access_key
    }

    # Liveness probe - checks if container is healthy
    liveness_probe {
      http_get {
        path   = "/status"
        port   = 5000
        scheme = "http"
      }
      initial_delay_seconds = 120  # Models take time to load
      period_seconds        = 30
      timeout_seconds       = 10
      failure_threshold     = 3
    }

    # Readiness probe - checks if container is ready to serve requests
    readiness_probe {
      http_get {
        path   = "/ready"
        port   = 5000
        scheme = "http"
      }
      initial_delay_seconds = 60
      period_seconds        = 10
      timeout_seconds       = 5
      failure_threshold     = 3
    }
  }

  # Send container logs to Log Analytics
  diagnostics {
    log_analytics {
      workspace_id  = azurerm_log_analytics_workspace.main.workspace_id
      workspace_key = azurerm_log_analytics_workspace.main.primary_shared_key
      log_type      = "ContainerInsights"
    }
  }

  tags = merge(local.tags, {
    "service-type" = "neural-text-to-speech"
  })

  depends_on = [
    azurerm_cognitive_account.speech
  ]
}

# ============================================================================
# OUTPUTS
# ============================================================================

output "SPEECH_COGNITIVE_ACCOUNT_ENDPOINT" {
  description = "Speech Services cognitive account endpoint (billing endpoint)"
  value       = var.enable_speech_containers ? azurerm_cognitive_account.speech[0].endpoint : null
}

output "SPEECH_COGNITIVE_ACCOUNT_NAME" {
  description = "Speech Services cognitive account name"
  value       = var.enable_speech_containers ? azurerm_cognitive_account.speech[0].name : null
}

output "STT_CONTAINER_NAME" {
  description = "STT Container Instance name"
  value       = var.enable_speech_containers ? azurerm_container_group.stt[0].name : null
}

output "STT_CONTAINER_FQDN" {
  description = "STT Container Instance FQDN (if public)"
  value       = var.enable_speech_containers && var.speech_container_external_ingress ? azurerm_container_group.stt[0].fqdn : null
}

output "STT_CONTAINER_IP" {
  description = "STT Container Instance IP address"
  value       = var.enable_speech_containers ? azurerm_container_group.stt[0].ip_address : null
}

output "STT_CONTAINER_ENDPOINT" {
  description = "STT Container endpoint URL (for Speech SDK host configuration)"
  value       = var.enable_speech_containers ? (
    var.speech_container_external_ingress 
      ? "ws://${azurerm_container_group.stt[0].fqdn}:5000"
      : "ws://${azurerm_container_group.stt[0].ip_address}:5000"
  ) : null
}

output "TTS_CONTAINER_NAME" {
  description = "TTS Container Instance name"
  value       = var.enable_speech_containers ? azurerm_container_group.tts[0].name : null
}

output "TTS_CONTAINER_FQDN" {
  description = "TTS Container Instance FQDN (if public)"
  value       = var.enable_speech_containers && var.speech_container_external_ingress ? azurerm_container_group.tts[0].fqdn : null
}

output "TTS_CONTAINER_IP" {
  description = "TTS Container Instance IP address"
  value       = var.enable_speech_containers ? azurerm_container_group.tts[0].ip_address : null
}

output "TTS_CONTAINER_ENDPOINT" {
  description = "TTS Container endpoint URL (for Speech SDK host configuration)"
  value       = var.enable_speech_containers ? (
    var.speech_container_external_ingress 
      ? "http://${azurerm_container_group.tts[0].fqdn}:5000"
      : "http://${azurerm_container_group.tts[0].ip_address}:5000"
  ) : null
}
