@description('The location used for all deployed resources')
param location string = resourceGroup().location

@description('Tags that will be applied to all resources')
param tags object = {}

@description('Name of the environment that can be used as part of naming resource convention')
param name string

import { ContainerAppKvSecret } from './modules/types.bicep'

// AZD managed variables
param rtaudioClientExists bool
param rtaudioServerExists bool
param acsSourcePhoneNumber string = ''

// Required parameters for the app environment (app config values, secrets, etc.)
@description('Enable EasyAuth for the frontend internet facing container app')
param enableEasyAuth bool = true

param appInsightsConnectionString string = 'InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://dc.services.visualstudio.com/v2/track'
param logAnalyticsWorkspaceResourceId string = '00000000-0000-0000-0000-000000000000'

// Key Vault parameters
param keyVaultResourceId string

// Network parameters for reference
// param vnetName string
// param appgwSubnetResourceId string
param appSubnetResourceId string

@description('Id of the user or app to assign application roles')
param principalId string
param principalType string

// App Dependencies
param aoai_endpoint string
param aoai_chat_deployment_id string
// param acsResourceId string = ''


var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = uniqueString(subscription().id, resourceGroup().id, location)


// param apimDnsZoneId string = '' // Optional DNS zone ID for APIM, can be used for private endpoints
// param aoaiDnsZoneId string = '' // Optional DNS zone ID for Azure OpenAI, can be used for private endpoints
param cosmosDnsZoneId string = '' // Optional DNS zone ID for Cosmos DB, can be used for private endpoints
param privateEndpointSubnetId string = '' // Subnet ID for private endpoints, if applicable

param disableLocalAuth bool = true // Keep enabled for now, can be disabled in prod
// param vnetIntegrationSubnetId string = ''
// param privateEndpoints array = []


module frontendUserAssignedIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'gbbAiAudioAgentidentity'
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}gbbAiAudioAgent-${resourceToken}'
    location: location
  }
}

module backendUserAssignedIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.2.1' = {
  name: 'gbbAiAudioAgentBackendIdentity'
  params: {
    name: '${name}${abbrs.managedIdentityUserAssignedIdentities}gbbAiAudioAgentBackend-${resourceToken}'
    location: location
  }
}

var beContainerName =  toLower(substring('rtagent-server-${resourceToken}', 0, 22))
var feContainerName =  toLower(substring('rtagent-client-${resourceToken}', 0, 22))


// Cosmos DB MongoDB Cluster
resource mongoCluster 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'mongo-${name}-${resourceToken}'
  location: location
  tags: tags
  kind: 'MongoDB'
  properties: {
    disableLocalAuth: disableLocalAuth
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    // administrator: {
    //   userName: cosmosAdministratorUsername
    //   password: cosmosAdministratorPassword
    // }
    apiProperties: {
      serverVersion: '7.0'
    }

    capabilities: [
      {
        name: 'EnableMongo'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: 'Enabled'

  }
}



module mongoPrivateEndpoint 'br/public:avm/res/network/private-endpoint:0.7.1' = {
  name: 'mongo-pe-${name}-${resourceToken}'
  params: {
    name: 'mongo-pe-${name}-${resourceToken}'
    location: location
    subnetResourceId: privateEndpointSubnetId
    privateLinkServiceConnections: [
      {
        name: 'mongo-pls-${name}-${resourceToken}'
        properties: {
          privateLinkServiceId: mongoCluster.id
          groupIds: [
            'MongoDB'
          ]
        }
      }
    ]
    privateDnsZoneGroup: {
      privateDnsZoneGroupConfigs: [
        {
          name: 'default'
          privateDnsZoneResourceId: cosmosDnsZoneId
        }
      ]
    }
  }
}

// Store MongoDB connection string in Key Vault if local auth is enabled
resource mongoConnectionString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!disableLocalAuth) {
  name: '${last(split(keyVaultResourceId, '/'))}/mongo-connection-string'
  properties: {
    value: mongoCluster.listConnectionStrings().connectionStrings[0].connectionString
  }
}




// Container registry
module containerRegistry 'br/public:avm/res/container-registry/registry:0.1.1' = {
  name: 'registry'
  params: {
    name: '${name}${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
    publicNetworkAccess: 'Enabled'
    roleAssignments: [
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: 'AcrPull'
      }
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: 'AcrPush'
      }
      // Temporarily disabled - managed identity deployment timing issue
      // {
      //   principalId: frontendUserAssignedIdentity.outputs.principalId
      //   principalType: 'ServicePrincipal'
      //   roleDefinitionIdOrName: 'AcrPull'
      // }
      // {
      //   principalId: backendUserAssignedIdentity.outputs.principalId
      //   principalType: 'ServicePrincipal'
      //   roleDefinitionIdOrName: 'AcrPull'
      // }
    ]
  }
}

param frontendExternalAccessEnabled bool = true
// Container apps environment (deployed into appSubnet)
module externalContainerAppsEnvironment 'br/public:avm/res/app/managed-environment:0.11.2' = if (frontendExternalAccessEnabled){
  name: 'external-container-apps-environment'
  params: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: reference(logAnalyticsWorkspaceResourceId, '2022-10-01').customerId
        sharedKey: listKeys(logAnalyticsWorkspaceResourceId, '2022-10-01').primarySharedKey
      }
    }
    name: 'ext-${name}${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    zoneRedundant: false
    // infrastructureSubnetResourceId: appSubnetResourceId // Enables private networking in the specified subnet
    internal: false
    tags: tags
  }
}
// Container apps environment (deployed into appSubnet)
module containerAppsEnvironment 'br/public:avm/res/app/managed-environment:0.11.2' = {
  name: 'container-apps-environment'
  params: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: reference(logAnalyticsWorkspaceResourceId, '2022-10-01').customerId
        sharedKey: listKeys(logAnalyticsWorkspaceResourceId, '2022-10-01').primarySharedKey
      }
    }
    name: '${name}${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    zoneRedundant: false
    infrastructureSubnetResourceId: appSubnetResourceId // Enables private networking in the specified subnet
    internal: appSubnetResourceId != '' ? true : false
    tags: tags
  }
}

param storageSkuName string = 'Standard_LRS'
param storageContainerName string = 'audioagent'


module storage 'br/public:avm/res/storage/storage-account:0.9.1' = {
  name: 'storage'
  params: {
    name: '${abbrs.storageStorageAccounts}${resourceToken}'
    location: location
    tags: tags
    kind: 'StorageV2'
    skuName: storageSkuName
    publicNetworkAccess: 'Enabled' // Necessary for uploading documents to storage container
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    blobServices: {
      deleteRetentionPolicyDays: 2
      deleteRetentionPolicyEnabled: true
      containers: [
        {
          name: storageContainerName
          publicAccess: 'None'
        }
        {
          name: 'prompt'
          publicAccess: 'None'
        }
      ]
    }
    roleAssignments: [
      // {
      //   roleDefinitionIdOrName: 'Storage Blob Data Contributor'
      //   principalId: backendUserAssignedIdentity.outputs.principalId
      //   principalType: 'ServicePrincipal'
      // }
      // {
      //   roleDefinitionIdOrName: 'Storage Blob Data Reader'
      //   principalId: principalId
      //   // principalType: 'User'  
      //   principalType: principalType
      // } 
      // {
      //   roleDefinitionIdOrName: 'Storage Blob Data Contributor'
      //   principalId: principalId
      //   // principalType: 'User'
      //   principalType: principalType
      // }      
    ]
  }
}

module fetchFrontendLatestImage './modules/app/fetch-container-image.bicep' = {
  name: 'gbbAiAudioAgent-fetch-image'
  params: {
    exists: rtaudioClientExists
    name: feContainerName
  }
}
module fetchBackendLatestImage './modules/app/fetch-container-image.bicep' = {
  name: 'gbbAiAudioAgentBackend-fetch-image'
  params: {
    exists: rtaudioServerExists
    name: beContainerName
  }
}

module frontendAudioAgent 'modules/app/container-app.bicep' = {
  name: 'frontend-audio-agent'
  params: {
    name: feContainerName
    enableEasyAuth: enableEasyAuth
    corsPolicy: {
      allowedOrigins: [
        'http://localhost:5173'
        'http://localhost:3000'
      ]
      allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
      allowedHeaders: ['*']
      allowCredentials: false
    }
    
    publicAccessAllowed: true

    ingressTargetPort: 5173
    scaleMinReplicas: 1
    scaleMaxReplicas: 10
    stickySessionsAffinity: 'sticky'
    containers: [
      {
        image: fetchFrontendLatestImage.outputs.?containers[?0].?image ?? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
        name: 'main'
        resources: {
          cpu: json('0.5')
          memory: '1.0Gi'
        }
        env: [
          {
            name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
            value: appInsightsConnectionString
          }
          {
            name: 'AZURE_CLIENT_ID'
            value: frontendUserAssignedIdentity.outputs.clientId
          }
          {
            name: 'PORT'
            value: '5173'
          }
          // {
          //   name: 'VITE_BACKEND_BASE_URL'
          //   value: 'https://${existingAppGatewayPublicIp.properties.dnsSettings.fqdn}'
          // }
        ]
      }
    ]
    userAssignedResourceId: frontendUserAssignedIdentity.outputs.resourceId

    registries: [
      // Temporarily disabled - managed identity access issue
      {
        server: containerRegistry.outputs.loginServer
        identity: frontendUserAssignedIdentity.outputs.resourceId
      }
    ]
    
    environmentResourceId: frontendExternalAccessEnabled ? externalContainerAppsEnvironment.outputs.resourceId : containerAppsEnvironment.outputs.resourceId
    // environmentResourceId: containerAppsEnvironment.outputs.resourceId
    location: location
    tags: union(tags, { 'azd-service-name': 'rtaudio-client' })
  }
  dependsOn: [
    containerAppsEnvironment
    frontendUserAssignedIdentity
    fetchFrontendLatestImage
  ]
}

// @description('Resource ID of an existing Application Gateway to use')
// param existingAppGatewayResourceName string = 'ai-realtime-sandbox-wus2-appgw'
// param existingAppGatewayResourceGroupName string = 'ai-realtime-sandbox'

// resource existingAppGateway 'Microsoft.Network/applicationGateways@2022-09-01' existing = if (!empty(existingAppGatewayResourceName)) {
//   scope: resourceGroup(existingAppGatewayResourceGroupName)
//   name: existingAppGatewayResourceName
// }

// @description('Name of the existing public IP address associated with the Application Gateway')
// param existingAppGatewayPublicIpName string = 'ai-realtime-sandbox-appgw-pip'

// resource existingAppGatewayPublicIp 'Microsoft.Network/publicIPAddresses@2022-05-01' existing = if (!empty(existingAppGatewayPublicIpName)) {
//   scope: resourceGroup(existingAppGatewayResourceGroupName)
//   name: existingAppGatewayPublicIpName
// }



// param backendSecrets ContainerAppKvSecret[] 

module backendAudioAgent './modules/app/container-app.bicep' = {
  name: 'backend-audio-agent'
  params: {
    name: beContainerName
    ingressTargetPort: 8010
    scaleMinReplicas: 1
    scaleMaxReplicas: 10
    corsPolicy: {
      allowedOrigins: [
      // 'https://${frontendAudioAgent.outputs.containerAppFqdn}'
      // 'https://${existingAppGatewayPublicIp.properties.dnsSettings.fqdn}'
      // 'https://${existingAppGatewayPublicIp.properties.ipAddress}'
      'http://localhost:5173'
      ]
      allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
      allowedHeaders: ['*']
      allowCredentials: true
    }
    containers: [
      {
        image: fetchBackendLatestImage.outputs.?containers[?0].?image ?? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
        name: 'main'
        resources: {
          cpu: json('1.0')
          memory: '2.0Gi'
        }
        // secrets: backendSecrets

        env: [
          {
            name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
            value: appInsightsConnectionString
          }
          {
            name: 'AZURE_CLIENT_ID'
            value: backendUserAssignedIdentity.outputs.clientId
          }
          {
            name: 'PORT'
            value: '8010'
          }
          {
            name: 'AZURE_OPENAI_ENDPOINT'
            value: aoai_endpoint
          }
          {
            name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_ID'
            value: aoai_chat_deployment_id
          }
          // { // For when RBAC access to speech service is enabled
          //   name: 'AZURE_SPEECH_RESOURCE_ID'
          //   value: aiGateway.outputs.aiServicesIds[0]
          // }
          // {
          //   name: 'REDIS_HOST'
          //   value: redis_host
          // }
          // {
          //   name: 'REDIS_PORT'
          //   value: redis_port
          // }
          {
            name: 'AZURE_SPEECH_REGION'
            value: location
          }
          // {
          //   name: 'BASE_URL'
          //   value: 'https://${existingAppGatewayPublicIp.properties.ipAddress}'
          // }
          {
            name: 'ACS_SOURCE_PHONE_NUMBER'
            value: acsSourcePhoneNumber
          }
          // {  // For when ACS RBAC is enabled
          //   name: 'ACS_RESOURCE_ENDPOINT'
          //   value: 'https://${communicationServices.properties.hostName}'
          // }
          {
            name: 'USE_ENTRA_CREDENTIALS'
            value: 'true'
          }
        ]
      }
    ]
    userAssignedResourceId: backendUserAssignedIdentity.outputs.resourceId
    // managedIdentities: {
    //   userAssignedResourceIds: [
    //     backendUserAssignedIdentity.outputs.resourceId
    //   ]
    // }
    registries: [
      {
        server: containerRegistry.outputs.loginServer
        identity: backendUserAssignedIdentity.outputs.resourceId
      }
    ]
    environmentResourceId: containerAppsEnvironment.outputs.resourceId
    location: location
    tags: union(tags, { 'azd-service-name': 'rtaudio-server' })
  }
}


// Outputs for downstream consumption and integration

// Container Registry
output containerRegistryEndpoint string = containerRegistry.outputs.loginServer
output containerRegistryResourceId string = containerRegistry.outputs.resourceId

// Container Apps Environment
output containerAppsEnvironmentId string = containerAppsEnvironment.outputs.resourceId

// User Assigned Identities
output frontendUserAssignedIdentityClientId string = frontendUserAssignedIdentity.outputs.clientId
output frontendUserAssignedIdentityResourceId string = frontendUserAssignedIdentity.outputs.resourceId
output backendUserAssignedIdentityClientId string = backendUserAssignedIdentity.outputs.clientId
output backendUserAssignedIdentityResourceId string = backendUserAssignedIdentity.outputs.resourceId

// // Communication Services
// output communicationServicesResourceId string = communicationServices.id
// output communicationServicesEndpoint string = communicationServices.properties.hostName

// Container Apps
// output frontendContainerAppResourceId string = frontendAudioAgent.outputs.containerAppResourceId
output backendContainerAppResourceId string = backendAudioAgent.outputs.containerAppResourceId
output frontendAppName string = feContainerName
output backendAppName string = beContainerName

// Application Gateway Integration
// output frontendBaseUrl string = 'https://${existingAppGatewayPublicIp.properties.dnsSettings.fqdn}'
// output backendBaseUrl string = 'https://${existingAppGatewayPublicIp.properties.ipAddress}'



// NOTE: These parameters are currently not used directly in this file, but are available for future use and for passing to modules that support subnet assignment.
