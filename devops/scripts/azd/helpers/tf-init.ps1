#Requires -Version 7.0
#Requires -Module Az.Accounts, Az.Storage, Az.Resources

<#
.SYNOPSIS
    Terraform Remote State Storage Account Setup
.DESCRIPTION
    Creates Azure Storage Account for Terraform remote state using fully Entra-backed authentication.
    Only creates if storage values are not already defined in azd environment.
.PARAMETER Force
    Skip confirmation prompts
.EXAMPLE
    .\tf-init.ps1
    .\tf-init.ps1 -Force
#>

[CmdletBinding()]
param(
    [switch]$Force
)

# Constants
$script:RequiredCommands = @('az', 'azd')
$script:DefaultLocation = 'eastus2'
$script:DefaultEnvName = 'tfdev'

# Color constants for console output
$script:Colors = @{
    Info    = 'Cyan'
    Success = 'Green'
    Warning = 'Yellow'
    Error   = 'Red'
}

#region Helper Functions

function Write-ColorOutput {
    param(
        [Parameter(Mandatory)]
        [string]$Message,
        
        [Parameter(Mandatory)]
        [ValidateSet('Info', 'Success', 'Warning', 'Error')]
        [string]$Type,
        
        [string]$Prefix = $null
    )
    
    $icons = @{
        Info    = 'ℹ️  [INFO]'
        Success = '✅ [SUCCESS]'
        Warning = '⚠️  [WARNING]'
        Error   = '❌ [ERROR]'
    }
    
    $color = $script:Colors[$Type]
    $icon = $icons[$Type]
    $fullMessage = if ($Prefix) { "$icon $Prefix $Message" } else { "$icon $Message" }
    
    Write-Host $fullMessage -ForegroundColor $color
}

function Test-Dependencies {
    Write-ColorOutput "Checking required dependencies..." -Type Info
    
    $missingCommands = $script:RequiredCommands | Where-Object { 
        -not (Get-Command $_ -ErrorAction SilentlyContinue) 
    }
    
    if ($missingCommands) {
        Write-ColorOutput "Missing required commands: $($missingCommands -join ', ')" -Type Error
        exit 1
    }
    
    if (-not (Get-Command 'jq' -ErrorAction SilentlyContinue)) {
        Write-ColorOutput "Install jq for better JSON handling: https://stedolan.github.io/jq/" -Type Info
    }
    
    Write-ColorOutput "All dependencies found" -Type Success
}

function Test-AzureAuth {
    Write-ColorOutput "Checking Azure authentication..." -Type Info
    
    try {
        $accountInfo = az account show --query "{subscriptionId: id, tenantId: tenantId, user: user.name}" | ConvertFrom-Json
        Write-ColorOutput "Authenticated to Azure:" -Type Success
        Write-Host "  Subscription: $($accountInfo.subscriptionId)" -ForegroundColor White
        Write-Host "  Tenant: $($accountInfo.tenantId)" -ForegroundColor White
        Write-Host "  User: $($accountInfo.user)" -ForegroundColor White
    }
    catch {
        Write-ColorOutput "Not authenticated to Azure. Please run 'az login'" -Type Error
        exit 1
    }
}

function Get-AzdEnvValue {
    param(
        [Parameter(Mandatory)]
        [string]$Key,
        
        [string]$Default = $null
    )
    
    try {
        # Capture both stdout and stderr, then check exit code
        $output = & azd env get-value $Key 2>&1
        
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

function Test-ExistingStateConfig {
    Write-ColorOutput "Checking existing Terraform remote state configuration..." -Type Info
    
    # Check for new RS_* variables first
    $storageAccount = Get-AzdEnvValue -Key 'RS_STORAGE_ACCOUNT'
    $containerName = Get-AzdEnvValue -Key 'RS_CONTAINER_NAME'
    $resourceGroup = Get-AzdEnvValue -Key 'RS_RESOURCE_GROUP'
    
    # Debug output to show what we're getting
    Write-ColorOutput "Debug: Retrieved values:" -Type Info
    Write-Host "  RS_STORAGE_ACCOUNT: '$storageAccount'" -ForegroundColor Gray
    Write-Host "  RS_CONTAINER_NAME: '$containerName'" -ForegroundColor Gray
    Write-Host "  RS_RESOURCE_GROUP: '$resourceGroup'" -ForegroundColor Gray
    
    # Fall back to old TERRAFORM_STATE_* variables for backward compatibility
    if (-not $storageAccount) {
        $resourceGroup = Get-AzdEnvValue -Key 'TERRAFORM_STATE_RESOURCE_GROUP'
        Write-Host "  TERRAFORM_STATE_RESOURCE_GROUP: '$resourceGroup'" -ForegroundColor Gray
    }
    
    if ($storageAccount -and $containerName -and $resourceGroup) {
        Write-ColorOutput "Remote state already configured:" -Type Success
        Write-Host "  Storage Account: $storageAccount" -ForegroundColor White
        Write-Host "  Container: $containerName" -ForegroundColor White
        Write-Host "  Resource Group: $resourceGroup" -ForegroundColor White
        return $true
    }
    
    return $false
}

function New-ResourceNames {
    $envName = Get-AzdEnvValue -Key 'AZURE_ENV_NAME' -Default $script:DefaultEnvName
    $subscriptionId = (az account show --query id -o tsv)
    
    # Debug output
    Write-ColorOutput "Debug: Environment values for resource naming:" -Type Info
    Write-Host "  AZURE_ENV_NAME: '$envName'" -ForegroundColor Gray
    Write-Host "  Using default env name: $($envName -eq $script:DefaultEnvName)" -ForegroundColor Gray
    
    # Create deterministic but unique suffix
    $hashInput = "$subscriptionId$envName"
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($hashInput))
    $randomSuffix = [System.BitConverter]::ToString($hash)[0..15] -join '' -replace '-', '' | ForEach-Object { $_.ToLower() }
    $randomSuffix = $randomSuffix.Substring(0, 8)
    
    # Storage account names must be lowercase, alphanumeric, 3-24 chars
    $storageAccountName = "tfstate$randomSuffix"
    if ($storageAccountName.Length -gt 24) {
        $storageAccountName = $storageAccountName.Substring(0, 24)
    }
    
    $script:StorageAccountName = $storageAccountName
    $script:ContainerName = 'tfstate'
    $script:ResourceGroupName = "rg-tfstate-$envName-$randomSuffix"
    
    Write-ColorOutput "Generated resource names:" -Type Info
    Write-Host "  Storage Account: $script:StorageAccountName" -ForegroundColor White
    Write-Host "  Container: $script:ContainerName" -ForegroundColor White
    Write-Host "  Resource Group: $script:ResourceGroupName" -ForegroundColor White
}

function New-ResourceGroup {
    $location = Get-AzdEnvValue -Key 'AZURE_LOCATION' -Default $script:DefaultLocation

    if (-not $location) {
        Write-ColorOutput "AZURE_LOCATION not set, using default: $location" -Type Warning
    }

    Write-ColorOutput "Creating resource group: $script:ResourceGroupName" -Type Info

    $rgExists = az group show --name $script:ResourceGroupName --query "name" -o tsv 2>$null
    if ($rgExists -eq $script:ResourceGroupName) {
        Write-ColorOutput "Resource group already exists." -Type Success
    }
    else {
        az group create --name $script:ResourceGroupName --location $location --output none
        Write-ColorOutput "Resource group created successfully." -Type Success
    }
}

function New-StorageAccount {
    Write-ColorOutput "Creating storage account: $script:StorageAccountName" -Type Info

    $saExists = az storage account show --name $script:StorageAccountName --resource-group $script:ResourceGroupName --query "name" -o tsv 2>$null
    if ($saExists -eq $script:StorageAccountName) {
        Write-ColorOutput "Storage account already exists." -Type Success
    }
    else {
        az storage account create `
            --name $script:StorageAccountName `
            --resource-group $script:ResourceGroupName `
            --location (Get-AzdEnvValue -Key 'AZURE_LOCATION' -Default $script:DefaultLocation) `
            --sku Standard_LRS `
            --kind StorageV2 `
            --allow-blob-public-access false `
            --min-tls-version TLS1_2 `
            --output none

        Write-ColorOutput "Storage account created successfully." -Type Success
    }

    # Enable versioning and change feed
    Write-ColorOutput "Enabling blob versioning..." -Type Info
    az storage account blob-service-properties update `
        --account-name $script:StorageAccountName `
        --resource-group $script:ResourceGroupName `
        --enable-versioning true `
        --enable-change-feed true `
        --output none

    Write-ColorOutput "Storage account configured with versioning and change feed." -Type Success
}

function New-StorageContainer {
    Write-ColorOutput "Creating storage container: $script:ContainerName" -Type Info
    $containerExists = az storage container show `
        --name $script:ContainerName `
        --account-name $script:StorageAccountName `
        --auth-mode login `
        --query "name" -o tsv 2>$null

    if ($containerExists -eq $script:ContainerName) {
        Write-ColorOutput "Storage container already exists." -Type Success
    }
    else {
        az storage container create `
            --name $script:ContainerName `
            --account-name $script:StorageAccountName `
            --auth-mode login `
            --output none

        Write-ColorOutput "Storage container created successfully." -Type Success
    }
}

function Set-StoragePermissions {
    Write-ColorOutput "Assigning Storage Blob Data Contributor permissions..." -Type Info
    
    $currentUserId = az ad signed-in-user show --query id -o tsv
    $storageAccountId = az storage account show `
        --name $script:StorageAccountName `
        --resource-group $script:ResourceGroupName `
        --query id -o tsv
    
    # Check if role assignment already exists
    $existingAssignment = az role assignment list `
        --assignee $currentUserId `
        --scope $storageAccountId `
        --role "Storage Blob Data Contributor" `
        --query "length(@)" -o tsv
    
    if ($existingAssignment -eq "1") {
        Write-ColorOutput "Storage permissions already assigned." -Type Success
    }
    else {
        az role assignment create `
            --assignee $currentUserId `
            --role "Storage Blob Data Contributor" `
            --scope $storageAccountId `
            --output none
            
        Write-ColorOutput "Storage permissions assigned successfully." -Type Success
    }
}

function Set-AzdEnvironmentVariables {
    Write-ColorOutput "Setting azd environment variables..." -Type Info
    
    azd env set RS_STORAGE_ACCOUNT $script:StorageAccountName
    azd env set RS_CONTAINER_NAME $script:ContainerName
    azd env set RS_RESOURCE_GROUP $script:ResourceGroupName
    azd env set RS_STATE_KEY "terraform.tfstate"
    
    Write-ColorOutput "Environment variables set:" -Type Success
    Write-Host "  RS_STORAGE_ACCOUNT=$script:StorageAccountName" -ForegroundColor White
    Write-Host "  RS_CONTAINER_NAME=$script:ContainerName" -ForegroundColor White
    Write-Host "  RS_RESOURCE_GROUP=$script:ResourceGroupName" -ForegroundColor White
    Write-Host "  RS_STATE_KEY=terraform.tfstate" -ForegroundColor White
}

function Initialize-TerraformDirectory {
    $infraDir = "./infra-tf"
    
    Write-ColorOutput "Ensuring Terraform directory exists..." -Type Info
    
    if (-not (Test-Path $infraDir)) {
        New-Item -ItemType Directory -Path $infraDir -Force | Out-Null
        Write-ColorOutput "Created Terraform directory: $infraDir" -Type Success
    }
    else {
        Write-ColorOutput "Terraform directory already exists: $infraDir" -Type Success
    }
}

function Update-TerraformVars {
    $tfvarsFile = "./infra-tf/main.tfvars.json"
    $providerConfFile = "./infra-tf/provider.conf.json"
    
    Write-ColorOutput "Updating Terraform variables and configuration files..." -Type Info
    
    # Get azd environment values
    $envName = Get-AzdEnvValue -Key 'AZURE_ENV_NAME' -Default $script:DefaultEnvName
    $location = Get-AzdEnvValue -Key 'AZURE_LOCATION' -Default $script:DefaultLocation
    $subscriptionId = az account show --query id -o tsv
    
    # Debug output
    Write-ColorOutput "Debug: Environment values for Terraform vars:" -Type Info
    Write-Host "  AZURE_ENV_NAME: '$envName' (using default: $($envName -eq $script:DefaultEnvName))" -ForegroundColor Gray
    Write-Host "  AZURE_LOCATION: '$location' (using default: $($location -eq $script:DefaultLocation))" -ForegroundColor Gray
    
    if ($envName -eq $script:DefaultEnvName) {
        Write-ColorOutput "AZURE_ENV_NAME not set, using default: $envName" -Type Warning
    }
    
    if ($location -eq $script:DefaultLocation) {
        Write-ColorOutput "AZURE_LOCATION not set, using default: $location" -Type Warning
    }
    
    # Create or update tfvars file
    $tfvarsContent = @{
        environment_name = $envName
        location = $location
    } | ConvertTo-Json -Depth 3
    
    if (Test-Path $tfvarsFile) {
        Write-ColorOutput "Updating existing tfvars file: $tfvarsFile" -Type Info
        
        if (Get-Command 'jq' -ErrorAction SilentlyContinue) {
            $tempFile = [System.IO.Path]::GetTempFileName()
            $existingContent = Get-Content $tfvarsFile -Raw | ConvertFrom-Json
            $existingContent.environment_name = $envName
            $existingContent.location = $location
            $existingContent | ConvertTo-Json -Depth 3 | Set-Content $tempFile
            Move-Item $tempFile $tfvarsFile
            Write-ColorOutput "Updated tfvars file using PowerShell JSON handling." -Type Success
        }
        else {
            Write-ColorOutput "Recreating tfvars file (may lose other variables)." -Type Warning
            $tfvarsContent | Set-Content $tfvarsFile
        }
    }
    else {
        Write-ColorOutput "Creating new tfvars file: $tfvarsFile" -Type Info
        $tfvarsContent | Set-Content $tfvarsFile
    }
    
    # Create provider configuration file
    Write-ColorOutput "Creating provider configuration file: $providerConfFile" -Type Info
    $providerConfig = @{
        subscription_id = $subscriptionId
        environment_name = $envName
        location = $location
        terraform_state_storage_account = $script:StorageAccountName
        terraform_state_container = $script:ContainerName
        terraform_state_resource_group = $script:ResourceGroupName
    } | ConvertTo-Json -Depth 3
    
    $providerConfig | Set-Content $providerConfFile
    
    Write-ColorOutput "Terraform configuration files updated:" -Type Success
    Write-Host "  environment_name: $envName" -ForegroundColor White
    Write-Host "  location: $location" -ForegroundColor White
    Write-Host "  subscription_id: $subscriptionId" -ForegroundColor White
    Write-Host "  Files: $tfvarsFile, $providerConfFile" -ForegroundColor White
}

function New-ProviderConfig {
    $providerConfigFile = "./infra-tf/provider.conf.json"
    
    Write-ColorOutput "Creating azd Terraform provider configuration..." -Type Info
    
    $providerConfig = @{
        resource_group_name = "`${RS_RESOURCE_GROUP}"
        storage_account_name = "`${RS_STORAGE_ACCOUNT}"
        container_name = "`${RS_CONTAINER_NAME}"
        key = "azd/$((Get-AzdEnvValue -Key 'AZURE_ENV_NAME' -Default $script:DefaultEnvName)).tfstate"
    } | ConvertTo-Json -Depth 3
    
    $providerConfig | Set-Content $providerConfigFile
    
    Write-ColorOutput "Provider configuration created: $providerConfigFile" -Type Success
}

function Test-Setup {
    Write-ColorOutput "Validating Terraform remote state setup..." -Type Info
    
    try {
        az storage blob list `
            --container-name $script:ContainerName `
            --account-name $script:StorageAccountName `
            --auth-mode login `
            --output none 2>$null
        Write-ColorOutput "Storage access validated successfully." -Type Success
    }
    catch {
        Write-ColorOutput "Storage access validation failed." -Type Error
        return $false
    }
    
    if (Get-Command 'terraform' -ErrorAction SilentlyContinue) {
        Push-Location "./infra-tf"
        try {
            terraform init -backend=false *>$null
            Write-ColorOutput "Terraform initialization test passed." -Type Success
        }
        catch {
            Write-ColorOutput "Terraform initialization test failed, but continuing..." -Type Warning
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-ColorOutput "Terraform not found. Skipping initialization test." -Type Info
    }
    
    return $true
}

#endregion

#region Main

function Main {
    Write-Host "=========================================================================" -ForegroundColor Cyan
    Write-Host "🏗️  Terraform Remote State Storage Setup" -ForegroundColor Cyan
    Write-Host "=========================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Check dependencies and authentication
    Test-Dependencies
    Test-AzureAuth
    
    # Check if remote state is already configured
    if (Test-ExistingStateConfig) {
        Write-ColorOutput "Remote state storage already configured. Exiting." -Type Info
        return
    }
    
    # Generate resource names
    New-ResourceNames
    
    if (-not $Force) {
        Write-Host ""
        Write-ColorOutput "About to create the following resources:" -Type Info
        Write-Host "  Resource Group: $script:ResourceGroupName" -ForegroundColor White
        Write-Host "  Storage Account: $script:StorageAccountName" -ForegroundColor White
        Write-Host "  Container: $script:ContainerName" -ForegroundColor White
        Write-Host ""
        
        $confirmation = Read-Host "Continue? (y/N)"
        if ($confirmation -notmatch '^[Yy]$') {
            Write-ColorOutput "Operation cancelled by user." -Type Warning
            return
        }
    }
    
    try {
        # Create infrastructure
        New-ResourceGroup
        New-StorageAccount
        New-StorageContainer
        Set-StoragePermissions
        
        # Configure azd and Terraform
        Set-AzdEnvironmentVariables
        Initialize-TerraformDirectory
        Update-TerraformVars
        New-ProviderConfig
        
        # Validate setup
        if (Test-Setup) {
            Write-Host ""
            Write-ColorOutput "🎉 Terraform remote state setup completed successfully!" -Type Success
            Write-Host ""
            Write-ColorOutput "Next steps:" -Type Info
            Write-Host "  1. Run 'terraform init' in the infra-tf directory" -ForegroundColor White
            Write-Host "  2. Run 'azd provision' to deploy your infrastructure" -ForegroundColor White
        }
        else {
            Write-ColorOutput "Setup completed with warnings. Please verify configuration manually." -Type Warning
        }
        exit 0
    }
    catch {
        Write-ColorOutput "Setup failed: $($_.Exception.Message)" -Type Error
        exit 1
    }
}

# Handle script interruption
trap {
    Write-ColorOutput "Script interrupted by user" -Type Error
    exit 130
}

# Run main function
Main

#endregion
