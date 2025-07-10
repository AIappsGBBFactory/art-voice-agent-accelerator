# ============================================================================
# AZURE COMMUNICATION SERVICES
# ============================================================================

resource "azurerm_communication_service" "main" {
  name                = local.resource_names.acs
  resource_group_name = azurerm_resource_group.main.name
  data_location       = var.acs_data_location
  tags                = local.tags
}

# Store ACS connection string in Key Vault
resource "azurerm_key_vault_secret" "acs_connection_string" {
  name         = "acs-connection-string"
  value        = azurerm_communication_service.main.primary_connection_string
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.keyvault_admin]
}

# Store ACS primary key in Key Vault
resource "azurerm_key_vault_secret" "acs_primary_key" {
  name         = "acs-primary-key"
  value        = azurerm_communication_service.main.primary_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.keyvault_admin]
}

# ============================================================================
# EVENT GRID SYSTEM TOPIC FOR ACS
# ============================================================================

resource "azurerm_eventgrid_system_topic" "acs" {
  name                   = "eg-topic-acs-${local.resource_token}"
  resource_group_name    = azurerm_resource_group.main.name
  location               = "global"
  source_arm_resource_id = azurerm_communication_service.main.id
  topic_type             = "Microsoft.Communication.CommunicationServices"
  tags                   = local.tags
}

# # Event Grid System Topic Event Subscription for Incoming Calls
# resource "azurerm_eventgrid_system_topic_event_subscription" "incoming_call_handler" {
#   name                = "backend-incoming-call-handler"
#   system_topic        = azurerm_eventgrid_system_topic.acs.name
#   resource_group_name = azurerm_resource_group.main.name

#   webhook_endpoint {
#     url = "https://${azurerm_container_app.backend.ingress[0].fqdn}/api/call/inbound"
#   }

#   included_event_types = [
#     "Microsoft.Communication.IncomingCall"
#   ]

#   # Retry policy for webhook delivery
#   retry_policy {
#     max_delivery_attempts = 5
#     event_time_to_live    = 1440
#   }

#   depends_on = [azurerm_eventgrid_system_topic.acs]
# }