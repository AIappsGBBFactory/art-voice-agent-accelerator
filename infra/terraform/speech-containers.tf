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
# TLS Termination (optional):
# - Uses nginx sidecar container for HTTPS/WSS termination
# - See: https://learn.microsoft.com/azure/container-instances/container-instances-container-group-ssl
#
# References:
# - https://learn.microsoft.com/azure/ai-services/speech-service/speech-container-howto
# - https://learn.microsoft.com/azure/container-instances/container-instances-overview
# ============================================================================

# ============================================================================
# TLS CERTIFICATE GENERATION (Self-Signed)
# ============================================================================
# Generates a self-signed certificate if TLS is enabled but no cert is provided.
# For production, provide your own certificate from a trusted CA.
# ============================================================================

resource "tls_private_key" "speech_containers" {
  count     = var.enable_speech_containers && var.speech_container_enable_tls && var.speech_container_tls_cert_base64 == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "speech_containers" {
  count           = var.enable_speech_containers && var.speech_container_enable_tls && var.speech_container_tls_cert_base64 == "" ? 1 : 0
  private_key_pem = tls_private_key.speech_containers[0].private_key_pem

  subject {
    common_name  = "${var.name}-speech.${var.location}.azurecontainer.io"
    organization = var.name
  }

  # Certificate valid for 1 year
  validity_period_hours = 8760

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]

  # Include DNS names for both containers
  dns_names = [
    "${var.name}-stt-${local.resource_token}.${var.speech_container_location != null ? var.speech_container_location : var.location}.azurecontainer.io",
    "${var.name}-tts-${local.resource_token}.${var.speech_container_location != null ? var.speech_container_location : var.location}.azurecontainer.io",
    "localhost",
  ]
}

# ============================================================================
# NGINX CONFIGURATION FOR TLS TERMINATION
# ============================================================================

locals {
  # Determine which certificate to use (provided or self-signed)
  tls_cert_pem = var.speech_container_tls_cert_base64 != "" ? base64decode(var.speech_container_tls_cert_base64) : (
    var.enable_speech_containers && var.speech_container_enable_tls ? tls_self_signed_cert.speech_containers[0].cert_pem : ""
  )
  tls_key_pem = var.speech_container_tls_key_base64 != "" ? base64decode(var.speech_container_tls_key_base64) : (
    var.enable_speech_containers && var.speech_container_enable_tls ? tls_private_key.speech_containers[0].private_key_pem : ""
  )

  # Nginx config for TTS (HTTP proxy on port 5000)
  nginx_tts_config = <<-EOF
# Nginx TLS Termination for TTS Container
user nginx;
worker_processes auto;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    server {
        listen 443 ssl;
        listen [::]:443 ssl;
        server_name _;

        # TLS Configuration
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256;
        ssl_prefer_server_ciphers on;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 24h;

        ssl_certificate /etc/nginx/ssl.crt;
        ssl_certificate_key /etc/nginx/ssl.key;

        # Security headers
        add_header Strict-Transport-Security 'max-age=31536000; includeSubDomains' always;

        # Proxy to TTS container on localhost:5000
        location / {
            proxy_pass http://localhost:5000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 60s;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }

        # Health check endpoint (pass through)
        location /status {
            proxy_pass http://localhost:5000/status;
        }

        location /ready {
            proxy_pass http://localhost:5000/ready;
        }
    }
}
EOF

  # Nginx config for STT (WebSocket proxy on port 5000)
  nginx_stt_config = <<-EOF
# Nginx TLS Termination for STT Container (WebSocket support)
user nginx;
worker_processes auto;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    # WebSocket upgrade mapping
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    server {
        listen 443 ssl;
        listen [::]:443 ssl;
        server_name _;

        # TLS Configuration
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256;
        ssl_prefer_server_ciphers on;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 24h;

        ssl_certificate /etc/nginx/ssl.crt;
        ssl_certificate_key /etc/nginx/ssl.key;

        # Security headers
        add_header Strict-Transport-Security 'max-age=31536000; includeSubDomains' always;

        # Proxy to STT container on localhost:5000 with WebSocket support
        location / {
            proxy_pass http://localhost:5000;
            proxy_http_version 1.1;

            # WebSocket headers
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;

            # Standard proxy headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Increased timeouts for long-running speech recognition
            proxy_connect_timeout 60s;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }

        # Health check endpoint (pass through)
        location /status {
            proxy_pass http://localhost:5000/status;
        }

        location /ready {
            proxy_pass http://localhost:5000/ready;
        }
    }
}
EOF
}

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
# When TLS enabled: nginx sidecar terminates WSS on 443, proxies to localhost:5000
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

  # Only expose the appropriate port (443 for TLS, 5000 for non-TLS)
  dynamic "exposed_port" {
    for_each = var.speech_container_enable_tls ? [443] : [5000]
    content {
      port     = exposed_port.value
      protocol = "TCP"
    }
  }

  # ---- STT Speech Container ----
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
      "Eula"                                  = "accept"
      "Billing"                               = azurerm_cognitive_account.speech[0].endpoint
      "Logging__Console__LogLevel__Default"   = var.speech_container_log_level
      "Logging__Console__LogLevel__Microsoft" = "Warning"
      "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
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
      initial_delay_seconds = 120 # Models take time to load
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

  # ---- Nginx TLS Sidecar (conditional) ----
  dynamic "container" {
    for_each = var.speech_container_enable_tls ? [1] : []
    content {
      name   = "nginx-tls"
      image  = "mcr.microsoft.com/oss/nginx/nginx:1.21.6-alpine"
      cpu    = 0.5
      memory = 0.5

      ports {
        port     = 443
        protocol = "TCP"
      }

      # Mount secret volume containing nginx.conf and TLS certs
      # In AzureRM 4.x, secret volumes are defined inline within the volume block
      volume {
        name       = "nginx-config"
        mount_path = "/etc/nginx"
        read_only  = true
        secret = {
          "nginx.conf" = base64encode(local.nginx_stt_config)
          "ssl.crt"    = base64encode(local.tls_cert_pem)
          "ssl.key"    = base64encode(local.tls_key_pem)
        }
      }

      # Liveness probe on nginx
      liveness_probe {
        http_get {
          path   = "/status"
          port   = 443
          scheme = "https"
        }
        initial_delay_seconds = 30
        period_seconds        = 30
        timeout_seconds       = 10
        failure_threshold     = 3
      }
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
# When TLS enabled: nginx sidecar terminates HTTPS on 443, proxies to localhost:5000
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

  # Only expose the appropriate port (443 for TLS, 5000 for non-TLS)
  dynamic "exposed_port" {
    for_each = var.speech_container_enable_tls ? [443] : [5000]
    content {
      port     = exposed_port.value
      protocol = "TCP"
    }
  }

  # ---- TTS Speech Container ----
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
      "Eula"                                  = "accept"
      "Billing"                               = azurerm_cognitive_account.speech[0].endpoint
      "Logging__Console__LogLevel__Default"   = var.speech_container_log_level
      "Logging__Console__LogLevel__Microsoft" = "Warning"
      "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
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
      initial_delay_seconds = 120 # Models take time to load
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

  # ---- Nginx TLS Sidecar (conditional) ----
  dynamic "container" {
    for_each = var.speech_container_enable_tls ? [1] : []
    content {
      name   = "nginx-tls"
      image  = "mcr.microsoft.com/oss/nginx/nginx:1.21.6-alpine"
      cpu    = 0.5
      memory = 0.5

      ports {
        port     = 443
        protocol = "TCP"
      }

      # Mount secret volume containing nginx.conf and TLS certs
      # In AzureRM 4.x, secret volumes are defined inline within the volume block
      volume {
        name       = "nginx-config"
        mount_path = "/etc/nginx"
        read_only  = true
        secret = {
          "nginx.conf" = base64encode(local.nginx_tts_config)
          "ssl.crt"    = base64encode(local.tls_cert_pem)
          "ssl.key"    = base64encode(local.tls_key_pem)
        }
      }

      # Liveness probe on nginx
      liveness_probe {
        http_get {
          path   = "/status"
          port   = 443
          scheme = "https"
        }
        initial_delay_seconds = 30
        period_seconds        = 30
        timeout_seconds       = 10
        failure_threshold     = 3
      }
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
  description = "STT Container endpoint URL (for Speech SDK host configuration). Uses wss:// with port 443 when TLS enabled."
  value = var.enable_speech_containers ? (
    var.speech_container_external_ingress
    ? (var.speech_container_enable_tls
      ? "wss://${azurerm_container_group.stt[0].fqdn}:443"
    : "ws://${azurerm_container_group.stt[0].fqdn}:5000")
    : (var.speech_container_enable_tls
      ? "wss://${azurerm_container_group.stt[0].ip_address}:443"
    : "ws://${azurerm_container_group.stt[0].ip_address}:5000")
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
  description = "TTS Container endpoint URL (for Speech SDK host configuration). Uses https:// with port 443 when TLS enabled."
  value = var.enable_speech_containers ? (
    var.speech_container_external_ingress
    ? (var.speech_container_enable_tls
      ? "https://${azurerm_container_group.tts[0].fqdn}:443"
    : "http://${azurerm_container_group.tts[0].fqdn}:5000")
    : (var.speech_container_enable_tls
      ? "https://${azurerm_container_group.tts[0].ip_address}:443"
    : "http://${azurerm_container_group.tts[0].ip_address}:5000")
  ) : null
}

output "SPEECH_CONTAINER_TLS_ENABLED" {
  description = "Whether TLS is enabled for speech containers"
  value       = var.enable_speech_containers ? var.speech_container_enable_tls : null
}

output "SPEECH_CONTAINER_TLS_SELF_SIGNED" {
  description = "Whether self-signed certificate was generated (true if no cert provided)"
  value       = var.enable_speech_containers && var.speech_container_enable_tls ? (var.speech_container_tls_cert_base64 == "") : null
  sensitive   = true
}
