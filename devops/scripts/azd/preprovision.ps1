#!/usr/bin/env pwsh
#requires -version 7.0

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("bicep", "terraform")]
    [string]$Provider
)

# Function to display usage
function Show-Usage {
    Write-Host "Usage: preprovision.ps1 <provider>"
    Write-Host "  provider: bicep or terraform"
    exit 1
}

# Get the directory where this script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Process based on provider
switch ($Provider.ToLower()) {
    "bicep" {
        Write-Host "Bicep deployment detected"
        
        # Call ssl-preprovision.sh from helpers directory (no PS1 equivalent exists)
        $SslPreprovisionScript = Join-Path $ScriptDir "helpers/ssl-preprovision.ps1"
        if (Test-Path $SslPreprovisionScript) {
            Write-Host "Running SSL pre-provisioning setup..."
            & bash $SslPreprovisionScript
            if ($LASTEXITCODE -ne 0) {
                Write-Error "SSL pre-provisioning failed"
                exit 1
            }
        }
        else {
            Write-Error "ssl-preprovision.ps1 not found at $SslPreprovisionScript"
            exit 1
        }
    }
    
    "terraform" {
        Write-Host "Terraform deployment detected"
        Write-Host "Running Terraform Remote State initialization..."
        
        # Call tf-init.ps1 from helpers directory
        $TfInitScript = Join-Path $ScriptDir "helpers/tf-init.ps1"
        if (Test-Path $TfInitScript) {
            & $TfInitScript
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Terraform initialization encountered issues but continuing..."
            }
        }
        else {
            Write-Warning "tf-init.ps1 not found at $TfInitScript"
        }
        
        # Set terraform variables through environment exports and tfvars file
        Write-Host "Setting Terraform variables from Azure environment..."
        
        # Validate required variables
        $EnvironmentName = azd env get-value AZURE_ENV_NAME 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $EnvironmentName) {
            $EnvironmentName = $env:AZURE_ENV_NAME
        }

        $Location = azd env get-value AZURE_LOCATION 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $Location) {
            $Location = $env:AZURE_LOCATION
        }
        
        if (-not $EnvironmentName) {
            Write-Error "AZURE_ENV_NAME environment variable is not set"
            exit 1
        }
        
        if (-not $Location) {
            Write-Error "AZURE_LOCATION environment variable is not set"
            exit 1
        }
        
        # Set environment variables for Terraform
        $env:TF_VAR_environment_name = $EnvironmentName
        $env:TF_VAR_location = $Location
        
        # Get optional ACS phone number from AZD environment
        $AcsSourcePhoneNumber = ""
        $azdValue = azd env get-value ACS_SOURCE_PHONE_NUMBER 2>$null
        if ($LASTEXITCODE -eq 0 -and $azdValue) {
            $AcsSourcePhoneNumber = $azdValue
        }
        else {
            $AcsSourcePhoneNumber = ""
        }
        
        # Generate tfvars.json
        $TfVarsFile = "./infra-tf/main.tfvars.json"
        Write-Host "Generating $TfVarsFile..."
        
        # Build configuration object
        $Config = @{
            environment_name = $EnvironmentName
            location = $Location
        }
        
        if ($AcsSourcePhoneNumber) {
            $Config.acs_source_phone_number = $AcsSourcePhoneNumber
        }
        
        # Write to file
        $Config | ConvertTo-Json -Depth 10 | Set-Content $TfVarsFile -Encoding UTF8
        
        # Display configuration summary
        Write-Host ""
        Write-Host "✅ Terraform variables configured:" -ForegroundColor Green
        Write-Host "   Environment: $EnvironmentName"
        Write-Host "   Location: $Location"
        if ($AcsSourcePhoneNumber) {
            Write-Host "   ACS Phone: $AcsSourcePhoneNumber"
        }
        else {
            Write-Host "   ACS Phone: null (not set)"
        }
        Write-Host "   Config file: $TfVarsFile"
        exit 0
    }
    
    default {
        Write-Error "Invalid provider '$Provider'. Must be 'bicep' or 'terraform'"
        Show-Usage
    }
}
