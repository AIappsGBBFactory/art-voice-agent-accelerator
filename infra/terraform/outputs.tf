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
  value       = azurerm_communication_service.main.hostname
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
    value       = "${azurerm_storage_account.main.primary_blob_endpoint}${azurerm_storage_container.audioagent.name}"
}

output "AZURE_COSMOS_DATABASE_NAME" {
  description = "Azure Cosmos DB database name"
  value       = var.mongo_database_name
}

output "AZURE_COSMOS_COLLECTION_NAME" {
  description = "Azure Cosmos DB collection name"
  value       = var.mongo_collection_name
}

output "AZURE_COSMOS_CONNECTION_STRING" {
  description = "Azure Cosmos DB connection string"
  value = replace(
    data.azapi_resource.mongo_cluster_info.output.properties.connectionString,
    "/mongodb\\+srv:\\/\\/[^@]+@([^?]+)\\?(.*)$/",
    "mongodb+srv://$1?tls=true&authMechanism=MONGODB-OIDC&retrywrites=false&maxIdleTimeMS=120000"
  )
}

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
