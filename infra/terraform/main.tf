# ============================================================================
# TERRAFORM CONFIGURATION
# ============================================================================

terraform {
  required_version = ">= 1.1.7, < 2.0.0"

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
  storage_use_azuread = true
}

provider "azuread" {}

provider "azapi" {
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
  principal_id   = var.principal_id != null ? var.principal_id : data.azuread_client_config.current.object_id
  principal_type = var.principal_type
  # Generate a unique resource token
  resource_token = random_string.resource_token.result

  email_sender_username     = "noreply"
  email_sender_display_name = "Real-Time Voice Notifications"

  # Common tags
  tags = {
    "azd-env-name"    = var.environment_name
    "hidden-title"    = "Real Time Audio ${var.environment_name}"
    "project"         = "gbb-ai-audio-agent"
    "environment"     = var.environment_name
    "deployment"      = "terraform"
    "deployed_by"     = coalesce(var.deployed_by, local.principal_id)
    # To bypass Azure policy which enforces private networking configuration for nonprod environments
    "SecurityControl" = var.environment_name != "prod" ? "Ignore" : null
  }

  voice_live_available_regions = [
    "eastus2",
    "westus2",
    "swedencentral",
    "southeastasia",
  ]
  
  # Resource naming with Azure standard abbreviations
  # Following Azure Cloud Adoption Framework: https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations
  resource_names = {
    resource_group     = "rg-${var.name}-${var.environment_name}"
    app_service_plan   = "asp-${var.name}-${var.environment_name}-${local.resource_token}"
    key_vault          = "kv-${local.resource_token}"
    speech             = "spch-${var.environment_name}-${local.resource_token}"
    openai             = "oai-${local.resource_token}"
    cosmos             = "cosmos-cluster-${local.resource_token}"
    storage            = "st${local.resource_token}"
    redis              = "redis${local.resource_token}"
    acs                = "acs-${var.name}-${var.environment_name}-${local.resource_token}"
    container_registry = "cr${var.name}${local.resource_token}"
    log_analytics      = "log-${local.resource_token}"
    app_insights       = "ai-${local.resource_token}"
    container_env      = "cae-${var.name}-${var.environment_name}-${local.resource_token}"
    email_service      = "email-${var.name}-${var.environment_name}-${local.resource_token}"
    email_domain       = "AzureManagedDomain"
    foundry_account    = substr(replace("aif${var.name}${var.environment_name}", "/[^a-zA-Z0-9]/", ""), 0, 24)
    foundry_project    = "aif${var.name}${var.environment_name}proj"
    voice_live_foundry_account = substr(replace("avl${var.name}${var.environment_name}", "/[^a-zA-Z0-9]/", ""), 0, 24)
    voice_live_foundry_project = "aif${var.name}${var.environment_name}-vl-proj"
  }

  foundry_project_display = "AI Foundry ${var.environment_name}"
  foundry_project_desc    = "AI Foundry project for ${var.environment_name} environment"

  voice_live_supported_region   = contains(local.voice_live_available_regions, azurerm_resource_group.main.location)
  voice_live_primary_region     = local.voice_live_available_regions[0]
  should_enable_voice_live_here = var.enable_voice_live && local.voice_live_supported_region
  should_create_voice_live_account = var.enable_voice_live && !local.voice_live_supported_region

  voice_live_model_names = ["gpt-realtime", "gpt-4o-transcribe"]

  base_model_deployments_map = {
    for deployment in var.model_deployments :
    deployment.name => deployment
    if !(local.should_create_voice_live_account && contains(local.voice_live_model_names, deployment.name))
  }
  voice_live_model_name = "gpt-realtime"
  voice_live_model_deployments_map = {
    for name, details in {
      "gpt-realtime" = {
        name     = "gpt-realtime"
        version  = "2025-08-28"
        sku_name = "GlobalStandard"
        capacity = 10
      }
      "gpt-4o-transcribe" = {
        name     = "gpt-4o-transcribe"
        version  = "2025-03-20"
        sku_name = "GlobalStandard"
        capacity = 150
      }
    } : name => details
  }

  combined_model_deployments_map = local.should_enable_voice_live_here ? merge(local.base_model_deployments_map, local.voice_live_model_deployments_map) : local.base_model_deployments_map
  combined_model_deployments     = [for deployment in values(local.combined_model_deployments_map) : deployment]
  voice_live_model_deployments   = [for deployment in values(local.voice_live_model_deployments_map) : deployment]

  voice_live_project_display = "AI Foundry Voice Live ${var.environment_name}"
  voice_live_project_desc    = "AI Foundry Voice Live project for ${var.environment_name} environment"
}
