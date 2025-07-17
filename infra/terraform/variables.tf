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
variable "acs_source_phone_number" {
  description = "Azure Communication Services phone number for outbound calls (E.164 format)"
  type        = string
  default     = null
  validation {
    condition = var.acs_source_phone_number == null || can(regex("^\\+[1-9]\\d{1,14}$", var.acs_source_phone_number))
    error_message = "ACS source phone number must be in E.164 format (e.g., +1234567890) or null."
  }
}
variable "name" {
  description = "Base name for the real-time audio agent application"
  type        = string
  default     = "rtaudioagent"
  validation {
    condition     = length(var.name) >= 1 && length(var.name) <= 20
    error_message = "Name must be between 1 and 20 characters."
  }
}

variable "location" {
  description = "Primary location for all resources"
  type        = string
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
  default     = true
}

variable "enable_redis_ha" {
  description = "Enable Redis Enterprise High Availability"
  type        = bool
  default     = false
}

variable "redis_sku" {
  description = "SKU for Azure Managed Redis (Enterprise)"
  type        = string
  default     = "MemoryOptimized_M10"
}

variable "redis_port" {
    description = "Port for Azure Managed Redis"
    type        = number
    default     = 10000
}

variable "openai_models" {
  description = "Azure OpenAI model deployments"
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
      capacity = 50
    },
    {
      name     = "gpt-4o-mini"
      version  = "2024-07-18"
      sku_name = "DataZoneStandard"
      capacity = 50
    },
    {
      name     = "gpt-4.1-mini"
      version  = "2025-04-14"
      sku_name = "DataZoneStandard"
      capacity = 50
    },
    {
      name     = "gpt-4.1"
      version  = "2025-04-14"
      sku_name = "DataZoneStandard"
      capacity = 50
    }
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