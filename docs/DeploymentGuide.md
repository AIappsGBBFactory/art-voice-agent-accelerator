
# Deployment Guide

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli) installed and authenticated
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) installed
- Node.js 18+ and Python 3.11+
- An Azure subscription with appropriate permissions
- **A publicly trusted SSL certificate** for your domain (required for Azure Communication Services WebSocket connections)

## Quick Start

1. **Clone and Initialize**
    ```bash
    git clone <repository-url>
    cd gbb-ai-audio-agent
    azd auth login
    azd init
    ```

2. **Set Environment Variables**
    ```bash
    azd env new <environment-name>
    azd env set LOCATION "East US"
    azd env set ENVIRONMENT_NAME "<environment-name>"
    ```

3. **Deploy Infrastructure and Code**
    ```bash
    azd up
    ```

## Detailed Deployment Steps

### 1. SSL Certificate Requirements

**Important**: Azure Communication Services requires a publicly trusted SSL certificate for WebSocket connections. You must bring your own certificate and store it in Key Vault before deployment.

#### Certificate Preparation

1. **Obtain a Publicly Trusted Certificate**
   - Purchase from a certificate authority (CA) like DigiCert, Let's Encrypt, or your preferred provider
   - Ensure the certificate covers your intended domain (e.g., `voice-agent.yourdomain.com`)
   - The certificate must be in PFX format with a password

2. **Store Certificate in Key Vault**
   ```bash
   # Import certificate to Key Vault (this will be created during deployment)
   az keyvault certificate import \
     --vault-name kv-voice-agent-prod \
     --name ssl-certificate \
     --file /path/to/your/certificate.pfx \
     --password "your-certificate-password"
   
   # Set the certificate password as a secret
   az keyvault secret set \
     --vault-name kv-voice-agent-prod \
     --name ssl-certificate-password \
     --value "your-certificate-password"
    
   azd env set AZURE_SSL_KEY_VAULT_SECRET_ID https://kv-voice-agent-prod.vault.azure.net/secrets/ssl-certificate
   ```

3. **Configure User-Assigned Managed Identity for Certificate Access**

    Before deployment, you need to create a user-assigned managed identity and grant it appropriate permissions to retrieve the certificate from Key Vault.

    ```bash
    # Create user-assigned managed identity
    az identity create \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod

    # Get the principal ID of the managed identity
    IDENTITY_PRINCIPAL_ID=$(az identity show \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod \
        --query principalId -o tsv)

    # Grant the managed identity certificate permissions on Key Vault
    az keyvault set-policy \
        --name kv-voice-agent-prod \
        --object-id $IDENTITY_PRINCIPAL_ID \
        --certificate-permissions get list \
        --secret-permissions get list

    # Set the identity resource ID for deployment
    IDENTITY_RESOURCE_ID=$(az identity show \
        --name id-voice-agent-cert \
        --resource-group rg-voice-agent-prod \
        --query id -o tsv)

    azd env set AZURE_KEY_VAULT_SECRET_USER_IDENTITY $IDENTITY_RESOURCE_ID
    ```

    **Note**: This managed identity will be assigned to the Application Gateway to retrieve the SSL certificate from Key Vault during deployment and runtime operations.

### 2. Environment Configuration

Configure your deployment environment:

```bash
# Create a new environment
azd env new production

# Set required parameters
azd env set LOCATION "East US"
azd env set RESOURCE_GROUP_NAME "rg-voice-agent-prod"
azd env set PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
azd env set CUSTOM_DOMAIN "voice-agent.yourdomain.com"
```

### 3. Infrastructure Provisioning

Deploy Azure resources using Bicep templates:

```bash
# Deploy infrastructure only
azd provision

# Deploy the code to already deployed infra
azd deploy

# Or deploy everything (infrastructure + code)
azd up
```
For a detailed overview of the infrastructure components, provisioning details, and manual setup requirements, refer to the [Infrastructure README](../infra/README.md).

This will create:
- Azure Container Apps Environment
- Azure OpenAI Service
- Azure Communication Services
- Redis Cache
- Key Vault
- Application Gateway (configured to use your certificate from Key Vault)
- Storage Account
- Cosmos DB
- Private endpoints and networking

### 4. Application Deployment

Deploy the application code:

```bash
# Deploy code to existing infrastructure
azd deploy
```

### 5. SSL Certificate and DNS Configuration

**Important**: After provisioning and importing your certificate, update your DNS records.

1. **Get Application Gateway Public IP**
    ```bash
    # Find your Application Gateway public IP
    az network public-ip show \
      --resource-group rg-voice-agent-prod \
      --name pip-appgw-voice-agent \
      --query ipAddress -o tsv
    ```

2. **Update DNS Records**
    - Go to your domain registrar or DNS provider
    - Create/update an A record pointing your domain to the Application Gateway's public IP
    - Example: `voice-agent.yourdomain.com` → `20.xx.xx.xx`

3. **Import Certificate (if not done during step 1)**
    ```bash
    # Import your certificate after Key Vault is created
    az keyvault certificate import \
      --vault-name kv-voice-agent-prod \
      --name ssl-certificate \
      --file /path/to/your/certificate.pfx \
      --password "your-certificate-password"
    
    # Update Application Gateway to use the certificate
    azd deploy
    ```

4. **Verify SSL Certificate**
    After DNS propagation (5-30 minutes), verify your SSL certificate is working:
    
    ```bash
    # Basic health check
    curl -I https://voice-agent.yourdomain.com/health
    
    # Check SSL certificate details
    openssl s_client -connect voice-agent.yourdomain.com:443 -servername voice-agent.yourdomain.com | openssl x509 -noout -subject -ext subjectAltName
    
    # Verify certificate chain and expiration
    openssl s_client -connect voice-agent.yourdomain.com:443 -servername voice-agent.yourdomain.com -showcerts </dev/null 2>/dev/null | openssl x509 -noout -dates
    
    # Test SSL configuration (optional - requires ssllabs-scan tool)
    # curl -s "https://api.ssllabs.com/api/v3/analyze?host=voice-agent.yourdomain.com&publish=off"
    ```
    
    Expected output should show:
    - Valid certificate subject matching your domain
    - Subject Alternative Names (SAN) including your domain
    - Certificate validity dates showing future expiration

### 6. WebSocket Connectivity Testing

Test WebSocket functionality using `wscat`:

```bash
# Install wscat if not already installed
npm install -g wscat

# Test WebSocket connection to your deployed backend
wscat -c wss://voice-agent.yourdomain.com/ws

# Or test against local development server
wscat -c ws://localhost:8000/ws
```

**Expected behavior:**
- Connection should establish successfully
- You should see a connection confirmation message
- Type messages to test bidirectional communication
- Use `Ctrl+C` to disconnect

**Troubleshooting WebSocket issues:**
- Check backend container logs for WebSocket errors
- Test local backend first to isolate networking issues
- Ensure your SSL certificate is properly configured (ACS requires trusted certificates)

## Environment Management

### Switch Between Environments

```bash
# List environments
azd env list

# Switch to different environment
azd env select <environment-name>

# View current environment variables
azd env get-values
```

### Update Configurations

```bash
# See all environment variables
azd env get-values

# Set new environment variable
azd env set AZURE_DOMAIN_FQDN <your-domain-name>

# Apply changes
azd deploy
```

### Certificate Management

**Updating SSL Certificates:**

```bash
# Import new certificate to Key Vault
az keyvault certificate import \
  --vault-name kv-voice-agent-prod \
  --name ssl-certificate \
  --file /path/to/new/certificate.pfx \
  --password "new-certificate-password"

# Update the password secret
az keyvault secret set \
  --vault-name kv-voice-agent-prod \
  --name ssl-certificate-password \
  --value "new-certificate-password"

# Redeploy to apply certificate changes
azd deploy
```

## Monitoring and Troubleshooting

### View Deployment Logs

```bash
# View deployment status
azd show

# View container app logs
az containerapp logs show \
  --name ca-voice-agent-backend \
  --resource-group rg-voice-agent-prod \
  --follow
```

### Common Issues

1. **SSL Certificate Not Working**
    - Verify DNS A record points to Application Gateway IP
    - Wait for DNS propagation (up to 30 minutes)
    - Check certificate provisioning in Azure portal
    - Ensure certificate is properly imported to Key Vault

2. **ACS WebSocket Connection Fails**
    - Verify you're using a publicly trusted SSL certificate (self-signed certificates will not work)
    - Check that the certificate covers your domain
    - Test SSL configuration with browser or OpenSSL

3. **Container App Not Starting**
    - Check environment variables in Key Vault
    - Verify managed identity permissions
    - Review container app logs

4. **Redis Connection Issues**
    - Ensure private endpoint connectivity
    - Verify Redis access keys in Key Vault

## Cleanup

To remove all resources:

```bash
# Delete all resources
azd down

# Delete specific environment
azd env delete <environment-name>
```

## Advanced Configuration

### Scaling Configuration

Update container app scaling in `infra/modules/containerapp.bicep`:

```bicep
scale: {
  minReplicas: 1
  maxReplicas: 10
  rules: [
     {
        name: 'http-scaling'
        http: {
          metadata: {
             concurrentRequests: '100'
          }
        }
     }
  ]
}
```

## Support

For deployment issues:
1. Check Azure portal for resource status
2. Review container app logs
3. Verify network connectivity and DNS settings
4. Ensure all required permissions are granted
5. Verify SSL certificate is properly configured and trusted

