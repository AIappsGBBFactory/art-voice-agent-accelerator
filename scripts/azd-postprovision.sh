#!/bin/bash
# filepath: /Users/jinle/Repos/_AIProjects/gbb-ai-audio-agent/scripts/azd-postprovision.sh

# Exit immediately if a command exits with a non-zero status
set -e

# ========================================================================
# 🎯 Azure Developer CLI Post-Provisioning Script
# ========================================================================
echo "🚀 Starting Post-Provisioning Script"
echo "===================================="
echo ""

# Load environment variables from .env file
echo "🔍 Checking ACS_SOURCE_PHONE_NUMBER..."
EXISTING_ACS_PHONE_NUMBER="$(azd env get-value ACS_SOURCE_PHONE_NUMBER 2>/dev/null || echo "")"

if [ -n "$EXISTING_ACS_PHONE_NUMBER" ] && [ "$EXISTING_ACS_PHONE_NUMBER" != "null" ]; then
    if [[ "$EXISTING_ACS_PHONE_NUMBER" =~ ^\+[0-9]+$ ]]; then
        echo "✅ ACS_SOURCE_PHONE_NUMBER already exists: $EXISTING_ACS_PHONE_NUMBER"
        echo "⏩ Skipping phone number creation."
    else
        echo "⚠️ ACS_SOURCE_PHONE_NUMBER exists but is not a valid phone number format: $EXISTING_ACS_PHONE_NUMBER"
        echo "🔄 Proceeding with phone number creation..."
    fi
else
    echo "🔄 Creating a new ACS phone number..."
    {
        # Ensure Azure CLI communication extension is installed
        echo "🔧 Checking Azure CLI communication extension..."
        if ! az extension list --query "[?name=='communication']" -o tsv | grep -q communication; then
            echo "➕ Adding Azure CLI communication extension..."
            az extension add --name communication
        else
            echo "✅ Azure CLI communication extension is already installed."
        fi

        # Retrieve ACS endpoint
        echo "🔍 Retrieving ACS_ENDPOINT from environment..."
        ACS_ENDPOINT="$(azd env get-value ACS_ENDPOINT)"
        if [ -z "$ACS_ENDPOINT" ]; then
            echo "❌ Error: ACS_ENDPOINT is not set in the environment."
            exit 1
        fi

        # Install required Python packages
        echo "📦 Installing required Python packages for ACS phone number management..."
        pip3 install azure-identity azure-communication-phonenumbers

        # Run the Python script to create a new phone number
        echo "📞 Creating a new ACS phone number..."
        PHONE_NUMBER=$(python3 scripts/acs_phone_number_manager.py --endpoint "$ACS_ENDPOINT" purchase || echo "")
        if [ -z "$PHONE_NUMBER" ]; then
            echo "❌ Error: Failed to create ACS phone number."
            exit 1
        fi

        echo "✅ Successfully created ACS phone number: $PHONE_NUMBER"

        # Set the ACS_SOURCE_PHONE_NUMBER in azd environment
        # Extract just the phone number from the output
        CLEAN_PHONE_NUMBER=$(echo "$PHONE_NUMBER" | grep -o '+[0-9]\+' | head -1)
        azd env set ACS_SOURCE_PHONE_NUMBER "$CLEAN_PHONE_NUMBER"
        echo "🔄 Updated ACS_SOURCE_PHONE_NUMBER in .env file."
        # Update the backend container app environment variable
        echo "🔄 Updating backend container app environment variable..."
        BACKEND_CONTAINER_APP_NAME="$(azd env get-value BACKEND_CONTAINER_APP_NAME)"
        BACKEND_RESOURCE_GROUP_NAME="$(azd env get-value BACKEND_RESOURCE_GROUP_NAME)"

        if [ -n "$BACKEND_CONTAINER_APP_NAME" ] && [ -n "$BACKEND_RESOURCE_GROUP_NAME" ]; then
            echo "📱 Updating ACS_SOURCE_PHONE_NUMBER in container app: $BACKEND_CONTAINER_APP_NAME"
            az containerapp update \
                --name "$BACKEND_CONTAINER_APP_NAME" \
                --resource-group "$BACKEND_RESOURCE_GROUP_NAME" \
                --set-env-vars "ACS_SOURCE_PHONE_NUMBER=$CLEAN_PHONE_NUMBER" \
                --output none
            echo "✅ Successfully updated container app environment variable."
        else
            echo "⚠️ Warning: Could not update container app - missing BACKEND_CONTAINER_APP_NAME or BACKEND_RESOURCE_GROUP_NAME"
        fi
    } || {
        echo "⚠️ Warning: ACS phone number creation failed, but continuing with the rest of the script..."
    }
fi

# # ========================================================================
# # 🔐 Azure Entra Group Configuration
# # ========================================================================
# echo ""
# echo "👥 Configuring Azure Entra Group Membership"
# echo "==========================================="
# echo ""

# # Retrieve required values from azd environment
# BACKEND_UAI_PRINCIPAL_ID="$(azd env get-value BACKEND_UAI_PRINCIPAL_ID)"
# AZURE_ENTRA_GROUP_ID="$(azd env get-value AZURE_ENTRA_GROUP_ID)"

# if [ -z "$BACKEND_UAI_PRINCIPAL_ID" ]; then
#     echo "❌ Error: BACKEND_UAI_PRINCIPAL_ID is not set in the environment."
#     exit 1
# fi

# if [ -z "$AZURE_ENTRA_GROUP_ID" ]; then
#     echo "❌ Error: AZURE_ENTRA_GROUP_ID is not set in the environment."
#     exit 1
# fi

# # Check if the member is already in the group
# echo "🔍 Checking if BACKEND_UAI_PRINCIPAL_ID is already a member of the Azure Entra group..."
# EXISTING_MEMBER=$(az rest --method get --url "https://graph.microsoft.com/v1.0/groups/$AZURE_ENTRA_GROUP_ID/members/microsoft.graph.servicePrincipal" --query "value[?id=='$BACKEND_UAI_PRINCIPAL_ID'].id" -o tsv)

# if [ -n "$EXISTING_MEMBER" ]; then
#     echo "✅ BACKEND_UAI_PRINCIPAL_ID ($BACKEND_UAI_PRINCIPAL_ID) is already a member of the Azure Entra group."
# else
#     echo "➕ Adding BACKEND_UAI_PRINCIPAL_ID to Azure Entra group..."
#     if az ad group member add --group "$AZURE_ENTRA_GROUP_ID" --member-id "$BACKEND_UAI_PRINCIPAL_ID" 2>/dev/null; then
#         echo "✅ Successfully added BACKEND_UAI_PRINCIPAL_ID to Azure Entra group."
#     else
#         echo "❌ Error: Failed to add BACKEND_UAI_PRINCIPAL_ID to Azure Entra group."
#         exit 1
#     fi
# fi

# # ========================================================================
# # 🌐 Application Gateway DNS Configuration Info
# # ========================================================================
# echo ""
# echo "🔗 Application Gateway DNS Configuration"
# echo "======================================="
# echo ""

# # Retrieve Application Gateway public IP and domain information
# APP_GATEWAY_PUBLIC_IP="$(azd env get-value APPLICATION_GATEWAY_PUBLIC_IP 2>/dev/null || echo "")"
# APP_GATEWAY_FQDN="$(azd env get-value APPLICATION_GATEWAY_FQDN 2>/dev/null || echo "")"
# CUSTOM_DOMAIN="$(azd env get-value AZURE_DOMAIN_FQDN 2>/dev/null || echo "")"

# if [ -n "$APP_GATEWAY_PUBLIC_IP" ] && [ "$APP_GATEWAY_PUBLIC_IP" != "null" ]; then
#     echo "📋 DNS Record Configuration Required:"
#     echo "======================================"
#     echo ""
#     echo "🔧 Please configure the following DNS record in your DNS provider:"
#     echo ""
#     echo "   Record Type: A"
#     echo "   Name:        ${CUSTOM_DOMAIN:-yourdomain.com}"
#     echo "   Value:       $APP_GATEWAY_PUBLIC_IP"
#     echo "   TTL:         300 (or your preferred value)"
#     echo ""
    
#     if [ -n "$APP_GATEWAY_FQDN" ] && [ "$APP_GATEWAY_FQDN" != "null" ]; then
#     echo "   Alternative CNAME Record:"
#     echo "   Record Type: CNAME"
#     echo "   Name:        ${CUSTOM_DOMAIN:-yourdomain.com}"
#     echo "   Value:       $APP_GATEWAY_FQDN"
#     echo "   TTL:         300 (or your preferred value)"
#     echo ""
#     fi
    
#     echo "⚠️  Important Notes:"
#     echo "   • DNS propagation may take up to 48 hours"
#     echo "   • Verify the record using: nslookup ${CUSTOM_DOMAIN:-yourdomain.com}"
#     echo "   • SSL certificate will be auto-provisioned after DNS propagation"
#     echo ""
# else
#     echo "⚠️ Warning: APP_GATEWAY_PUBLIC_IP not found in environment variables."
#     echo "   Please check your Application Gateway deployment."
# fi


