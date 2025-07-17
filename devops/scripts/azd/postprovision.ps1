#!/usr/bin/env pwsh
#requires -version 7.0

# ========================================================================
# 🎯 Azure Developer CLI Post-Provisioning Script (PowerShell)
# ========================================================================
Write-Host "🚀 Starting Post-Provisioning Script" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Function to safely get azd environment value
function Get-AzdEnvValue {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        
        [string]$Default = ""
    )
    
    try {
        # Capture both stdout and stderr, then check exit code
        $output = & azd env get-value $Name 2>&1
        
        # Check if the command succeeded (exit code 0)
        if ($LASTEXITCODE -eq 0) {
            # Convert output to string and trim whitespace
            $value = $output | Out-String | ForEach-Object { $_.Trim() }
            
            # Return the value if it's not empty, null, or an error message
            if ($value -and 
                $value -ne 'null' -and 
                $value -ne '' -and
                -not $value.StartsWith('ERROR') -and
                -not $value.Contains('not found')) {
                return $value
            }
        }
        
        # Return default if command failed or value is invalid
        return $Default
    }
    catch {
        # Return default on any exception
        return $Default
    }
}

# Check ACS_SOURCE_PHONE_NUMBER
Write-Host "🔍 Checking ACS_SOURCE_PHONE_NUMBER..." -ForegroundColor Yellow
$ExistingAcsPhoneNumber = Get-AzdEnvValue -Name "ACS_SOURCE_PHONE_NUMBER"
$SkipPhoneCreation = $false

# Debug output
Write-Host "Debug: Retrieved ACS_SOURCE_PHONE_NUMBER: '$ExistingAcsPhoneNumber'" -ForegroundColor Gray

if ($ExistingAcsPhoneNumber -and $ExistingAcsPhoneNumber -ne "null" -and $ExistingAcsPhoneNumber -match '^\+[0-9]+$') {
    Write-Host "✅ ACS_SOURCE_PHONE_NUMBER already exists: $ExistingAcsPhoneNumber" -ForegroundColor Green
    Write-Host "⏩ Skipping phone number creation." -ForegroundColor Yellow
    $SkipPhoneCreation = $true
}
elseif ($ExistingAcsPhoneNumber -and $ExistingAcsPhoneNumber -ne "null") {
    Write-Host "⚠️ ACS_SOURCE_PHONE_NUMBER exists but is not a valid phone number format: $ExistingAcsPhoneNumber" -ForegroundColor Yellow
    Write-Host "🔄 Proceeding with phone number creation..." -ForegroundColor Yellow
    $SkipPhoneCreation = $false
}

if (-not $SkipPhoneCreation) {
    Write-Host "🔄 Creating a new ACS phone number..." -ForegroundColor Yellow
    
    try {
        # Ensure Azure CLI communication extension is installed
        Write-Host "🔧 Checking Azure CLI communication extension..." -ForegroundColor Cyan
        $CommExtension = az extension list --query "[?name=='communication']" -o tsv | Where-Object { $_ -like "*communication*" }
        
        if (-not $CommExtension) {
            Write-Host "➕ Adding Azure CLI communication extension..." -ForegroundColor Yellow
            az extension add --name communication
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install Azure CLI communication extension"
            }
        }
        else {
            Write-Host "✅ Azure CLI communication extension is already installed." -ForegroundColor Green
        }

        # Retrieve ACS endpoint
        Write-Host "🔍 Retrieving ACS_ENDPOINT from environment..." -ForegroundColor Cyan
        $AcsEndpoint = Get-AzdEnvValue -Name "ACS_ENDPOINT"
        if (-not $AcsEndpoint) {
            throw "ACS_ENDPOINT is not set in the environment"
        }

        # Install required Python packages
        Write-Host "📦 Installing required Python packages for ACS phone number management..." -ForegroundColor Cyan
        pip3 install azure-identity azure-communication-phonenumbers
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install required Python packages"
        }

        # Run the Python script to create a new phone number
        Write-Host "📞 Creating a new ACS phone number..." -ForegroundColor Cyan
        $PhoneNumber = python3 scripts/azd/helpers/acs_phone_number_manager.py --endpoint $AcsEndpoint purchase
        if ($LASTEXITCODE -ne 0 -or -not $PhoneNumber) {
            throw "Failed to create ACS phone number"
        }

        Write-Host "✅ Successfully created ACS phone number: $PhoneNumber" -ForegroundColor Green

        # Extract clean phone number
        $CleanPhoneNumber = [regex]::Match($PhoneNumber, '\+[0-9]+').Value
        if (-not $CleanPhoneNumber) {
            $CleanPhoneNumber = $PhoneNumber
        }

        # Set the ACS_SOURCE_PHONE_NUMBER in azd environment
        azd env set ACS_SOURCE_PHONE_NUMBER $CleanPhoneNumber
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set ACS_SOURCE_PHONE_NUMBER in azd environment"
        }
        Write-Host "🔄 Updated ACS_SOURCE_PHONE_NUMBER in .env file." -ForegroundColor Green
        
        # Update the backend container app or app service environment variable
        Write-Host "🔄 Updating backend environment variable..." -ForegroundColor Cyan
        $BackendContainerAppName = Get-AzdEnvValue -Name "BACKEND_CONTAINER_APP_NAME"
        $BackendAppServiceName = Get-AzdEnvValue -Name "BACKEND_APP_SERVICE_NAME"
        $BackendResourceGroupName = Get-AzdEnvValue -Name "AZURE_RESOURCE_GROUP"

        if ($BackendContainerAppName -and $BackendResourceGroupName) {
            Write-Host "📱 Updating ACS_SOURCE_PHONE_NUMBER in container app: $BackendContainerAppName" -ForegroundColor Cyan
            az containerapp update `
                --name $BackendContainerAppName `
                --resource-group $BackendResourceGroupName `
                --set-env-vars "ACS_SOURCE_PHONE_NUMBER=$CleanPhoneNumber" `
                --output none
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Successfully updated container app environment variable." -ForegroundColor Green
            }
        }
        if ($BackendAppServiceName -and $BackendResourceGroupName) {
            Write-Host "🌐 Updating ACS_SOURCE_PHONE_NUMBER in app service: $BackendAppServiceName" -ForegroundColor Cyan
            az webapp config appsettings set `
                --name $BackendAppServiceName `
                --resource-group $BackendResourceGroupName `
                --settings "ACS_SOURCE_PHONE_NUMBER=$CleanPhoneNumber" `
                --output none
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Successfully updated app service environment variable." -ForegroundColor Green
            }
        }

    }
    catch {
        Write-Host "⚠️ Warning: ACS phone number creation failed, but continuing with the rest of the script..." -ForegroundColor Yellow
        Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ========================================================================
# 📄 Environment File Generation
# ========================================================================
Write-Host ""
Write-Host "📄 Generating Environment Configuration Files" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Get the azd environment name
$AzdEnvName = Get-AzdEnvValue -Name "AZURE_ENV_NAME" -Default "dev"
$EnvFile = ".env.$AzdEnvName"

# Debug output
Write-Host "Debug: Using environment name: '$AzdEnvName'" -ForegroundColor Gray
Write-Host "Debug: Environment file will be: '$EnvFile'" -ForegroundColor Gray

# Get the script directory to locate helper scripts
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$GenerateEnvScript = Join-Path $ScriptDir "helpers/generate-env.ps1"

Write-Host "📝 Running: $GenerateEnvScript $AzdEnvName $EnvFile" -ForegroundColor Cyan

# Run the modular environment generation script
try {
    if (Test-Path $GenerateEnvScript) {
        & $GenerateEnvScript $AzdEnvName $EnvFile
        if ($LASTEXITCODE -ne 0) {
            throw "Environment file generation failed"
        }
        Write-Host "✅ Environment file generation completed successfully" -ForegroundColor Green
    }
    else {
        Write-Warning "generate-env.ps1 not found at $GenerateEnvScript"
        # Fallback to shell script
        $GenerateEnvShellScript = Join-Path $ScriptDir "helpers/generate-env.sh"
        if (Test-Path $GenerateEnvShellScript) {
            Write-Host "Using shell script fallback..." -ForegroundColor Yellow
            & bash $GenerateEnvShellScript $AzdEnvName $EnvFile
            if ($LASTEXITCODE -ne 0) {
                throw "Environment file generation failed"
            }
            Write-Host "✅ Environment file generation completed successfully" -ForegroundColor Green
        }
        else {
            throw "No environment generation script found"
        }
    }
    exit 0
}
catch {
    Write-Error "❌ Environment file generation failed: $($_.Exception.Message)"
    exit 1
}

# Count configuration variables
if (Test-Path $EnvFile) {
    $ConfigCount = (Get-Content $EnvFile | Where-Object { $_ -match '^[A-Z]' }).Count
    Write-Host "📋 Environment file contains $ConfigCount configuration variables" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "🎯 Post-Provisioning Complete" -ForegroundColor Green
Write-Host "============================" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Generated Files:" -ForegroundColor Cyan
Write-Host "  - $EnvFile (Backend environment configuration)"
Write-Host ""
Write-Host "🔧 Next Steps:" -ForegroundColor Cyan
Write-Host "  - Review the generated environment file: Get-Content $EnvFile"
Write-Host "  - Load the environment file into your session"
Write-Host "  - Test your application with the new configuration"
Write-Host ""
