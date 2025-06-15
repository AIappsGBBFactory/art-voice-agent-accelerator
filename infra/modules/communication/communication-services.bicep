param communicationServiceName string
param keyVaultResourceId string
param dataLocation string = 'United States' // Default data location, can be overridden
param connectionStringSecretName string = 'acs-connection-string'
param primaryKeySecretName string = 'acs-primary-key'

// Add diagnostic settings parameter
@description('Diagnostic settings for the Communication Service')
param diagnosticSettings object = {}

resource communicationService 'Microsoft.Communication/CommunicationServices@2023-04-01-preview' = {
  name: communicationServiceName
  location: 'global'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    dataLocation: dataLocation
  }
}


// Add diagnostic settings resource
resource communicationServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(diagnosticSettings)) {
  name: 'diagnostics'
  scope: communicationService
  properties: {
    workspaceId: diagnosticSettings.?workspaceResourceId
    storageAccountId: diagnosticSettings.?storageAccountResourceId
    eventHubAuthorizationRuleId: diagnosticSettings.?eventHubAuthorizationRuleResourceId
    eventHubName: diagnosticSettings.?eventHubName
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}



// Reference existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: last(split(keyVaultResourceId, '/'))
}

// Store connection string in Key Vault
resource connectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: connectionStringSecretName
  properties: {
    value: communicationService.listKeys().primaryConnectionString
  }
}

// Store primary key in Key Vault
resource primaryKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: primaryKeySecretName
  properties: {
    value: communicationService.listKeys().primaryKey
  }
}

output endpoint string = 'https://${communicationService.properties.hostName}'
output communicationServiceName string = communicationServiceName
output location string = communicationService.location
output connectionStringSecretName string = connectionStringSecretName
output primaryKeySecretName string = primaryKeySecretName
output keyVaultUri string = keyVault.properties.vaultUri

output primaryKeySecretUri string = primaryKeySecret.properties.secretUriWithVersion
output connectionStringSecretUri string = connectionStringSecret.properties.secretUriWithVersion
output managedIdentityPrincipalId string = communicationService.identity.principalId
output managedIdentityClientId string = communicationService.identity.tenantId
