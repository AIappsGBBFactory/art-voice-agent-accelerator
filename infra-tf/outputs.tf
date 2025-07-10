# ============================================================================
# OUTPUTS FOR AZD INTEGRATION AND APPLICATION CONFIGURATION
# ============================================================================

output "AZURE_RESOURCE_GROUP" {
  description = "Azure Resource Group name"
  value       = azurerm_resource_group.main.name
}

output "AZURE_LOCATION" {
  description = "Azure region location"
  value       = azurerm_resource_group.main.location
}

output "AZURE_CONTAINER_REGISTRY_ENDPOINT" {
  description = "Azure Container Registry endpoint"
  value       = azurerm_container_registry.main.login_server
}

# AI Services
output "AZURE_OPENAI_ENDPOINT" {
  description = "Azure OpenAI endpoint"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "AZURE_OPENAI_CHAT_DEPLOYMENT_ID" {
    description = "Azure OpenAI Chat Deployment ID"
    value       = "gpt-4o"
}

output "AZURE_OPENAI_API_VERSION" {
  description = "Azure OpenAI API version"
  value       = "2025-01-01-preview"
}

output "AZURE_OPENAI_RESOURCE_ID" {
  description = "Azure OpenAI resource ID"
  value       = azurerm_cognitive_account.openai.id
}

output "AZURE_SPEECH_ENDPOINT" {
  description = "Azure Speech Services endpoint"
  value       = azurerm_cognitive_account.speech.endpoint
}

output "AZURE_SPEECH_RESOURCE_ID" {
  description = "Azure Speech Services resource ID"
  value       = azurerm_cognitive_account.speech.id
}

output "AZURE_SPEECH_REGION" {
  description = "Azure Speech Services region"
  value       = azurerm_cognitive_account.speech.location
}

# Communication Services
output "ACS_ENDPOINT" {
  description = "Azure Communication Services endpoint"
  value       = "https://${azurerm_communication_service.main.data_location}.communication.azure.com"
}

output "ACS_RESOURCE_ID" {
  description = "Azure Communication Services resource ID"
  value       = azurerm_communication_service.main.id
}

# Data Services
output "AZURE_STORAGE_ACCOUNT_NAME" {
  description = "Azure Storage Account name"
  value       = azurerm_storage_account.main.name
}

output "AZURE_STORAGE_BLOB_ENDPOINT" {
  description = "Azure Storage Blob endpoint"
  value       = azurerm_storage_account.main.primary_blob_endpoint
}

output "AZURE_STORAGE_CONTAINER_URL" {
    description = "Azure Storage Container URL"
    value       = "${azurerm_storage_account.main.primary_blob_endpoint}/${azurerm_storage_container.audioagent.name}"
}

# output "AZURE_COSMOS_DB_ENDPOINT" {
#   description = "Azure Cosmos DB endpoint"
#   value       = azurerm_cosmosdb_account.main.endpoint
# }

# output "AZURE_COSMOS_DB_DATABASE_NAME" {
#   description = "Azure Cosmos DB database name"
#   value       = azurerm_cosmosdb_mongo_database.main.name
# }

# output "AZURE_COSMOS_DB_COLLECTION_NAME" {
#   description = "Azure Cosmos DB collection name"
#   value       = azurerm_cosmosdb_mongo_collection.main.name
# }

# Redis
output "REDIS_HOSTNAME" {
  description = "Redis Enterprise hostname"
  value       = data.azapi_resource.redis_enterprise_fetched.output.properties.hostName
}

output "REDIS_PORT" {
  description = "Redis Enterprise port"
  value       = var.redis_port
}

# Key Vault
output "AZURE_KEY_VAULT_NAME" {
  description = "Azure Key Vault name"
  value       = azurerm_key_vault.main.name
}

output "AZURE_KEY_VAULT_ENDPOINT" {
  description = "Azure Key Vault endpoint"
  value       = azurerm_key_vault.main.vault_uri
}

# Managed Identities
output "BACKEND_UAI_CLIENT_ID" {
  description = "Backend User Assigned Identity Client ID"
  value       = azurerm_user_assigned_identity.backend.client_id
}

output "BACKEND_UAI_PRINCIPAL_ID" {
  description = "Backend User Assigned Identity Principal ID"
  value       = azurerm_user_assigned_identity.backend.principal_id
}

output "FRONTEND_UAI_CLIENT_ID" {
  description = "Frontend User Assigned Identity Client ID"
  value       = azurerm_user_assigned_identity.frontend.client_id
}

output "FRONTEND_UAI_PRINCIPAL_ID" {
  description = "Frontend User Assigned Identity Principal ID"
  value       = azurerm_user_assigned_identity.frontend.principal_id
}

# Monitoring
output "APPLICATIONINSIGHTS_CONNECTION_STRING" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "LOG_ANALYTICS_WORKSPACE_ID" {
  description = "Log Analytics workspace ID"
  value       = azurerm_log_analytics_workspace.main.id
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

output "BASE_URL" { 
    description = "Base URL for the application"
    value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}