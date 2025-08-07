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
SKIP_PHONE_CREATION=True
if [ -n "$EXISTING_ACS_PHONE_NUMBER" ] && [ "$EXISTING_ACS_PHONE_NUMBER" != "null" ]; then
    if [[ "$EXISTING_ACS_PHONE_NUMBER" =~ ^\+[0-9]+$ ]]; then
        echo "✅ ACS_SOURCE_PHONE_NUMBER already exists: $EXISTING_ACS_PHONE_NUMBER"
        echo "⏩ Skipping phone number creation."
        SKIP_PHONE_CREATION=true
    else
        echo "⚠️ ACS_SOURCE_PHONE_NUMBER exists but is not a valid phone number format: $EXISTING_ACS_PHONE_NUMBER"
        echo "🔄 Proceeding with phone number creation..."
        SKIP_PHONE_CREATION=false
    fi
fi

if [ "$SKIP_PHONE_CREATION" == false ]; then
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
        PHONE_NUMBER=$(python3 scripts/azd/helpers/acs_phone_number_manager.py --endpoint "$ACS_ENDPOINT" purchase)
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
        
        # Update the generated environment file with the new phone number
        sed -i.bak "s/^ACS_SOURCE_PHONE_NUMBER=.*/ACS_SOURCE_PHONE_NUMBER=$CLEAN_PHONE_NUMBER/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
        echo "🔄 Updated ACS_SOURCE_PHONE_NUMBER in $ENV_FILE."
        
        # Update the backend container app or app service environment variable
        echo "🔄 Updating backend environment variable..."
        BACKEND_CONTAINER_APP_NAME="$(azd env get-value BACKEND_CONTAINER_APP_NAME 2>/dev/null || echo "")"
        BACKEND_APP_SERVICE_NAME="$(azd env get-value BACKEND_APP_SERVICE_NAME 2>/dev/null || echo "")"
        BACKEND_RESOURCE_GROUP_NAME="$(azd env get-value AZURE_RESOURCE_GROUP)"

        if [ -n "$BACKEND_CONTAINER_APP_NAME" ] && [ -n "$BACKEND_RESOURCE_GROUP_NAME" ]; then
            echo "📱 Updating ACS_SOURCE_PHONE_NUMBER in container app: $BACKEND_CONTAINER_APP_NAME"
            az containerapp update \
                --name "$BACKEND_CONTAINER_APP_NAME" \
                --resource-group "$BACKEND_RESOURCE_GROUP_NAME" \
                --set-env-vars "ACS_SOURCE_PHONE_NUMBER=$CLEAN_PHONE_NUMBER" \
                --output none
            echo "✅ Successfully updated container app environment variable."
        elif [ -n "$BACKEND_APP_SERVICE_NAME" ] && [ -n "$BACKEND_RESOURCE_GROUP_NAME" ]; then
            echo "🌐 Updating ACS_SOURCE_PHONE_NUMBER in app service: $BACKEND_APP_SERVICE_NAME"
            az webapp config appsettings set \
                --name "$BACKEND_APP_SERVICE_NAME" \
                --resource-group "$BACKEND_RESOURCE_GROUP_NAME" \
                --settings "ACS_SOURCE_PHONE_NUMBER=$CLEAN_PHONE_NUMBER" \
                --output none
            echo "✅ Successfully updated app service environment variable."
        else
            echo "⚠️ Warning: Could not update backend service - missing container app or app service name, or AZURE_RESOURCE_GROUP"
        fi
    } || {
        echo "⚠️ Warning: ACS phone number creation failed, but continuing with the rest of the script..."
    }
fi


# ========================================================================
# 📄 Environment File Generation
# ========================================================================
echo ""
echo "📄 Generating Environment Configuration Files"
echo "============================================="
echo ""

# Get the azd environment name
AZD_ENV_NAME="$(azd env get-value AZURE_ENV_NAME 2>/dev/null || echo "dev")"
ENV_FILE=".env.${AZD_ENV_NAME}"

# Get the script directory to locate helper scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATE_ENV_SCRIPT="$SCRIPT_DIR/helpers/generate-env.sh"

echo "📝 Running: $GENERATE_ENV_SCRIPT $AZD_ENV_NAME $ENV_FILE"

# Run the modular environment generation script
if "$GENERATE_ENV_SCRIPT" "$AZD_ENV_NAME" "$ENV_FILE"; then
    echo "✅ Environment file generation completed successfully"
else
    echo "❌ Environment file generation failed"
    exit 1
fi

echo "📋 Environment file contains $(grep -c '^[A-Z]' "$ENV_FILE") configuration variables"
echo ""

echo ""
echo "🎯 Post-Provisioning Complete"
echo "============================"
echo ""
echo "📋 Generated Files:"
echo "  - ${ENV_FILE} (Backend environment configuration)"
echo ""
echo "🔧 Next Steps:"
echo "  - Review the generated environment file: cat ${ENV_FILE}"
echo "  - Source the environment file: source ${ENV_FILE}"
echo "  - Test your application with the new configuration"
echo ""
