targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

param name string = 'rtaudioagent'

@minLength(1)
@description('Azure AD application/client ID')
param appClientId string

@minLength(1)
@description('Primary location for all resources')
param location string

import { ContainerAppKvSecret, SubnetConfig, BackendConfigItem } from './modules/types.bicep'

param rtaudioClientExists bool
param rtaudioServerExists bool

@description('Flag to enable/disable the use of APIM for OpenAI loadbalancing')
param enableAPIManagement bool = true

@description('Id of the user or app to assign application roles')
param principalId string

// param acsSourcePhoneNumber string
@description('[Required when enableAPIManagement is true] Array of backend configurations for the AI services.')
param azureOpenAIBackendConfig BackendConfigItem[]


// @secure()
// @description('Base64-encoded Root SSL certificate (.cer) for Application Gateway')
// param rootCertificateBase64Value string

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = uniqueString(subscription().id, environmentName, location)

// Network Config
// -----------------------------------------------------------
param hubVNetName string = 'vnet-hub-${name}-${environmentName}'
param spokeVNetName string = 'vnet-spoke-${name}-${environmentName}'
param hubVNetAddressPrefix string = '10.0.0.0/16'
param spokeVNetAddressPrefix string = '10.1.0.0/16'
param hubSubnets SubnetConfig[] = [
  {
    name: 'loadBalancer'          // App Gateway or L4 LB
    addressPrefix: '10.0.0.0/27'
  }
  {
    name: 'apim'                  // Internal APIM instance
    addressPrefix: '10.0.1.0/27'
    delegations: [
      {
        name: 'apimDelegation'
        properties: {
          serviceName: 'Microsoft.Web/serverfarms'
          // serviceName: 'Microsoft.ApiManagement/service'
        }
      }

    ]  
  }
  {
    name: 'services'          // Shared services like monitor, orchestrators (if colocated)
    addressPrefix: '10.0.0.64/26'
  }
]
param spokeSubnets SubnetConfig[] = [
  {
    name: 'privateEndpoint'       // PE for Redis, Cosmos, Speech, Blob
    addressPrefix: '10.1.0.0/26'
  }
  {
    name: 'app'        // Real-time agents, FastAPI, containers
    addressPrefix: '10.1.10.0/23'
  }
  {
    name: 'cache'                 // Redis workers (can be merged into `app` if simple)
    addressPrefix: '10.1.2.0/26'
  }
  {
    name: 'jumpbox'               // Optional, minimal size
    addressPrefix: '10.1.3.0/26'
  }
  // {
  //   name: 'apimOutbound'
  //   addressPrefix: '10.1.0.224/27'
  //   delegations: [
  //     {
  //       name: 'Microsoft.Web/serverfarms'
  //       properties: {
  //         serviceName: 'Microsoft.Web/serverFarms'
  //       }
  //     }
  //   ]
  // }
]
// Tags that should be applied to all resources.
// 
// Note that 'azd-service-name' tags should be applied separately to service host resources.
// Example usage:
//   tags: union(tags, { 'azd-service-name': <service name in azure.yaml> })
var tags = {
  'azd-env-name': environmentName
  'hidden-title': 'Real Time Audio ${environmentName}'

}
param networkIsolation bool = true

resource hubRg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-hub-${name}-${environmentName}'
  location: location
  tags: tags
}

resource spokeRg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-spoke-${name}-${environmentName}'
  location: location
  tags: tags
}

// Monitor application with Azure Monitor
module monitoring 'br/public:avm/ptn/azd/monitoring:0.1.0' = {
  name: 'monitoring'
  scope: hubRg
  params: {
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    applicationInsightsName: '${abbrs.insightsComponents}${resourceToken}'
    applicationInsightsDashboardName: '${abbrs.portalDashboards}${resourceToken}'
    location: location
    tags: tags
  }
}

// Hub and Spoke VNets
module hubNetwork 'network.bicep' = {
scope: hubRg
  name: hubVNetName
  params: {
    vnetName: hubVNetName
    location: location
    vnetAddressPrefix: hubVNetAddressPrefix
    subnets: hubSubnets
    workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    tags: tags
    // Optionally, you can pass custom subnet configs or domain label here if needed
  }
}


module spokeNetwork 'network.bicep' = {
  scope: spokeRg
  name: spokeVNetName
  params: {
    vnetName: spokeVNetName
    location: location
    vnetAddressPrefix: spokeVNetAddressPrefix
    subnets: spokeSubnets
    workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    tags: tags
    // Optionally, you can pass custom subnet configs or domain label here if needed
  }
}

// Private DNS Zones for various Azure services
module blobDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'blob-dnzones'
  scope: hubRg
  params: {
    #disable-next-line no-hardcoded-env-urls
    dnsZoneName: 'privatelink.blob.core.windows.net' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}
module apimDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'apim-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.azure-api.net' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module cosmosMongoDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'cosmos-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.mongo.cosmos.azure.com' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module documentsDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'documents-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.documents.azure.com' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module vaultDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'vault-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.vaultcore.azure.net' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module containerAppsDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'aca-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.${location}.azurecontainerapps.io' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}
module acrDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'acr-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.${location}.azurecr.io' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module aiservicesDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'aiservices-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.cognitiveservices.azure.com' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module openaiDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'openai-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.openai.azure.com' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module searchDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'searchs-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.search.windows.net' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

module redisDnsZone './modules/networking/private-dns-zone.bicep' =if (networkIsolation) {
  name: 'redis-azure-managed-dnzones'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.redis.azure.net' 
    tags: tags
    virtualNetworkName: networkIsolation ? hubNetwork.outputs.vnetName : ''
  }
}

// VNet Peering
module peerHubToSpoke './modules/networking/peer-virtual-networks.bicep' = {
  scope: hubRg
  name: 'peer-hub-to-spoke-vnets'
  params: {
    localVnetName: hubNetwork.outputs.vnetName
    remoteVnetId: spokeNetwork.outputs.vnetId
    remoteVnetName: spokeNetwork.outputs.vnetName
  }
}

module peerSpokeToHub './modules/networking/peer-virtual-networks.bicep' = {
  scope: spokeRg
  name: 'peer-spoke-to-hub-vnets'
  params: {
    localVnetName: spokeNetwork.outputs.vnetName
    remoteVnetId: hubNetwork.outputs.vnetId
    remoteVnetName: hubNetwork.outputs.vnetName
  }
  dependsOn: [
    peerHubToSpoke
  ]
}

param acsDataLocation string = 'UnitedStates'


module uaiAudioAgentBackendIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'uaiAudioAgentBackend'
  scope: spokeRg
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}uaiAudioAgentBackend-${resourceToken}'
    location: location
  }
}


module uaiAudioAgentFrontendIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'uaiAudioAgentFrontend'
  scope: spokeRg
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}uaiAudioAgentFrontend-${resourceToken}'
    location: location
  }
}

param principalType string = 'User' // or 'ServicePrincipal' based on your requirements
param vaultSku string = 'standard' // or 'premium' based on your requirements
// Key Vault for storing secrets
module keyVault 'br/public:avm/res/key-vault/vault:0.12.1' = {
  name: 'kv-${name}-${environmentName}-${resourceToken}'
  scope: spokeRg
  params: {
    name: '${abbrs.keyVaultVaults}${resourceToken}'
    location: location
    sku:  vaultSku
    tags: tags
    enableRbacAuthorization: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow' // Change to 'Deny' if you want to restrict public access
      bypass: 'AzureServices'
    }
    roleAssignments: [
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00482a5a-887f-4fb3-b363-3b7fe8e74483') // Key Vault Administrator
      }
      {
        principalId: uaiAudioAgentBackendIdentity.outputs.principalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'Key Vault Secrets User' 
      }
    ]
    privateEndpoints: [
      {
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: vaultDnsZone.outputs.id
            }
          ]
        }
        subnetResourceId: spokeNetwork.outputs.subnets.privateEndpoint
      }
    ]
    diagnosticSettings: [
      {
        name: 'default'
        workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
        logCategoriesAndGroups: [
          {
            categoryGroup: 'allLogs'
            enabled: true
          }
        ]
        metricCategories: [
          {
            category: 'AllMetrics'
            enabled: true
          }
        ]
      }
    ]
  }
}

param disableLocalAuth bool = true // Set to true to disable local authentication

module speechService 'br/public:avm/res/cognitive-services/account:0.11.0' = {
  name: 'speech-${name}-${environmentName}-${resourceToken}'
  scope: hubRg
  params: {
    // Required parameters
    kind: 'SpeechServices'
    sku: 'S0'
    name: 'speech-${environmentName}-${resourceToken}'
    tags: tags
    // Non-required parameters
    customSubDomainName: 'speech-${environmentName}-${resourceToken}'

    disableLocalAuth: disableLocalAuth
    location: location
    secretsExportConfiguration: disableLocalAuth ? null : {
      accessKey1Name: 'speech-${environmentName}-${resourceToken}-accessKey1'
      keyVaultResourceId: keyVault.outputs.resourceId
    }

    roleAssignments: [
      {
        principalId: acs.outputs.managedIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'Cognitive Services User' // Role for accessing Speech services
      }
      {
        principalId: uaiAudioAgentFrontendIdentity.outputs.principalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'Cognitive Services User' // Role for accessing Speech services
      }
    ]
    publicNetworkAccess: 'Enabled' // Required to integrate with ACS

    diagnosticSettings: [
      {
        name: 'default'
        workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
        logCategoriesAndGroups: [
          {
            categoryGroup: 'allLogs'
            enabled: true
          }
        ]
        metricCategories: [
          {
            category: 'AllMetrics'
            enabled: true
          }
        ]
      }
    ]
  }
}



module acs 'modules/communication/communication-services.bicep' = {
  name: 'acs'
  scope: spokeRg
  params: {
    communicationServiceName: 'acs-${name}-${environmentName}-${resourceToken}'
    keyVaultResourceId: keyVault.outputs.resourceId
    dataLocation: acsDataLocation
    diagnosticSettings: {
      workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    }
  }
}

param jwtAudience string
param entraGroupId string

module aiGateway 'ai-gateway.bicep' = {
  scope: hubRg
  name: 'ai-gateway'
  params: {
    name: name
    audience: jwtAudience
    entraGroupId: entraGroupId
    enableAPIManagement: enableAPIManagement
    location: location
    tags: tags
    apimSku: 'StandardV2'
    virtualNetworkType: 'External'
    backendConfig: azureOpenAIBackendConfig
    apimSubnetResourceId: hubNetwork.outputs.subnets.apim

    // apimDnsZoneId: networkIsolation ? apimDnsZone.outputs.id : ''
    aoaiDnsZoneId: networkIsolation ? openaiDnsZone.outputs.id : ''
    // cosmosDnsZoneId: networkIsolation ? cosmosMongoDnsZone.outputs.id : ''

    // vnetIntegrationSubnetId: spokeNetwork.outputs.subnets.apimOutbound
    privateEndpointSubnetId: spokeNetwork.outputs.subnets.privateEndpoint
    keyVaultResourceId: keyVault.outputs.resourceId
    loggers: [
      {
        credentials: {
          instrumentationKey: monitoring.outputs.applicationInsightsInstrumentationKey
        }
        description: 'Logger to Azure Application Insights'
        isBuffered: false
        loggerType: 'applicationInsights'
        name: 'logger'
        resourceId: monitoring.outputs.applicationInsightsResourceId
      }
    ]
    // privateEndpoints: [
    //   {
    //     privateDnsZoneGroup: {
    //       privateDnsZoneGroupConfigs: [
    //         {
    //           privateDnsZoneResourceId: apimDnsZone.outputs.id
    //         }
    //       ]
    //     }
    //     subnetResourceId: spokeNetwork.outputs.subnets.privateEndpoint
    //   }
    // ]
    // Pass monitoring config from monitoring module
    diagnosticSettings: [
      {
        name: 'default'
        workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
        logCategoriesAndGroups: [
          {
            categoryGroup: 'allLogs'
            enabled: true
          }
        ]
        metricCategories: [
          {
            category: 'AllMetrics'
            enabled: true
          }
        ]
      }
    ]
  }
}


// Store APIM subscription key in Key Vault when API Management is enabled
module apimSubscriptionKeySecret 'modules/vault/secret.bicep' = if (enableAPIManagement) {
  name: 'openai-apim-subscription-key'
  scope: spokeRg
  params: {
    keyVaultName: keyVault.outputs.name
    secretName: 'openai-apim-subscription-key'
    secretValue: aiGateway.outputs.oaiSubscriptionKey
    tags: tags
  }
}

param redisSku string = 'MemoryOptimized_M10' 

module redisEnterprise 'br/public:avm/res/cache/redis-enterprise:0.1.1' = {
  name: 'rtaudio-azureManagedRedis'
  scope: spokeRg
  params: {
    name: 'rtaudio-redis-${resourceToken}'
    skuName: redisSku
  
    database: {
      accessKeysAuthentication: 'Disabled'
      accessPolicyAssignments: [
        {
          name: 'assign1'
          userObjectId: uaiAudioAgentBackendIdentity.outputs.principalId
        }
      ]
      diagnosticSettings: [
        {
          logCategoriesAndGroups: [
            {
              categoryGroup: 'allLogs'
              enabled: true
            }
          ]
          name: 'defaultDBLogs'
          workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
        }
      ]
    }
    diagnosticSettings: [
      {
        metricCategories: [
          {
            category: 'AllMetrics'
          }
        ]
        name: 'defaultClusterMetrics'
        workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
      }
    ]
    privateEndpoints: [
      {
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: redisDnsZone.outputs.id
            }
          ]
        }
        subnetResourceId: spokeNetwork.outputs.subnets.privateEndpoint
      }
    ]
    location: location
    tags: tags
  }
}



// Secrets needed for the application:
// var backendSecrets ContainerAppKvSecret[] = [
//   {
//     name: 'acs-connection-string'
//     keyVaultUrl: acs.outputs.connectionStringSecretUri
//     identity: uaiAudioAgentBackendIdentity.outputs.principalId
//   }
// ]


// Backend:
// AZURE_COSMOS_CONNECTION_STRING
// ACS_CONNECTION_STRING
// AZURE_OPENAI_KEY 


// module loadbalancer 'loadbalancer.bicep' = {
//   scope: rg
//   name: 'loadbalancer'
//   params: {
//     location: location
//     tags: tags
//     vnetName: network.outputs.vnetName
//     subnetResourceIds: network.outputs.subnetResourceIds
//     enableAppGateway: false // Set to true if you want to enable Application Gateway
//     appGatewaySku: 'Standard_v2'
//     backendFqdn: app.outputs.backendBaseUrl
//     publicIpResourceId: network.outputs.publicIpResourceId
//     sslCertBase64: rootCertificateBase64Value
//   }
// }
module app 'app.bicep' = {
  scope: spokeRg
  name: 'app'
  params: {
    name: name
    location: location
    tags: tags

    keyVaultResourceId: keyVault.outputs.resourceId

    aoai_endpoint: aiGateway.outputs.endpoints.openAI
    aoai_chat_deployment_id: 'gpt-4o'
    
    // Monitoring
    appInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
    logAnalyticsWorkspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    principalId: principalId
    principalType: principalType

    // Managed by AZD to deploy code to container apps
    // acsSourcePhoneNumber: acsSourcePhoneNumber
    rtaudioClientExists: rtaudioClientExists
    rtaudioServerExists: rtaudioServerExists

    // Network configuration from network module
    vnetName: spokeNetwork.outputs.vnetName
    appgwSubnetResourceId: hubNetwork.outputs.subnets.loadBalancer
    appSubnetResourceId: spokeNetwork.outputs.subnets.app
  }
}

// module loadbalancer 'loadbalancer.bicep' = {
//   scope: rg
//   name: 'loadbalancer'
//   params: {
//     location: location
//     tags: tags
//     vnetName: network.outputs.vnetName
//     subnetResourceIds: network.outputs.subnetResourceIds
//     enableAppGateway: false // Set to true if you want to enable Application Gateway
//     appGatewaySku: 'Standard_v2'
//     backendFqdn: app.outputs.backendBaseUrl
//     publicIpResourceId: network.outputs.publicIpResourceId
//     sslCertBase64: rootCertificateBase64Value
//   }
// }

// output containerRegistryEndpoint string = app.outputs.containerRegistryEndpoint
// output containerRegistryResourceId string = app.outputs.containerRegistryResourceId
// output containerAppsEnvironmentId string = app.outputs.containerAppsEnvironmentId
// output frontendUserAssignedIdentityClientId string = app.outputs.frontendUserAssignedIdentityClientId
// output frontendUserAssignedIdentityResourceId string = app.outputs.frontendUserAssignedIdentityResourceId
// output backendUserAssignedIdentityClientId string = app.outputs.backendUserAssignedIdentityClientId
// output backendUserAssignedIdentityResourceId string = app.outputs.backendUserAssignedIdentityResourceId
// output communicationServicesResourceId string = app.outputs.communicationServicesResourceId
// output communicationServicesEndpoint string = app.outputs.communicationServicesEndpoint
// output aiGatewayEndpoints array = aiGateway.outputs.aiGatewayEndpoints
// output aiGatewayServiceIds array = aiGateway.outputs.aiGatewayServiceIds
// output frontendContainerAppResourceId string = app.outputs.frontendContainerAppResourceId
// output backendContainerAppResourceId string = app.outputs.backendContainerAppResourceId
// output frontendAppName string = app.outputs.frontendAppName
// output backendAppName string = app.outputs.backendAppName
// output frontendBaseUrl string = app.outputs.frontendBaseUrl
// output backendBaseUrl string = app.outputs.backendBaseUrl

// ==========================================
// EXAMPLE: LOAD BALANCER INTEGRATION
// ==========================================
// Uncomment and configure this section to add Application Gateway

/*
module loadBalancer 'loadbalancer-wrapper.bicep' = {
  scope: hubRg
  name: 'load-balancer'
  params: {
    name: name
    location: location
    tags: tags
    enableLoadBalancer: true
    
    // Network configuration from hub VNet
    networkConfig: {
      subnetResourceId: hubNetwork.outputs.subnets.loadBalancer
      publicIpResourceId: '' // Add public IP resource reference here
    }
    
    // Container app FQDNs from app module
    containerApps: {
      frontend: {
        fqdn: app.outputs.frontendContainerAppFqdn
        name: app.outputs.frontendAppName
      }
      backend: {
        fqdn: app.outputs.backendContainerAppFqdn  
        name: app.outputs.backendAppName
      }
    }
    
    // SSL configuration (optional)
    sslConfig: {
      enabled: false
      certificateName: 'ssl-cert'
      keyVaultSecretId: '${keyVault.outputs.uri}secrets/ssl-certificate'
    }
    
    // Application Gateway configuration
    skuConfig: {
      name: 'WAF_v2'
      tier: 'WAF_v2'
      capacity: {
        minCapacity: 1
        maxCapacity: 3
      }
    }
    
    // WAF settings
    wafConfig: {
      enabled: true
      firewallMode: 'Prevention'
      ruleSetType: 'OWASP'
      ruleSetVersion: '3.2'
    }
  }
  dependsOn: [
    app
    hubNetwork
  ]
}

// Load balancer outputs
output loadBalancerEndpoints object = loadBalancer.outputs.webSocketEndpoints
output frontendPublicUrl string = loadBalancer.outputs.frontendUrl
*/
