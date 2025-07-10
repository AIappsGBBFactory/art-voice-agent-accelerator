# ============================================================================
# TERRAFORM CONFIGURATION
# ============================================================================

terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    azapi = {
      source = "Azure/azapi"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}

provider "azapi" {
  skip_provider_registration = false
}

# ============================================================================
# DATA SOURCES
# ============================================================================

data "azuread_client_config" "current" {}

# ============================================================================
# RANDOM RESOURCES
# ============================================================================

resource "random_string" "resource_token" {
  length  = 8
  upper   = false
  special = false
}

# ============================================================================
# LOCALS & VARIABLES
# ============================================================================

locals {
  principal_id = var.principal_id != null ? var.principal_id : data.azuread_client_config.current.object_id
  # Generate a unique resource token
  resource_token = random_string.resource_token.result
  
  # Common tags
  tags = {
    "azd-env-name"   = var.environment_name
    "hidden-title"   = "Real Time Audio ${var.environment_name}"
    "project"        = "gbb-ai-audio-agent"
    "environment"    = var.environment_name
    "deployment"     = "terraform"
  }
  
  # Resource naming with abbreviations
  resource_names = {
    resource_group    = "rg-${var.name}-${var.environment_name}"
    key_vault        = "kv${local.resource_token}"
    speech           = "speech-${var.environment_name}-${local.resource_token}"
    openai           = "openai${local.resource_token}"
    cosmos           = "cosmos${local.resource_token}"
    storage          = "st${local.resource_token}"
    redis            = "redis${local.resource_token}"
    acs              = "acs-${var.name}-${var.environment_name}-${local.resource_token}"
    container_registry = "${var.name}cr${local.resource_token}"
    log_analytics     = "log${local.resource_token}"
    app_insights      = "ai${local.resource_token}"
    container_env     = "${var.name}cae${local.resource_token}"
  }
}
