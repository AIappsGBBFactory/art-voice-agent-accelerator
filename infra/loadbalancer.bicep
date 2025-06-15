
targetScope = 'resourceGroup'

// ==========================================
// LOAD BALANCER MODULE WRAPPER
// ==========================================
// This module provides a simplified interface for deploying 
// Application Gateway with the Real-Time Audio Agent infrastructure

@description('Name prefix for the load balancer resources')
param name string

@description('Location for all resources')
param location string = resourceGroup().location

@description('Tags to apply to all resources')
param tags object = {}

@description('Enable Application Gateway deployment')
param enableLoadBalancer bool = true

@description('Network configuration')
param networkConfig object = {
  subnetResourceId: ''
  publicIpResourceId: ''
}

@description('Container app configuration from app module outputs')
param containerApps object = {
  frontend: {
    fqdn: ''
    name: ''
  }
  backend: {
    fqdn: ''
    name: ''
  }
}

@description('SSL certificate configuration')
param sslConfig object = {
  enabled: false
  certificateName: ''
  keyVaultSecretId: ''
}

@description('Application Gateway SKU configuration')
param skuConfig object = {
  name: 'WAF_v2'
  tier: 'WAF_v2'
  capacity: {
    minCapacity: 0
    maxCapacity: 10
  }
}

@description('Web Application Firewall configuration')
param wafConfig object = {
  enabled: true
  firewallMode: 'Prevention'
  ruleSetType: 'OWASP'
  ruleSetVersion: '3.0'
}

// ==========================================
// VARIABLES
// ==========================================

var resourceToken = uniqueString(resourceGroup().id, name, location)
var appGatewayName = '${name}-appgw-${resourceToken}'

// ==========================================
// APPLICATION GATEWAY DEPLOYMENT
// ==========================================

module applicationGateway 'loadbalancer-fixed.bicep' = if (enableLoadBalancer) {
  name: 'application-gateway'
  params: {
    enableAppGateway: enableLoadBalancer
    location: location
    tags: tags
    
    // Basic configuration
    appGatewayName: appGatewayName
    subnetResourceId: networkConfig.subnetResourceId
    publicIpResourceId: networkConfig.publicIpResourceId
    
    // SKU and capacity
    appGatewaySku: skuConfig.name
    appGatewayTier: skuConfig.tier
    capacity: skuConfig.capacity
    
    // WAF configuration
    wafConfiguration: wafConfig
    
    // Container app integration
    containerAppConfig: {
      frontend: {
        fqdn: containerApps.frontend.fqdn
        name: containerApps.frontend.name
        healthPath: '/health'
      }
      backend: {
        fqdn: containerApps.backend.fqdn
        name: containerApps.backend.name
        healthPath: '/healthz'
      }
    }
    
    // SSL configuration
    certificateConfig: sslConfig
    
    // Dynamic backend configuration (will be overridden by containerAppConfig)
    frontendAppFqdn: containerApps.frontend.fqdn
    backendAppFqdn: containerApps.backend.fqdn
  }
}

// ==========================================
// OUTPUTS
// ==========================================

@description('Application Gateway resource ID')
output appGatewayId string = enableLoadBalancer ? applicationGateway.outputs.appGatewayId : ''

@description('Application Gateway name')
output appGatewayName string = enableLoadBalancer ? applicationGateway.outputs.appGatewayName : ''

@description('Frontend application URL')
output frontendUrl string = enableLoadBalancer ? applicationGateway.outputs.frontendUrl : ''

@description('WebSocket endpoints for real-time communication')
output webSocketEndpoints object = enableLoadBalancer ? applicationGateway.outputs.webSocketEndpoints : {}

@description('API endpoints configuration')
output apiEndpoints object = enableLoadBalancer ? applicationGateway.outputs.apiEndpoints : {}

@description('Health check endpoints')
output healthCheckEndpoints array = enableLoadBalancer ? applicationGateway.outputs.healthCheckEndpoints : []

@description('Configuration summary')
output configurationSummary object = enableLoadBalancer ? applicationGateway.outputs.configurationSummary : {}

@description('Backend pool summary')
output backendPoolSummary array = enableLoadBalancer ? applicationGateway.outputs.backendPoolSummary : []

@description('HTTP listener summary')
output httpListenerSummary array = enableLoadBalancer ? applicationGateway.outputs.httpListenerSummary : []

@description('Application Gateway operational state')
output operationalState string = enableLoadBalancer ? applicationGateway.outputs.operationalState : 'Disabled'

@description('Enable private frontend IP configuration')
param enablePrivateFrontend bool = false

// Backend Configuration
@description('Backend pools configuration')
param backendPools array = [
  {
    name: 'default-backend-pool'
    fqdns: []
    ipAddresses: []
  }
]

@description('Backend HTTP settings configuration')
param backendHttpSettings array = [
  {
    name: 'default-http-setting'
    port: 80
    protocol: 'Http'
    cookieBasedAffinity: 'Disabled'
    requestTimeout: 30
    connectionDraining: {
      enabled: true
      drainTimeoutInSec: 300
    }
    pickHostNameFromBackendAddress: false
    hostName: ''
    path: ''
    trustedRootCertificateNames: []
    authenticationCertificateNames: []
  }
]

// SSL/TLS Configuration
@description('SSL certificates configuration')
param sslCertificates array = []

@description('Trusted root certificates configuration')
param trustedRootCertificates array = []

@description('Trusted client certificates configuration')
param trustedClientCertificates array = []

@description('SSL profiles configuration')
param sslProfiles array = []

@description('SSL policy configuration')
param sslPolicy object = {
  policyType: 'Predefined'
  policyName: 'AppGwSslPolicy20220101S'
}

// Listener Configuration
@description('Frontend ports configuration')
param frontendPorts array = [
  {
    name: 'port-80'
    port: 80
  }
  {
    name: 'port-443'
    port: 443
  }
]

@description('HTTP listeners configuration')
param httpListeners array = [
  {
    name: 'default-http-listener'
    frontendIPConfigurationName: 'public-frontend'
    frontendPortName: 'port-80'
    protocol: 'Http'
    hostName: ''
    requireServerNameIndication: false
    sslCertificateName: ''
    firewallPolicyId: ''
  }
]

// Routing Configuration
@description('Request routing rules configuration')
param requestRoutingRules array = [
  {
    name: 'default-routing-rule'
    ruleType: 'Basic'
    httpListenerName: 'default-http-listener'
    backendAddressPoolName: 'default-backend-pool'
    backendHttpSettingsName: 'default-http-setting'
    redirectConfigurationName: ''
    urlPathMapName: ''
    priority: 100
  }
]

@description('URL path maps configuration')
param urlPathMaps array = []

@description('Redirect configurations')
param redirectConfigurations array = []

// Health Probe Configuration
@description('Health probes configuration')
param healthProbes array = [
  {
    name: 'default-health-probe'
    protocol: 'Http'
    host: ''
    path: '/health'
    interval: 30
    timeout: 30
    unhealthyThreshold: 3
    pickHostNameFromBackendHttpSettings: true
    minServers: 0
    match: {
      body: ''
      statusCodes: ['200-399']
    }
  }
]

// WAF Configuration
@description('Web Application Firewall configuration')
param wafConfiguration object = {
  enabled: true
  firewallMode: 'Prevention'
  ruleSetType: 'OWASP'
  ruleSetVersion: '3.2'
  fileUploadLimitInMb: 100
  requestBodyCheck: true
  maxRequestBodySizeInKb: 128
  disabledRuleGroups: []
  exclusions: []
}

@description('Firewall policy resource ID (optional)')
param firewallPolicyId string = ''

// Rewrite Rules Configuration
@description('Rewrite rule sets configuration')
param rewriteRuleSets array = []

// Custom Error Configuration
@description('Custom error configurations')
param customErrorConfigurations array = []

// Global Configuration
@description('Global configuration settings')
param globalConfiguration object = {
  enableRequestBuffering: false
  enableResponseBuffering: false
}

// Managed Identity Configuration
@description('Enable system assigned managed identity')
param enableSystemManagedIdentity bool = false

@description('User assigned managed identity resource IDs')
param userAssignedIdentityIds array = []

// Private Link Configuration
@description('Private link configurations')
param privateLinkConfigurations array = []

// Authentication Configuration
@description('Authentication certificates configuration')
param authenticationCertificates array = []

// Monitoring and Diagnostics
@description('Enable HTTP/2')
param enableHttp2 bool = true

@description('Enable FIPS')
param enableFips bool = false

@description('Force firewall policy association')
param forceFirewallPolicyAssociation bool = false

// Computed variables for complex configurations
var identityType = enableSystemManagedIdentity && !empty(userAssignedIdentityIds) ? 'SystemAssigned, UserAssigned' 
  : enableSystemManagedIdentity ? 'SystemAssigned' 
  : 'UserAssigned'

var userAssignedIdentityDict = !empty(userAssignedIdentityIds) ? reduce(userAssignedIdentityIds, {}, (acc, id) => union(acc, { '${id}': {} })) : {}

// Helper variables for backend address processing
var backendAddressesFlattened = [for pool in backendPools: {
  name: pool.name
  addresses: union(
    map(pool.?fqdns ?? [], fqdn => { fqdn: fqdn }),
    map(pool.?ipAddresses ?? [], ip => { ipAddress: ip })
  )
}]

// Helper variables for path rules processing (simplified)
var pathMapsProcessed = [for pathMap in urlPathMaps: {
  name: pathMap.name
  defaultBackendPoolName: pathMap.?defaultBackendPoolName ?? ''
  defaultBackendHttpSettingsName: pathMap.?defaultBackendHttpSettingsName ?? ''
  defaultRedirectConfigurationName: pathMap.?defaultRedirectConfigurationName ?? ''
  defaultRewriteRuleSetName: pathMap.?defaultRewriteRuleSetName ?? ''
  pathRules: pathMap.?pathRules ?? []
}]

// Application Gateway Resource
resource appGateway 'Microsoft.Network/applicationGateways@2024-05-01' = if (enableAppGateway) {
  name: appGatewayName
  location: location
  tags: tags
  zones: availabilityZones
  identity: enableSystemManagedIdentity || !empty(userAssignedIdentityIds) ? {
    type: identityType
    userAssignedIdentities: !empty(userAssignedIdentityIds) ? userAssignedIdentityDict : null
  } : null
  properties: {
    sku: {
      name: appGatewaySku
      tier: appGatewayTier
    }
    // Autoscale configuration
    autoscaleConfiguration: {
      minCapacity: capacity.minCapacity
      maxCapacity: capacity.maxCapacity
    }
    // Gateway IP configurations
    gatewayIPConfigurations: [
      {
        name: 'appGatewayIpConfig'
        properties: {
          subnet: {
            id: subnetResourceId
          }
        }
      }
    ]
    // Frontend IP configurations
    frontendIPConfigurations: concat([
      {
        name: 'public-frontend'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: publicIpResourceId
          }
        }
      }
    ], enablePrivateFrontend ? [
      {
        name: 'private-frontend'
        properties: {
          privateIPAddress: privateFrontendIP
          privateIPAllocationMethod: empty(privateFrontendIP) ? 'Dynamic' : 'Static'
          subnet: {
            id: subnetResourceId
          }
        }
      }
    ] : [])
    // Frontend ports
    frontendPorts: [for port in frontendPorts: {
      name: port.name
      properties: {
        port: port.port
      }
    }]
    // SSL certificates
    sslCertificates: [for cert in sslCertificates: {
      name: cert.name
      properties: {
        data: cert.?data
        keyVaultSecretId: cert.?keyVaultSecretId
        password: cert.?password
      }
    }]
    // Trusted root certificates
    trustedRootCertificates: [for cert in trustedRootCertificates: {
      name: cert.name
      properties: {
        data: cert.?data
        keyVaultSecretId: cert.?keyVaultSecretId
      }
    }]
    // Trusted client certificates
    trustedClientCertificates: [for cert in trustedClientCertificates: {
      name: cert.name
      properties: {
        data: cert.data
      }
    }]
    // Authentication certificates
    authenticationCertificates: [for cert in authenticationCertificates: {
      name: cert.name
      properties: {
        data: cert.data
      }
    }]
    // Backend address pools
    backendAddressPools: [for (pool, i) in backendPools: {
      name: pool.name
      properties: {
        backendAddresses: backendAddressesFlattened[i].addresses
      }
    }]    // Backend HTTP settings
    backendHttpSettingsCollection: [for (setting, i) in backendHttpSettings: {
      name: setting.name
      properties: {
        port: setting.port
        protocol: setting.protocol
        cookieBasedAffinity: setting.?cookieBasedAffinity ?? 'Disabled'
        requestTimeout: setting.?requestTimeout ?? 30
        connectionDraining: setting.?connectionDraining ?? {
          enabled: false
          drainTimeoutInSec: 0
        }
        pickHostNameFromBackendAddress: setting.?pickHostNameFromBackendAddress ?? false
        hostName: setting.?hostName ?? ''
        path: setting.?path ?? ''
        probe: !empty(setting.?probeName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/probes', appGatewayName, setting.probeName)        } : null
        trustedRootCertificates: !empty(setting.?trustedRootCertificateNames ?? []) ? map(setting.trustedRootCertificateNames, certName => {
          id: resourceId('Microsoft.Network/applicationGateways/trustedRootCertificates', appGatewayName, certName)
        }) : []
        authenticationCertificates: !empty(setting.?authenticationCertificateNames ?? []) ? map(setting.authenticationCertificateNames, certName => {
          id: resourceId('Microsoft.Network/applicationGateways/authenticationCertificates', appGatewayName, certName)
        }) : []
      }
    }]
    // Health probes
    probes: [for probe in healthProbes: {
      name: probe.name
      properties: {
        protocol: probe.protocol
        host: probe.?host ?? ''
        path: probe.path
        interval: probe.?interval ?? 30
        timeout: probe.?timeout ?? 30
        unhealthyThreshold: probe.?unhealthyThreshold ?? 3
        pickHostNameFromBackendHttpSettings: probe.?pickHostNameFromBackendHttpSettings ?? false
        minServers: probe.?minServers ?? 0
        match: probe.?match ?? {
          statusCodes: ['200-399']
        }
      }
    }]
    // HTTP listeners
    httpListeners: [for listener in httpListeners: {
      name: listener.name
      properties: {
        frontendIPConfiguration: {
          id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', appGatewayName, listener.frontendIPConfigurationName)
        }
        frontendPort: {
          id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', appGatewayName, listener.frontendPortName)
        }
        protocol: listener.protocol
        hostName: listener.?hostName ?? ''
        hostNames: listener.?hostNames ?? []
        requireServerNameIndication: listener.?requireServerNameIndication ?? false
        sslCertificate: !empty(listener.?sslCertificateName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/sslCertificates', appGatewayName, listener.sslCertificateName)
        } : null
        sslProfile: !empty(listener.?sslProfileName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/sslProfiles', appGatewayName, listener.sslProfileName)
        } : null
        firewallPolicy: !empty(listener.?firewallPolicyId ?? '') ? {
          id: listener.firewallPolicyId
        } : (!empty(firewallPolicyId) ? {
          id: firewallPolicyId
        } : null)
        customErrorConfigurations: listener.?customErrorConfigurations ?? []
      }
    }]
    // SSL profiles
    sslProfiles: [for (profile, i) in sslProfiles: {
      name: profile.name
      properties: {
        sslPolicy: profile.?sslPolicy ?? sslPolicy
        clientAuthConfiguration: profile.?clientAuthConfiguration
        trustedClientCertificates: !empty(profile.?trustedClientCertificateNames ?? []) ? map(profile.trustedClientCertificateNames, certName => {
          id: resourceId('Microsoft.Network/applicationGateways/trustedClientCertificates', appGatewayName, certName)
        }) : []
      }
    }]
    // URL path maps
    urlPathMaps: [for (pathMap, i) in urlPathMaps: {
      name: pathMap.name
      properties: {
        defaultBackendAddressPool: !empty(pathMapsProcessed[i].defaultBackendPoolName) ? {
          id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', appGatewayName, pathMapsProcessed[i].defaultBackendPoolName)
        } : null
        defaultBackendHttpSettings: !empty(pathMapsProcessed[i].defaultBackendHttpSettingsName) ? {
          id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', appGatewayName, pathMapsProcessed[i].defaultBackendHttpSettingsName)
        } : null
        defaultRedirectConfiguration: !empty(pathMapsProcessed[i].defaultRedirectConfigurationName) ? {
          id: resourceId('Microsoft.Network/applicationGateways/redirectConfigurations', appGatewayName, pathMapsProcessed[i].defaultRedirectConfigurationName)
        } : null
        defaultRewriteRuleSet: !empty(pathMapsProcessed[i].defaultRewriteRuleSetName) ? {
          id: resourceId('Microsoft.Network/applicationGateways/rewriteRuleSets', appGatewayName, pathMapsProcessed[i].defaultRewriteRuleSetName)
        } : null
        pathRules: pathMapsProcessed[i].pathRules
      }
    }]
    // Request routing rules
    requestRoutingRules: [for rule in requestRoutingRules: {
      name: rule.name
      properties: {
        ruleType: rule.ruleType
        priority: rule.?priority ?? 100
        httpListener: {
          id: resourceId('Microsoft.Network/applicationGateways/httpListeners', appGatewayName, rule.httpListenerName)
        }
        backendAddressPool: rule.ruleType == 'Basic' && !empty(rule.?backendAddressPoolName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', appGatewayName, rule.backendAddressPoolName)
        } : null
        backendHttpSettings: rule.ruleType == 'Basic' && !empty(rule.?backendHttpSettingsName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', appGatewayName, rule.backendHttpSettingsName)
        } : null
        redirectConfiguration: !empty(rule.?redirectConfigurationName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/redirectConfigurations', appGatewayName, rule.redirectConfigurationName)
        } : null
        urlPathMap: rule.ruleType == 'PathBasedRouting' && !empty(rule.?urlPathMapName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/urlPathMaps', appGatewayName, rule.urlPathMapName)
        } : null
        rewriteRuleSet: !empty(rule.?rewriteRuleSetName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/rewriteRuleSets', appGatewayName, rule.rewriteRuleSetName)
        } : null
      }
    }]
    // Redirect configurations
    redirectConfigurations: [for (redirect, i) in redirectConfigurations: {
      name: redirect.name
      properties: {
        redirectType: redirect.redirectType
        targetUrl: redirect.?targetUrl
        targetListener: !empty(redirect.?targetListenerName ?? '') ? {
          id: resourceId('Microsoft.Network/applicationGateways/httpListeners', appGatewayName, redirect.targetListenerName)
        } : null
        includePath: redirect.?includePath ?? true
        includeQueryString: redirect.?includeQueryString ?? true
      }
    }]
    // Rewrite rule sets
    rewriteRuleSets: [for (ruleSet, i) in rewriteRuleSets: {
      name: ruleSet.name
      properties: {
        rewriteRules: ruleSet.rewriteRules
      }
    }]
    // Private link configurations
    privateLinkConfigurations: [for (config, i) in privateLinkConfigurations: {
      name: config.name
      properties: {        ipConfigurations: !empty(config.?ipConfigurations ?? []) ? map(config.ipConfigurations, ipConfig => {
          name: ipConfig.name
          properties: {
            privateIPAddress: ipConfig.privateIPAddress
            privateIPAllocationMethod: ipConfig.privateIPAllocationMethod
            subnet: {
              id: ipConfig.subnetId
            }
            primary: ipConfig.primary
          }
        }) : []
      }
    }]
    // SSL policy
    sslPolicy: sslPolicy
    // Custom error configurations
    customErrorConfigurations: customErrorConfigurations
    // Global configuration
    globalConfiguration: globalConfiguration
    // Web Application Firewall configuration
    webApplicationFirewallConfiguration: appGatewayTier == 'WAF_v2' && !wafConfiguration.enabled ? null : (appGatewayTier == 'WAF_v2' ? {
      enabled: wafConfiguration.enabled
      firewallMode: wafConfiguration.firewallMode
      ruleSetType: wafConfiguration.ruleSetType
      ruleSetVersion: wafConfiguration.ruleSetVersion
      fileUploadLimitInMb: wafConfiguration.?fileUploadLimitInMb ?? 100
      requestBodyCheck: wafConfiguration.?requestBodyCheck ?? true
      maxRequestBodySizeInKb: wafConfiguration.?maxRequestBodySizeInKb ?? 128
      disabledRuleGroups: wafConfiguration.?disabledRuleGroups ?? []
      exclusions: wafConfiguration.?exclusions ?? []
    } : null)
    // Firewall policy
    firewallPolicy: !empty(firewallPolicyId) ? {
      id: firewallPolicyId
    } : null
    forceFirewallPolicyAssociation: forceFirewallPolicyAssociation
    // Additional settings
    enableHttp2: enableHttp2
    enableFips: enableFips
  }
}

// Outputs
@description('Application Gateway resource ID')
output appGatewayId string = enableAppGateway ? appGateway.id : ''

@description('Application Gateway name')
output appGatewayName string = enableAppGateway ? appGateway.name : ''

@description('Application Gateway FQDN - not available at deployment time')
output appGatewayFqdn string = ''

@description('Application Gateway public IP address - not available at deployment time')
output appGatewayPublicIpAddress string = ''

@description('Application Gateway backend pool names')
output backendPoolNames array = enableAppGateway ? map(backendPools, pool => pool.name) : []

@description('Application Gateway frontend IP configurations - available after deployment')
output frontendIPConfigurations array = []

@description('Application Gateway listener names')
output listenerNames array = enableAppGateway ? map(httpListeners, listener => listener.name) : []

@description('Application Gateway routing rule names')
output routingRuleNames array = enableAppGateway ? map(requestRoutingRules, rule => rule.name) : []

@description('Application Gateway operational state')
output operationalState string = enableAppGateway ? appGateway.properties.?operationalState ?? 'Unknown' : 'Disabled'

@description('Application Gateway system assigned managed identity principal ID')
output systemAssignedIdentityPrincipalId string = enableAppGateway && enableSystemManagedIdentity ? appGateway.identity.?principalId ?? '' : ''

@description('Application Gateway configuration summary')
output configurationSummary object = enableAppGateway ? {
  sku: {
    name: appGateway.properties.sku.name
    tier: appGateway.properties.sku.tier
  }
  capacity: {
    min: appGateway.properties.?autoscaleConfiguration.?minCapacity ?? 0
    max: appGateway.properties.?autoscaleConfiguration.?maxCapacity ?? 0
  }
  wafEnabled: appGateway.properties.?webApplicationFirewallConfiguration.?enabled ?? false
  http2Enabled: appGateway.properties.?enableHttp2 ?? false
  backendPoolCount: length(appGateway.properties.backendAddressPools)
  listenerCount: length(appGateway.properties.httpListeners)
  routingRuleCount: length(appGateway.properties.requestRoutingRules)
} : {}
