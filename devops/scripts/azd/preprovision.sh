#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 <provider>"
    echo "  provider: bicep or terraform"
    exit 1
}

# Check if argument is provided
if [ $# -ne 1 ]; then
    echo "Error: Provider argument is required"
    usage
fi

PROVIDER="$1"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Validate the provider argument
case "$PROVIDER" in
    "bicep")
        echo "Bicep deployment detected"
        # Call ssl-preprovision.sh from helpers directory
        SSL_PREPROVISION_SCRIPT="$SCRIPT_DIR/helpers/ssl-preprovision.sh"
        if [ -f "$SSL_PREPROVISION_SCRIPT" ]; then
            echo "Running SSL pre-provisioning setup..."
            bash "$SSL_PREPROVISION_SCRIPT"
        else
            echo "Error: ssl-preprovision.sh not found at $SSL_PREPROVISION_SCRIPT"
            exit 1
        fi
        ;;
    "terraform")
        echo "Terraform deployment detected"
        echo "Running Terraform Remote State initialization..."
        
        # Call tf-init.sh from helpers directory
        TF_INIT_SCRIPT="$SCRIPT_DIR/helpers/tf-init.sh"
        if [ -f "$TF_INIT_SCRIPT" ]; then
            bash "$TF_INIT_SCRIPT"
        else
            echo "Warning: tf-init.sh not found at $TF_INIT_SCRIPT"
        fi
        
        # Set terraform variables through environment exports and tfvars file
        echo "Setting Terraform variables from Azure environment..."
        export TF_VAR_environment_name="$AZURE_ENV_NAME"
        export TF_VAR_location="$AZURE_LOCATION"

        # Validate required variables
        if [ -z "$AZURE_ENV_NAME" ]; then
            echo "Error: AZURE_ENV_NAME environment variable is not set"
            exit 1
        fi

        if [ -z "$AZURE_LOCATION" ]; then
            echo "Error: AZURE_LOCATION environment variable is not set"
            exit 1
        fi
        # Get optional ACS phone number from AZD environment and cleanse error output
        ACS_SOURCE_PHONE_NUMBER_RAW=$(azd env get-value ACS_SOURCE_PHONE_NUMBER 2>&1)
        if [[ "$ACS_SOURCE_PHONE_NUMBER_RAW" == *"not found"* || "$ACS_SOURCE_PHONE_NUMBER_RAW" == *"No value"* ]]; then
            ACS_SOURCE_PHONE_NUMBER=""
        else
            ACS_SOURCE_PHONE_NUMBER="$ACS_SOURCE_PHONE_NUMBER_RAW"
        fi
        # Generate tfvars.json
        TFVARS_FILE="./infra-tf/main.tfvars.json"
        echo "Generating $TFVARS_FILE..."
        
        # Build JSON content dynamically
        JSON_CONTENT="{
  \"environment_name\": \"$AZURE_ENV_NAME\",
  \"location\": \"$AZURE_LOCATION\""
        
        if [ -n "$ACS_SOURCE_PHONE_NUMBER" ]; then
            JSON_CONTENT="$JSON_CONTENT,
  \"acs_source_phone_number\": \"$ACS_SOURCE_PHONE_NUMBER\""
        fi
        
        JSON_CONTENT="$JSON_CONTENT
}"
        
        # Write to file
        echo "$JSON_CONTENT" > "$TFVARS_FILE"

        # Display configuration summary
        echo ""
        echo "✅ Terraform variables configured:"
        echo "   Environment: $AZURE_ENV_NAME"
        echo "   Location: $AZURE_LOCATION"
        if [ -n "$ACS_SOURCE_PHONE_NUMBER" ]; then
            echo "   ACS Phone: $ACS_SOURCE_PHONE_NUMBER"
        else
            echo "   ACS Phone: null (not set)"
        fi
        echo "   Config file: $TFVARS_FILE"
        ;;
    *)
        echo "Error: Invalid provider '$PROVIDER'. Must be 'bicep' or 'terraform'"
        usage
        ;;
esac