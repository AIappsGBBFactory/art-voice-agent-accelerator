// ============================================================================
// DEPLOYMENT METADATA & SCOPE
// ============================================================================

targetScope = 'subscription'

// ============================================================================
// CORE PARAMETERS
// ============================================================================

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@maxLength(20)
@description('Base name for the real-time audio agent application')
param name string = 'rtaudioagent'

@minLength(1)
@description('Primary location for all resources')
param location string

// ============================================================================
// TYPE IMPORTS
// ============================================================================

import { SubnetConfig, BackendConfigItem } from './modules/types.bicep'

// ============================================================================
// APPLICATION CONFIGURATION
// ============================================================================

@description('Flag indicating if the real-time audio client application exists and should be deployed')
param rtaudioClientExists bool

@description('Flag indicating if the real-time audio server application exists and should be deployed')
param rtaudioServerExists bool

@description('Enable API Management for OpenAI load balancing and gateway functionality')
param enableAPIManagement bool = true

@description('Array of backend configurations for Azure OpenAI services when API Management is enabled')
param azureOpenAIBackendConfig BackendConfigItem[]

@description('SKU for Azure Managed Redis')
param redisSku string = 'MemoryOptimized_M10' 

@allowed(['United States', 'Europe', 'Asia Pacific', 'Australia', 'Brazil', 'Canada', 'France', 'Germany', 'India', 'Japan', 'Korea', 'Norway', 'Switzerland', 'UAE', 'UK'])
@description('Data location for Azure Communication Services')
param acsDataLocation string = 'United States'

// ============================================================================
// SECURITY & IDENTITY
// ============================================================================

@description('Principal ID of the user or service principal to assign application roles')
param principalId string

@allowed(['User', 'ServicePrincipal'])
@description('Type of principal (User or ServicePrincipal)')
param principalType string = 'User'

@description('Disable local authentication and use Azure AD/managed identity only')
param disableLocalAuth bool = true

@allowed(['standard', 'premium'])
@description('SKU for Azure Key Vault (standard or premium)')
param vaultSku string = 'standard'
// API Management authentication parameters
// These parameters configure APIM policies for JWT validation and authorization

// The expected audience claim value in JWT tokens for API access validation
// This should match the audience configured in your identity provider
@description('The JWT audience claim value used for token validation in APIM policies')
param jwtAudience string

// The Azure Entra ID group object ID that grants access to the API
// Users must be members of this group to access protected endpoints
@description('Azure Entra ID group object ID for user authorization in APIM policies')
param entraGroupId string

// ============================================================================
// NETWORK CONFIGURATION
// ============================================================================

@description('Name of the hub virtual network')
param hubVNetName string = 'vnet-hub-${name}-${environmentName}'

@description('Name of the spoke virtual network')
param spokeVNetName string = 'vnet-spoke-${name}-${environmentName}'

@description('Address prefix for the hub virtual network (CIDR notation)')
param hubVNetAddressPrefix string = '10.0.0.0/16'

@description('Address prefix for the spoke virtual network (CIDR notation)')
param spokeVNetAddressPrefix string = '10.1.0.0/16'

// ============================================================================
// CONSTANTS & COMPUTED VALUES
// ============================================================================

// Load Azure naming abbreviations for consistent resource naming
var abbrs = loadJsonContent('./abbreviations.json')

// Generate unique resource token based on subscription, environment, and location
var resourceToken = uniqueString(subscription().id, environmentName, location)
param hubSubnets SubnetConfig[] = [
  {
    name: 'loadBalancer'          // App Gateway or L4 LB
    addressPrefix: '10.0.0.0/27'
  }
  {
    name: 'services'          // Shared services like monitor, orchestrators (if colocated)
    addressPrefix: '10.0.0.64/26'
  }
  {
    name: 'jumpbox'               // Optional, minimal size
    addressPrefix: '10.0.10.0/27'
  }
  {
    name: 'apim'
    addressPrefix: '10.0.1.0/27'
    delegations: [
      {
        name: 'Microsoft.Web/serverFarms'
        properties: {
          serviceName: 'Microsoft.Web/serverFarms'
        }
      }
    ]
    securityRules: [
      {
        name: 'AllowHTTPS'
        properties: {
          priority: 1000
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowHTTP'
        properties: {
          priority: 1010
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AllowAPIMManagement'
        properties: {
          priority: 1020
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: 'ApiManagement'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '3443'
        }
      }
      {
        name: 'AllowLoadBalancer'
        properties: {
          priority: 1030
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '6390'
        }
      }
      {
        name: 'AllowOutboundHTTPS'
        properties: {
          priority: 1000
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Outbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowOutboundHTTP'
        properties: {
          priority: 1010
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Outbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AllowOutboundSQL'
        properties: {
          priority: 1020
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Outbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Sql'
          destinationPortRange: '1433'
        }
      }
      {
        name: 'AllowOutboundStorage'
        properties: {
          priority: 1030
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Outbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Storage'
          destinationPortRange: '443'
        }
      }
    ]
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
// ============================================================================
// MONITORING & OBSERVABILITY
// ============================================================================

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

// ============================================================================
// JUMPHOST (OPTIONAL - ONLY WHEN NETWORK ISOLATION ENABLED)
// ============================================================================

module winJumphost 'modules/jumphost/windows-vm.bicep' = if (networkIsolation) {
  name: 'win-jumphost'
  scope: hubRg
  params: {
    vmName: 'jumphost-${name}-${environmentName}'
    location: location
    adminUsername: 'azureuser'
    adminPassword: 'P@ssw0rd!' // TODO: Replace with Key Vault reference
    vmSize: 'Standard_B2s'
    subnetId: hubNetwork.outputs.subnets.jumpbox
    tags: tags
  }
}

// ============================================================================
// VIRTUAL NETWORKS (HUB & SPOKE TOPOLOGY)
// ============================================================================

// Hub VNet - Contains shared services, monitoring, and network appliances
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
  }
}

// Spoke VNet - Contains application workloads and private endpoints
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
  }
}

// ============================================================================
// PRIVATE DNS ZONES FOR AZURE SERVICES
// ============================================================================

// Storage Account (Blob) private DNS zone
module blobDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'blob-dns-zone'
  scope: hubRg
  params: {
    #disable-next-line no-hardcoded-env-urls
    dnsZoneName: 'privatelink.blob.core.windows.net'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// API Management private DNS zone
module apimDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'apim-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.azure-api.net'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Cosmos DB (MongoDB API) private DNS zone
module cosmosMongoDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'cosmos-mongo-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.mongo.cosmos.azure.com'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Cosmos DB (Core/SQL API) private DNS zone
module documentsDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'cosmos-documents-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.documents.azure.com'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Key Vault private DNS zone
module vaultDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'keyvault-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.vaultcore.azure.net'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Container Apps private DNS zone
module containerAppsDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'container-apps-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.${location}.azurecontainerapps.io'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Azure Container Registry private DNS zone
module acrDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'acr-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.${location}.azurecr.io'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Cognitive Services private DNS zone
module aiservicesDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'cognitive-services-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.cognitiveservices.azure.com'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Azure OpenAI private DNS zone
module openaiDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'openai-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.openai.azure.com'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Azure Cognitive Search private DNS zone
module searchDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'search-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.search.windows.net'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// Azure Cache for Redis Enterprise private DNS zone
module redisDnsZone './modules/networking/private-dns-zone.bicep' = if (networkIsolation) {
  name: 'redis-enterprise-dns-zone'
  scope: hubRg
  params: {
    dnsZoneName: 'privatelink.redis.azure.net'
    tags: tags
    virtualNetworkName: hubNetwork.outputs.vnetName
  }
}

// ============================================================================
// VNET PEERING (HUB-SPOKE CONNECTIVITY)
// ============================================================================

// Hub to Spoke peering
module peerHubToSpoke './modules/networking/peer-virtual-networks.bicep' = {
  scope: hubRg
  name: 'peer-hub-to-spoke'
  params: {
    localVnetName: hubNetwork.outputs.vnetName
    remoteVnetId: spokeNetwork.outputs.vnetId
    remoteVnetName: spokeNetwork.outputs.vnetName
  }
}

// Spoke to Hub peering
module peerSpokeToHub './modules/networking/peer-virtual-networks.bicep' = {
  scope: spokeRg
  name: 'peer-spoke-to-hub'
  params: {
    localVnetName: spokeNetwork.outputs.vnetName
    remoteVnetId: hubNetwork.outputs.vnetId
    remoteVnetName: hubNetwork.outputs.vnetName
  }
  dependsOn: [
    peerHubToSpoke
  ]
}

// ============================================================================
// APPLICATION MANAGED IDENTITIES
// ============================================================================

// User-assigned managed identity for backend services
module uaiAudioAgentBackendIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'backend-managed-identity'
  scope: spokeRg
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}backend-${resourceToken}'
    location: location
    tags: tags
  }
}

// User-assigned managed identity for frontend services
module uaiAudioAgentFrontendIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'frontend-managed-identity'
  scope: spokeRg
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}frontend-${resourceToken}'
    location: location
    tags: tags
  }
}

// ============================================================================
// KEY VAULT FOR SECRETS MANAGEMENT
// ============================================================================

module keyVault 'br/public:avm/res/key-vault/vault:0.12.1' = {
  name: 'key-vault'
  scope: spokeRg
  params: {
    name: '${abbrs.keyVaultVaults}${resourceToken}'
    location: location
    sku: vaultSku
    tags: tags
    enableRbacAuthorization: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow' // TODO: Change to 'Deny' for production with proper firewall rules
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

// ============================================================================
// AZURE SPEECH SERVICES
// ============================================================================

module speechService 'br/public:avm/res/cognitive-services/account:0.11.0' = {
  name: 'speech-service'
  scope: hubRg
  params: {
    kind: 'SpeechServices'
    sku: 'S0'
    name: 'speech-${environmentName}-${resourceToken}'
    customSubDomainName: 'speech-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    disableLocalAuth: disableLocalAuth
    
    // Store access keys in Key Vault if local auth is enabled
    secretsExportConfiguration: disableLocalAuth ? null : {
      accessKey1Name: 'speech-${environmentName}-${resourceToken}-accessKey1'
      keyVaultResourceId: keyVault.outputs.resourceId
    }

    // Grant access to ACS and Frontend identity
    roleAssignments: [
      {
        principalId: acs.outputs.managedIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'Cognitive Services User'
      }
      {
        principalId: uaiAudioAgentFrontendIdentity.outputs.principalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'Cognitive Services User'
      }
    ]
    
    publicNetworkAccess: 'Enabled' // Required for ACS integration
    
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

// ============================================================================
// AZURE COMMUNICATION SERVICES
// ============================================================================

// Communication Service for real-time voice and messaging
// NOTE: Phone number provisioning must be done manually after deployment
module acs 'modules/communication/communication-services.bicep' = {
  name: 'communication-services'
  scope: hubRg
  params: {
    communicationServiceName: 'acs-${name}-${environmentName}-${resourceToken}'
    dataLocation: acsDataLocation
    diagnosticSettings: {
      workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    }
    tags: tags
  }
}

// Store ACS connection string in Key Vault
module acsConnectionStringSecret 'modules/vault/secret.bicep' = {
  name: 'acs-connection-string-secret'
  scope: spokeRg
  params: {
    keyVaultName: keyVault.outputs.name
    secretName: '${acs.outputs.communicationServiceName}-connection-string'
    secretValue: acs.outputs.connectionString
    tags: tags
  }
}

// Store ACS primary key in Key Vault
module acsPrimaryKeySecret 'modules/vault/secret.bicep' = {
  name: 'acs-primary-key-secret'
  scope: spokeRg
  params: {
    keyVaultName: keyVault.outputs.name
    secretName: 'acs-primary-key'
    secretValue: acs.outputs.primaryKey
    tags: tags
  }
}

// ============================================================================
// AI GATEWAY (API MANAGEMENT + AZURE OPENAI)
// ============================================================================

module aiGateway 'ai-gateway.bicep' = {
  scope: hubRg
  name: 'ai-gateway'
  params: {
    name: name
    location: location
    tags: tags
    
    // JWT and security configuration
    audience: jwtAudience
    entraGroupId: entraGroupId
    
    // APIM configuration
    enableAPIManagement: enableAPIManagement
    apimSku: 'StandardV2'
    virtualNetworkType: 'External'
    backendConfig: azureOpenAIBackendConfig
    apimSubnetResourceId: hubNetwork.outputs.subnets.apim
    
    // Private DNS and networking
    aoaiDnsZoneId: networkIsolation ? openaiDnsZone.outputs.id : ''
    privateEndpointSubnetId: spokeNetwork.outputs.subnets.privateEndpoint
    keyVaultResourceId: keyVault.outputs.resourceId
    
    // Application Insights logging
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
    
    // Diagnostic settings
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

// Store APIM subscription key in Key Vault
module apimSubscriptionKeySecret 'modules/vault/secret.bicep' = if (enableAPIManagement) {
  name: 'apim-subscription-key-secret'
  scope: spokeRg
  params: {
    keyVaultName: keyVault.outputs.name
    secretName: 'openai-apim-subscription-key'
    secretValue: aiGateway.outputs.openAiSubscriptionKey
    tags: tags
  }
}

// ============================================================================
// REDIS ENTERPRISE CACHE
// ============================================================================

module redisEnterprise 'br/public:avm/res/cache/redis-enterprise:0.1.1' = {
  name: 'redis-enterprise'
  scope: spokeRg
  params: {
    name: 'redis-${name}-${resourceToken}'
    location: location
    tags: tags
    skuName: redisSku
    
    // Database configuration with RBAC authentication
    database: {
      accessKeysAuthentication: 'Disabled' // Use RBAC instead of access keys
      accessPolicyAssignments: [
        {
          name: 'backend-access'
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
          name: 'redis-database-logs'
          workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
        }
      ]
    }
    
    // Cluster-level diagnostics
    diagnosticSettings: [
      {
        metricCategories: [
          {
            category: 'AllMetrics'
          }
        ]
        name: 'redis-cluster-metrics'
        workspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
      }
    ]
    
    // Private endpoint configuration
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
  }
}

// ============================================================================
// APPLICATION SERVICES (CONTAINER APPS)
// ============================================================================

module app 'app.bicep' = {
  scope: spokeRg
  name: 'application-services'
  params: {
    name: name
    location: location
    tags: tags
    
    // Key Vault for secrets
    keyVaultResourceId: keyVault.outputs.resourceId
    
    // Azure OpenAI configuration
    aoai_endpoint: aiGateway.outputs.endpoints.openAI
    aoai_chat_deployment_id: 'gpt-4o'
    
    // Monitoring configuration
    appInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
    logAnalyticsWorkspaceResourceId: monitoring.outputs.logAnalyticsWorkspaceResourceId
    
    // RBAC configuration
    principalId: principalId
    principalType: principalType
    
    // Application deployment flags
    rtaudioClientExists: rtaudioClientExists
    rtaudioServerExists: rtaudioServerExists
    
    // Network configuration
    appSubnetResourceId: spokeNetwork.outputs.subnets.app
    privateEndpointSubnetId: spokeNetwork.outputs.subnets.privateEndpoint
    cosmosDnsZoneId: cosmosMongoDnsZone.outputs.id
  }
}

// ============================================================================
// OUTPUTS FOR AZD INTEGRATION
// ============================================================================

output AZURE_RESOURCE_GROUP string = spokeRg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = app.outputs.containerRegistryEndpoint
