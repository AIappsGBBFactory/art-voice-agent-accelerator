/*
  This module deploys AI Gateway infrastructure, including:
  - Azure AI Services (OpenAI) with multiple model deployments
  - API Management (APIM) for managing APIs
  - Role assignments for APIM to access AI services
*/

import { BackendConfigItem } from './modules/types.bicep'

// Parameters
@description('The name of the deployment or resource.')
param name string

@description('The location where the resources will be deployed. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('The environment for the deployment (e.g., dev, test, prod).')
param env string?

@description('Key Vault ID to store secrets.')
param keyVaultResourceId string

@description('Flag to enable or disable the use of a system-assigned managed identity.')
param enableSystemAssignedIdentity bool = true

@description('An array of user-assigned managed identity resource IDs to be used.')
param userAssignedResourceIds array?

@description('An array of diagnostic settings to configure for the resources.')
param diagnosticSettings array = []

@description('The email address of the API Management publisher.')
param apimPublisherEmail string = 'noreply@microsoft.com'

@description('The name of the API Management publisher.')
param apimPublisherName string = 'Microsoft'


@description('Subnet resource ID for API Management virtual network integration')
param apimSubnetResourceId string = ''

// Get reference to existing subnet for APIM delegation
resource existingSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = if (!empty(apimSubnetResourceId)) {
  name: '${split(apimSubnetResourceId, '/')[8]}/${last(split(apimSubnetResourceId, '/'))}'
}

// Update subnet with API Management delegation
resource apimSubnetDelegation 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = if (!empty(apimSubnetResourceId)) {
  name: '${split(apimSubnetResourceId, '/')[8]}/${last(split(apimSubnetResourceId, '/'))}'
  properties: {
    addressPrefix: existingSubnet.properties.addressPrefix
    delegations: [
      {
        name: 'Microsoft.Web/serverFarms'
        properties: {
          serviceName: 'Microsoft.Web/serverFarms'
        }
      }
    ]
    serviceEndpoints: existingSubnet.properties.?serviceEndpoints ?? []
  }
}

@description('Flag to enable API Management for AI Services')
param enableAPIManagement bool = false

// public spec not valid per 3.0.1 OpenAI specification requirements
// param openAIAPISpecURL string = 'https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/stable/2024-10-21/inference.json'
param openAIAPISpec string = loadTextContent('./modules/apim/specs/azure-openai-2024-10-21.yaml')

@allowed(['S0'])
param aiSvcSku string = 'S0'

@allowed(['BasicV2', 'StandardV2'])
param apimSku string = 'StandardV2'

param namedValues array = []

import { lockType } from 'br/public:avm/utl/types/avm-common-types:0.4.1'
param lock lockType = {
  name: null
  kind: env == 'prod' ? 'CanNotDelete' : 'None'
}

param tags object = {}

var resourceSuffix = uniqueString(subscription().id, resourceGroup().id)

// Backend Configuration with new structure
@description('Array of backend configurations for the AI services.')
param backendConfig BackendConfigItem[]

param oaiBackendPoolName string = 'openai-backend-pool' // Name of the backend pool for OpenAI

param audience string
param entraGroupId string

// param apimDnsZoneId string = '' // Optional DNS zone ID for APIM, can be used for private endpoints
param aoaiDnsZoneId string = '' // Optional DNS zone ID for Azure OpenAI, can be used for private endpoints
// param cosmosDnsZoneId string = '' // Optional DNS zone ID for Cosmos DB, can be used for private endpoints
param privateEndpointSubnetId string = '' // Subnet ID for private endpoints, if applicable

param disableLocalAuth bool = true // Keep enabled for now, can be disabled in prod
// param vnetIntegrationSubnetId string = ''
// param privateEndpoints array = []

// AzureOpenAI Services Deployment with updated model structure
@batchSize(1)
module aiSvc 'br/public:avm/res/cognitive-services/account:0.11.0' = [for (backend, i) in backendConfig: {
  name: 'aiServices-${i}-${resourceSuffix}-${backend.location}'
  params: {
    // Required parameters
    kind: 'OpenAI'
    sku: aiSvcSku
    name: 'aisvc-${i}-${resourceSuffix}-${backend.location}'
    // Non-required parameters
    disableLocalAuth: disableLocalAuth
    location: location
    secretsExportConfiguration: disableLocalAuth ? null : {
      accessKey1Name: 'aisvc-${i}-${resourceSuffix}-${backend.location}-accessKey1'
      keyVaultResourceId: keyVaultResourceId
    }
    deployments: [ for model in backend.models: {
        model: {
          format: 'OpenAI'
          name: model.name
          version: model.version
        }
        name: model.name
        sku: {
          name: model.sku
          capacity: model.capacity
        }
      }
    ]
    customSubDomainName: 'aisvc-${i}-${resourceSuffix}-${backend.location}'
    privateEndpoints: [
      {
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: aoaiDnsZoneId
            }
          ]
        }
        subnetResourceId: privateEndpointSubnetId
      }
    ]
    publicNetworkAccess: 'Disabled'

    diagnosticSettings: diagnosticSettings
    tags: tags
  }
}]

var formattedApimName = length('apim-${name}-${resourceSuffix}') <= 50
      ? 'apim-${name}-${resourceSuffix}'
      : 'apim-${substring(name, 0, 50 - length('apim--${resourceSuffix}'))}-${resourceSuffix}'


param loggers array = []

param virtualNetworkType string
// API Management Deployment
module apim 'br/public:avm/res/api-management/service:0.9.1' = if (enableAPIManagement) {
  name: formattedApimName
  params: {
    name: formattedApimName
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    location: location
    sku: apimSku
    namedValues: namedValues
    lock: lock
    managedIdentities: {
      systemAssigned: enableSystemAssignedIdentity
      userAssignedResourceIds: userAssignedResourceIds
    }

    loggers: loggers

    subnetResourceId: apimSubnetDelegation.id
    // subnetResourceId: apimSubnetResourceId
    
    diagnosticSettings: diagnosticSettings
    tags: tags

    apis: []
    
    backends: [
      for (backend, i) in backendConfig: {
        name: backend.name
        tls: {
          validateCertificateChain: true
          validateCertificateName: false
        }
        url: '${aiSvc[i].outputs.endpoint}openai'
      }
    ]

    // Global Policies go here
    policies: [

    ]
    virtualNetworkType: virtualNetworkType

  }
}


// module apimPrivateEndpoint 'br/public:avm/res/network/private-endpoint:0.7.1' = {
//   name: 'apim-pe-${name}-${resourceSuffix}'
//   params: {
//     name: 'apim-pe-${name}-${resourceSuffix}'
//     location: location
//     subnetResourceId: privateEndpointSubnetId
//     privateLinkServiceConnections: [
//       {
//         name: 'apim-pls-${name}-${resourceSuffix}'
//         properties: {
//           privateLinkServiceId: apim.outputs.resourceId
//           groupIds: [
//             'hostnameConfigurations'
//           ]
//         }
//       }
//     ]
//     privateDnsZoneGroup: {
//       privateDnsZoneGroupConfigs: [
//         {
//           name: 'apim-dns-zone'
//           privateDnsZoneResourceId: apimDnsZoneId
//         }
//       ]
//     }
//   }
// }


resource _apim 'Microsoft.ApiManagement/service@2024-05-01' existing = if (enableAPIManagement) {
  name: apim.name
}


// Create the backend pool
resource backendPool 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = {
  name: oaiBackendPoolName
  parent: _apim
  #disable-next-line BCP035
  properties: {
    description: 'Backend pool for Azure OpenAI'
    type: 'Pool'
    pool: {
    services: [for (backend, i) in backendConfig: {
      id: '/backends/${backend.name}'
      priority: backend.priority
      weight: min(backend.?weight ?? 10, 100)
    }]
    }
  }
  dependsOn: [apim]
}

// API creation
resource api 'Microsoft.ApiManagement/service/apis@2022-08-01' = {
  name: 'openai'
  parent: _apim
  properties: {
    apiVersionSetId: 'openai-version-set'
    displayName: 'OpenAI API'
    format: 'openapi+json'
    path: 'openai'
    protocols: [
      'http'
      'https'
    ]
    serviceUrl: '${_apim.properties.gatewayUrl}/openai'
    subscriptionRequired: false
    subscriptionKeyParameterNames: {
      header: 'api-key'
      query: 'api-key'
    }
    type: 'http'
    value: openAIAPISpec
  }
}

resource aoaiSubscription 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  name: 'openai-apim-subscription'
  parent: _apim
  properties: {
    allowTracing: true
    displayName: 'OpenAI API Subscription'
    scope: '/apis/${api.id}'
    state: 'active'
  }
}

// // Store APIM subscription key in Key Vault
// resource aoaiSubscriptionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (enableAPIManagement) {
//   name: '${last(split(keyVaultResourceId, '/'))}/openai-apim-subscription-key'
//   properties: {
//     value: aoaiSubscription.listSecrets().primaryKey
//   }
// }


var aoaiInboundXml = replace(
  replace(
    replace(
      replace(
        loadTextContent('./modules/apim/policies/openAI/inbound.xml'), 
        '{tenant-id}', 
        tenant().tenantId
      ), 
      '{backend-id}', 
      oaiBackendPoolName
    ),
    '{audience}',
    audience
  ),
  '{entra-group-id}',
  entraGroupId
)

// API Policy
resource aoaiInboundPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-09-01-preview' = {
  name: 'policy'
  parent: api
  properties: {
    format: 'rawxml'
    value: aoaiInboundXml
  }
}

// Role Assignments for APIM
resource apimSystemMIDRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableAPIManagement && enableSystemAssignedIdentity) {
  name: guid(resourceGroup().id, _apim.id, 'Azure-AI-Developer')
  scope: resourceGroup()
  properties: {
    principalId: _apim.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '64702f94-c441-49e6-a78b-ef80e0188fee')
    principalType: 'ServicePrincipal'
  }
  dependsOn: [aiSvc]
}

// ========== Outputs ==========
@description('API Management service details')
output apim object = enableAPIManagement ? {
  name: _apim.name
  id: _apim.id
  location: _apim.location
  sku: _apim.sku.name
  publisherEmail: _apim.properties.publisherEmail
  publisherName: _apim.properties.publisherName
  gatewayUrl: _apim.properties.gatewayUrl
  identity: _apim.identity
} : {}

@description('API endpoint URLs for accessing AI services')
output endpoints object = {
  openAI: enableAPIManagement 
    ? '${_apim.properties.gatewayUrl}/openai'
    #disable-next-line BCP187
    : length(backendConfig) > 0 ? aiSvc[0].outputs.endpoints['OpenAI Language Model Instance API'] : ''
}

// @description('Authentication details for accessing the APIs')
// output authentication object = {
//   subscriptionKeys: {
//     openAI: enableAPIManagement 
//       ? openAiApi.outputs.apiSubscriptionKey 
//       : length(backendConfig) > 0 ? aiSvc[0].outputs.: ''
//   }
//   managedIdentity: enableAPIManagement ? _apim.identity : {}
// }



@description('Complete AI Services module outputs for advanced scenarios')
output aiSvcRaw array = [for (item, i) in backendConfig: aiSvc[i].outputs]

// Additional outputs for easier access
@description('AI Gateway endpoints for simplified access')
output aiGatewayEndpoints array = [for (item, i) in backendConfig: aiSvc[i].outputs.endpoint]

@description('AI Gateway service IDs')
output aiGatewayServiceIds array = [for (item, i) in backendConfig: aiSvc[i].outputs.resourceId]

// output apimPrivateIpAddress string = enableAPIManagement ? _apim.properties.?privateIPAddresses[0] : ''
#disable-next-line outputs-should-not-contain-secrets
output oaiSubscriptionKey string = enableAPIManagement ? aoaiSubscription.listSecrets().primaryKey : ''
