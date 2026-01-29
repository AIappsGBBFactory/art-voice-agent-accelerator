# ============================================================================
# VARIABLES
# ============================================================================
variable "environment_name" {
  description = "Name of the environment that can be used as part of naming resource convention"
  type        = string
  validation {
    condition     = length(var.environment_name) >= 1 && length(var.environment_name) <= 64
    error_message = "Environment name must be between 1 and 64 characters."
  }
}

variable "name" {
  description = "Base name for the real-time audio agent application"
  type        = string
  default     = "artagent"
  validation {
    condition     = length(var.name) >= 1 && length(var.name) <= 20
    error_message = "Name must be between 1 and 20 characters."
  }
}

variable "location" {
  description = "Primary location for all resources"
  type        = string
}

variable "openai_location" {
  description = "Optional secondary Azure OpenAI location to use if defined; will be prioritized over var.location for OpenAI resources."
  type        = string
  default     = null
}

variable "cosmosdb_location" {
  description = "Optional secondary Azure Cosmos DB location to use if defined; will be prioritized over var.location for Cosmos DB resources."
  type        = string
  default     = null
}

variable "cosmosdb_sku" {
  description = "SKU for Azure Cosmos DB (MongoDB Cluster)"
  type        = string
  default     = "M30"
}

variable "cosmosdb_public_network_access_enabled" {
  description = "Enable public network access for Cosmos DB (required for non-VNet deployments)"
  type        = bool
  default     = true
}

variable "principal_id" {
  description = "Principal ID of the user or service principal to assign application roles"
  type        = string
  default     = null
  sensitive   = true
}

variable "principal_type" {
  description = "Type of principal (User or ServicePrincipal)"
  type        = string
  default     = "User"
  validation {
    condition     = contains(["User", "ServicePrincipal"], var.principal_type)
    error_message = "Principal type must be either 'User' or 'ServicePrincipal'."
  }
}

variable "deployed_by" {
  description = "Identifier of the deployer (e.g., 'Full Name <email@domain>' or UPN). Used to tag resources for traceability."
  type        = string
  default     = null
}

variable "acs_data_location" {
  description = "Data location for Azure Communication Services"
  type        = string
  default     = "United States"
  validation {
    condition = contains([
      "United States", "Europe", "Asia Pacific", "Australia", "Brazil", "Canada",
      "France", "Germany", "India", "Japan", "Korea", "Norway", "Switzerland", "UAE", "UK"
    ], var.acs_data_location)
    error_message = "ACS data location must be a valid Azure Communication Services data location."
  }
}

variable "disable_local_auth" {
  description = "Disable local authentication and use Azure AD/managed identity only"
  type        = bool
  default     = false
}

variable "enable_redis_ha" {
  description = "Enable Redis Enterprise High Availability for production workloads"
  type        = bool
  default     = true
}

variable "redis_sku" {
  description = "SKU for Azure Managed Redis (Enterprise) optimized for performance"
  type        = string
  default     = "MemoryOptimized_M10"
  validation {
    condition = contains([
      "MemoryOptimized_M10", "MemoryOptimized_M20", "MemoryOptimized_M50",
      "MemoryOptimized_M100", "ComputeOptimized_X5", "ComputeOptimized_X10"
    ], var.redis_sku)
    error_message = "Redis SKU must be a valid Enterprise tier SKU."
  }
}

variable "redis_port" {
  description = "Port for Azure Managed Redis"
  type        = number
  default     = 10000
}
variable "enable_voice_live" {
  description = "Enable Azure Voice Live service for real-time speech capabilities"
  type        = bool
  default     = true
}

variable "voice_live_location" {
  description = <<-EOT
    Azure region for Voice Live resources.
    Supported regions: eastus2, westus2, swedencentral, southeastasia
    See: https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live
  EOT
  type        = string
  default     = "eastus2"
  validation {
    condition     = contains(["eastus2", "westus2", "swedencentral", "southeastasia"], var.voice_live_location)
    error_message = "Voice Live location must be one of: eastus2, westus2, swedencentral, southeastasia. See https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live"
  }
}

variable "voice_live_model_deployments" {
  description = "Azure OpenAI model deployments for Voice Live (real-time speech)"
  type = list(object({
    name     = string
    version  = string
    sku_name = string
    capacity = number
  }))
  default = [
    {
      name     = "gpt-realtime"
      version  = "2025-08-28"
      sku_name = "GlobalStandard"
      capacity = 4
    },
    {
      name     = "gpt-4o-transcribe"
      version  = "2025-03-20"
      sku_name = "GlobalStandard"
      capacity = 150
    }
  ]
}

variable "model_deployments" {
  description = "Azure OpenAI model deployments optimized for high performance"
  type = list(object({
    name     = string
    version  = string
    sku_name = string
    capacity = number
  }))
  default = [
    {
      name     = "gpt-4o"
      version  = "2024-11-20"
      sku_name = "DataZoneStandard"
      capacity = 150
    },
    {
      name     = "gpt-4o-mini"
      version  = "2024-07-18"
      sku_name = "DataZoneStandard"
      capacity = 150
    },
    {
      name     = "o3-mini"
      version  = "2025-01-31"
      sku_name = "DataZoneStandard"
      capacity = 150
    },
    {
      name     = "gpt-5.1"
      version  = "2025-11-13"
      sku_name = "DataZoneStandard"
      capacity = 150
    },
    {
      name     = "text-embedding-3-large"
      version  = "1"
      sku_name = "GlobalStandard"
      capacity = 100
    },
  ]
}

variable "mongo_database_name" {
  description = "Name of the MongoDB database"
  type        = string
  default     = "audioagentdb"
  validation {
    condition     = length(var.mongo_database_name) >= 1 && length(var.mongo_database_name) <= 64
    error_message = "MongoDB database name must be between 1 and 64 characters."
  }
}

variable "mongo_collection_name" {
  description = "Name of the MongoDB collection"
  type        = string
  default     = "audioagentcollection"
  validation {
    condition     = length(var.mongo_collection_name) >= 1 && length(var.mongo_collection_name) <= 64
    error_message = "MongoDB collection name must be between 1 and 64 characters."
  }
}

variable "container_app_min_replicas" {
  description = "Minimum number of container app replicas for high availability"
  type        = number
  default     = 5
  validation {
    condition     = var.container_app_min_replicas >= 1 && var.container_app_min_replicas <= 25
    error_message = "Container app min replicas must be between 1 and 25."
  }
}

variable "container_app_max_replicas" {
  description = "Maximum number of container app replicas for auto-scaling"
  type        = number
  default     = 50
  validation {
    condition     = var.container_app_max_replicas >= 1 && var.container_app_max_replicas <= 300
    error_message = "Container app max replicas must be between 1 and 300."
  }
}

variable "container_cpu_cores" {
  description = "CPU cores allocated to each container instance"
  type        = number
  default     = 2
  validation {
    condition     = contains([0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2], var.container_cpu_cores)
    error_message = "Container CPU cores must be one of: 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2"
  }
}

variable "container_memory_gb" {
  description = "Memory in GB allocated to each container instance"
  type        = string
  default     = "4.0Gi"
  validation {
    condition     = contains(["0.5Gi", "1.0Gi", "1.5Gi", "2.0Gi", "2.5Gi", "3.0Gi", "3.5Gi", "4.0Gi"], var.container_memory_gb)
    error_message = "Container memory must be between 0.5Gi and 4.0Gi in 0.5Gi increments."
  }
}

variable "aoai_pool_size" {
  description = "Size of the Azure OpenAI client pool for optimal performance"
  type        = number
  default     = 50
  validation {
    condition     = var.aoai_pool_size >= 5 && var.aoai_pool_size <= 200
    error_message = "AOAI pool size must be between 5 and 200."
  }
}

variable "tts_pool_size" {
  description = "Size of the TTS client pool for optimal performance"
  type        = number
  default     = 100
  validation {
    condition     = var.tts_pool_size >= 10 && var.tts_pool_size <= 500
    error_message = "TTS pool size must be between 10 and 500."
  }
}

variable "stt_pool_size" {
  description = "Size of the STT client pool for optimal performance"
  type        = number
  default     = 100
  validation {
    condition     = var.stt_pool_size >= 10 && var.stt_pool_size <= 500
    error_message = "STT pool size must be between 10 and 500."
  }
}

# ============================================================================
# SPEECH CONTAINERS CONFIGURATION (Azure Container Instances)
# ============================================================================

variable "enable_speech_containers" {
  description = "Enable deployment of Azure Speech containers (STT/TTS) on Container Instances"
  type        = bool
  default     = true
}

variable "speech_container_location" {
  description = "Azure region for speech containers. If not set, uses var.location"
  type        = string
  default     = null
}

variable "speech_container_external_ingress" {
  description = "Enable public IP for speech containers. Set to false for private-only access (requires VNet integration)."
  type        = bool
  default     = true
}

variable "speech_container_log_level" {
  description = "Log level for speech containers (Debug, Information, Warning, Error)"
  type        = string
  default     = "Information"
  validation {
    condition     = contains(["Debug", "Information", "Warning", "Error"], var.speech_container_log_level)
    error_message = "Log level must be one of: Debug, Information, Warning, Error"
  }
}

# STT Container Configuration
variable "stt_container_tag" {
  description = <<-EOT
    Tag for STT container image. Use locale-specific tags for production.
    Examples: latest, 4.8.0-amd64-en-us, 4.8.0-amd64-es-es
    See: https://mcr.microsoft.com/artifact/mar/azure-cognitive-services/speechservices/speech-to-text/tags
  EOT
  type        = string
  default     = "latest"
}

variable "stt_container_cpu" {
  description = "CPU cores for STT container. MS recommended: 8 cores, minimum: 4 cores"
  type        = number
  default     = 8
  validation {
    condition     = var.stt_container_cpu >= 4 && var.stt_container_cpu <= 16
    error_message = "STT container CPU must be between 4 and 16 cores."
  }
}

variable "stt_container_memory" {
  description = "Memory in GB for STT container. MS recommended: 8-16GB (add 4-8GB for model loading)"
  type        = number
  default     = 16
  validation {
    condition     = var.stt_container_memory >= 8 && var.stt_container_memory <= 32
    error_message = "STT container memory must be between 8 and 32 GB."
  }
}

# TTS Container Configuration
variable "tts_container_tag" {
  description = <<-EOT
    Tag for TTS container image. Use voice-specific tags for production.
    Examples: latest, 2.21.0-amd64-en-us-arianeural, 2.21.0-amd64-es-es-elviraneural
    See: https://mcr.microsoft.com/artifact/mar/azure-cognitive-services/speechservices/neural-text-to-speech/tags
  EOT
  type        = string
  default     = "latest"
}

variable "tts_container_cpu" {
  description = "CPU cores for TTS container. MS recommended: 8 cores, minimum: 6 cores"
  type        = number
  default     = 8
  validation {
    condition     = var.tts_container_cpu >= 6 && var.tts_container_cpu <= 16
    error_message = "TTS container CPU must be between 6 and 16 cores."
  }
}

variable "tts_container_memory" {
  description = "Memory in GB for TTS container. MS recommended: 16GB, minimum: 12GB"
  type        = number
  default     = 16
  validation {
    condition     = var.tts_container_memory >= 12 && var.tts_container_memory <= 32
    error_message = "TTS container memory must be between 12 and 32 GB."
  }
}

# TLS Configuration for Speech Containers
variable "speech_container_enable_tls" {
  description = "Enable TLS termination via nginx sidecar for speech containers"
  type        = bool
  default     = false
}

variable "speech_container_tls_cert_base64" {
  description = <<-EOT
    Base64-encoded TLS certificate (PEM format) for speech container HTTPS/WSS endpoints.
    Generate with: cat ssl.crt | base64
    For production, use a certificate from a trusted CA.
    If not provided and TLS is enabled, a self-signed certificate will be generated.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "speech_container_tls_key_base64" {
  description = <<-EOT
    Base64-encoded TLS private key (PEM format) for speech container HTTPS/WSS endpoints.
    Generate with: cat ssl.key | base64
    Must match the TLS certificate.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}
