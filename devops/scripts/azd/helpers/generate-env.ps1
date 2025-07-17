#Requires -Version 7.0
#Requires -Module Az.Accounts

<#
.SYNOPSIS
    Azure Environment Configuration Generator
.DESCRIPTION
    Generates environment configuration files from AZD environment values.
    Can be used independently or called from other scripts.
.PARAMETER EnvironmentName
    The AZD environment name (defaults to current environment or 'dev')
.PARAMETER OutputFile
    The output file path (defaults to .env.{EnvironmentName})
.PARAMETER ShowValues
    Display configuration values in output (security risk - use carefully)
.EXAMPLE
    .\generate-env.ps1
    .\generate-env.ps1 -EnvironmentName "prod" -OutputFile ".env.production"
    .\generate-env.ps1 -ShowValues
#>

[CmdletBinding()]
param(
    [string]$EnvironmentName,
    [string]$OutputFile,
    [switch]$ShowValues
)

# Configuration
$script:DefaultEnvName = 'dev'

# Color constants
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
        Info    = 'ℹ️'
        Success = '✅'
        Warning = '⚠️'
        Error   = '❌'
    }
    
    $color = $script:Colors[$Type]
    $icon = $icons[$Type]
    $fullMessage = if ($Prefix) { "$icon $Prefix $Message" } else { "$icon $Message" }
    
    Write-Host $fullMessage -ForegroundColor $color
}

function Get-AzdValue {
    param(
        [Parameter(Mandatory)]
        [string]$Key,
        
        [string]$Fallback = ""
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
        
        # Return fallback if command failed or value is invalid
        return $Fallback
    }
    catch {
        # Return fallback on any exception
        return $Fallback
    }
}

function Test-AzdEnvironment {
    Write-ColorOutput "Validating AZD environment..." -Type Info
    
    if (-not (Get-Command 'azd' -ErrorAction SilentlyContinue)) {
        Write-ColorOutput "Azure Developer CLI (azd) is not installed or not in PATH" -Type Error
        exit 1
    }
    
    # Test if we can access azd environment
    try {
        $testValue = & azd env get-value AZURE_ENV_NAME 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-ColorOutput "No active AZD environment found. Output: $testValue" -Type Error
            Write-ColorOutput "Please run 'azd env select' or 'azd init' to set up an environment" -Type Error
            exit 1
        }
        Write-ColorOutput "AZD environment validation passed" -Type Success
        Write-ColorOutput "Active environment: $testValue" -Type Info
    }
    catch {
        Write-ColorOutput "No active AZD environment found. Error: $($_.Exception.Message)" -Type Error
        Write-ColorOutput "Please run 'azd env select' or 'azd init' to set up an environment" -Type Error
        exit 1
    }
}

function New-EnvironmentFile {
    param(
        [string]$FilePath,
        [string]$EnvName
    )
    
    Write-ColorOutput "Generating environment file: $FilePath" -Type Info
    
    # Define configuration mappings
    $configMappings = [ordered]@{
        # Application Insights Configuration
        'APPLICATIONINSIGHTS_CONNECTION_STRING' = @{ Key = 'APPLICATIONINSIGHTS_CONNECTION_STRING'; Default = '' }
        # Azure OpenAI Configuration
        'AZURE_OPENAI_KEY' = @{ Key = 'AZURE_OPENAI_KEY'; Default = '' }
        'AZURE_OPENAI_ENDPOINT' = @{ Key = 'AZURE_OPENAI_ENDPOINT'; Default = '' }
        'AZURE_OPENAI_DEPLOYMENT' = @{ Key = 'AZURE_OPENAI_CHAT_DEPLOYMENT_ID'; Default = '' }
        'AZURE_OPENAI_API_VERSION' = @{ Key = 'AZURE_OPENAI_API_VERSION'; Default = '2024-10-01-preview' }
        'AZURE_OPENAI_CHAT_DEPLOYMENT_ID' = @{ Key = 'AZURE_OPENAI_CHAT_DEPLOYMENT_ID'; Default = '' }
        'AZURE_OPENAI_CHAT_DEPLOYMENT_VERSION' = @{ Key = ''; Default = '2024-10-01-preview' }
        
        # Azure Speech Services Configuration
        'AZURE_SPEECH_ENDPOINT' = @{ Key = 'AZURE_SPEECH_ENDPOINT'; Default = '' }
        'AZURE_SPEECH_KEY' = @{ Key = 'AZURE_SPEECH_KEY'; Default = '' }
        'AZURE_SPEECH_RESOURCE_ID' = @{ Key = 'AZURE_SPEECH_RESOURCE_ID'; Default = '' }
        'AZURE_SPEECH_REGION' = @{ Key = 'AZURE_SPEECH_REGION'; Default = '' }
        
        # Base URL Configuration
        'BASE_URL' = @{ Key = ''; Default = '<Your publicly routable URL for the backend app, e.g devtunnel host>' }
        'BACKEND_APP_SERVICE_URL' = @{ Key = 'BACKEND_APP_SERVICE_URL'; Default = '' }
        
        # Azure Communication Services Configuration
        'ACS_CONNECTION_STRING' = @{ Key = 'ACS_CONNECTION_STRING'; Default = '' }
        'ACS_SOURCE_PHONE_NUMBER' = @{ Key = 'ACS_SOURCE_PHONE_NUMBER'; Default = '' }
        'ACS_ENDPOINT' = @{ Key = 'ACS_ENDPOINT'; Default = '' }
        
        # Redis Configuration
        'REDIS_HOST' = @{ Key = 'REDIS_HOSTNAME'; Default = '' }
        'REDIS_PORT' = @{ Key = 'REDIS_PORT'; Default = '6380' }
        'REDIS_PASSWORD' = @{ Key = 'REDIS_PASSWORD'; Default = '' }
        
        # Azure Storage Configuration
        'AZURE_STORAGE_CONNECTION_STRING' = @{ Key = 'AZURE_STORAGE_CONNECTION_STRING'; Default = '' }
        'AZURE_STORAGE_CONTAINER_URL' = @{ Key = 'AZURE_STORAGE_CONTAINER_URL'; Default = '' }
        'AZURE_STORAGE_ACCOUNT_NAME' = @{ Key = 'AZURE_STORAGE_ACCOUNT_NAME'; Default = '' }
        
        # Azure Cosmos DB Configuration
        'AZURE_COSMOS_DATABASE_NAME' = @{ Key = 'AZURE_COSMOS_DATABASE_NAME'; Default = 'audioagentdb' }
        'AZURE_COSMOS_COLLECTION_NAME' = @{ Key = 'AZURE_COSMOS_COLLECTION_NAME'; Default = 'audioagentcollection' }
        'AZURE_COSMOS_CONNECTION_STRING' = @{ Key = 'AZURE_COSMOS_CONNECTION_STRING'; Default = '' }
        
        # Azure Identity Configuration
        'AZURE_SUBSCRIPTION_ID' = @{ Key = 'AZURE_SUBSCRIPTION_ID'; Default = '' }
        
        # Azure Resource Configuration
        'AZURE_RESOURCE_GROUP' = @{ Key = 'AZURE_RESOURCE_GROUP'; Default = '' }
        'AZURE_LOCATION' = @{ Key = 'AZURE_LOCATION'; Default = '' }
        
        # Application Configuration
        'ACS_STREAMING_MODE' = @{ Key = ''; Default = 'media' }
        'ENVIRONMENT' = @{ Key = ''; Default = $EnvName }
        
        # Logging Configuration
        'LOG_LEVEL' = @{ Key = 'LOG_LEVEL'; Default = 'INFO' }
        'ENABLE_DEBUG' = @{ Key = 'ENABLE_DEBUG'; Default = 'false' }
    }
    
    # Generate file content
    $content = @()
    $content += "# Generated automatically by generate-env.ps1 on $(Get-Date)"
    $content += "# Environment: $EnvName"
    $content += "# ================================================================="
    $content += ""
    
    # Group configurations by section
    $sections = @{
        'Azure OpenAI Configuration' = @('AZURE_OPENAI_KEY', 'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_DEPLOYMENT', 'AZURE_OPENAI_API_VERSION', 'AZURE_OPENAI_CHAT_DEPLOYMENT_ID', 'AZURE_OPENAI_CHAT_DEPLOYMENT_VERSION')
        'Azure Speech Services Configuration' = @('AZURE_SPEECH_ENDPOINT', 'AZURE_SPEECH_KEY', 'AZURE_SPEECH_RESOURCE_ID', 'AZURE_SPEECH_REGION')
        'Base URL Configuration' = @('BASE_URL', 'BACKEND_APP_SERVICE_URL')
        'Azure Communication Services Configuration' = @('ACS_CONNECTION_STRING', 'ACS_SOURCE_PHONE_NUMBER', 'ACS_ENDPOINT')
        'Redis Configuration' = @('REDIS_HOST', 'REDIS_PORT', 'REDIS_PASSWORD')
        'Azure Storage Configuration' = @('AZURE_STORAGE_CONNECTION_STRING', 'AZURE_STORAGE_CONTAINER_URL', 'AZURE_STORAGE_ACCOUNT_NAME')
        'Azure Cosmos DB Configuration' = @('AZURE_COSMOS_DATABASE_NAME', 'AZURE_COSMOS_COLLECTION_NAME', 'AZURE_COSMOS_CONNECTION_STRING')
        'Azure Identity Configuration' = @('AZURE_SUBSCRIPTION_ID')
        'Azure Resource Configuration' = @('AZURE_RESOURCE_GROUP', 'AZURE_LOCATION')
        'Application Configuration' = @('ACS_STREAMING_MODE', 'ENVIRONMENT')
        'Logging Configuration' = @('LOG_LEVEL', 'ENABLE_DEBUG')
    }
    
    foreach ($sectionName in $sections.Keys) {
        $content += "# $sectionName"
        
        foreach ($varName in $sections[$sectionName]) {
            $mapping = $configMappings[$varName]
            $value = if ($mapping.Key) { Get-AzdValue -Key $mapping.Key -Fallback $mapping.Default } else { $mapping.Default }
            $content += "$varName=$value"
        }
        
        $content += ""
    }
    
    # Write to file
    $content | Set-Content -Path $FilePath -Encoding UTF8
    
    # Set appropriate permissions (equivalent to chmod 644)
    if (Get-Command 'icacls' -ErrorAction SilentlyContinue) {
        icacls $FilePath /grant:r "$env:USERNAME:(R)" *>$null
    }
    
    Write-ColorOutput "Environment file generated successfully" -Type Success
}

function Test-EnvironmentFile {
    param([string]$FilePath)
    
    Write-ColorOutput "Validating generated environment file..." -Type Info
    
    if (-not (Test-Path $FilePath)) {
        Write-ColorOutput "Environment file was not created: $FilePath" -Type Error
        exit 1
    }
    
    # Count non-empty configuration variables
    $content = Get-Content $FilePath
    $varCount = ($content | Where-Object { $_ -match '^[A-Z][A-Z_]*=' }).Count
    
    if ($varCount -eq 0) {
        Write-ColorOutput "No configuration variables found in environment file" -Type Error
        exit 1
    }
    
    Write-ColorOutput "Environment file validation passed" -Type Success
    Write-ColorOutput "Found $varCount configuration variables" -Type Info -Prefix "📊"
}

function Show-EnvironmentSummary {
    param(
        [string]$FilePath,
        [string]$EnvName
    )
    
    Write-Host ""
    Write-ColorOutput "Environment File Summary" -Type Info -Prefix "📊"
    Write-Host "==========================" -ForegroundColor Cyan
    Write-Host "   File: $FilePath" -ForegroundColor White
    Write-Host "   Environment: $EnvName" -ForegroundColor White
    Write-Host "   Generated: $(Get-Date)" -ForegroundColor White
    Write-Host ""
    
    # Check configuration sections
    $content = Get-Content $FilePath
    $sections = @{
        'Azure OpenAI' = 'AZURE_OPENAI_ENDPOINT='
        'Azure Speech Services' = 'AZURE_SPEECH_ENDPOINT='
        'Azure Communication Services' = 'ACS_CONNECTION_STRING='
        'Redis Cache' = 'REDIS_HOST='
        'Cosmos DB' = 'AZURE_COSMOS_CONNECTION_STRING='
    }
    
    Write-ColorOutput "Configuration Sections:" -Type Info -Prefix "🔧"
    foreach ($sectionName in $sections.Keys) {
        $pattern = $sections[$sectionName]
        if ($content | Where-Object { $_ -match [regex]::Escape($pattern) -and $_ -notmatch '=$' }) {
            Write-Host "   ✅ $sectionName" -ForegroundColor Green
        }
        else {
            Write-Host "   ⚠️  $sectionName (missing configuration)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-ColorOutput "Usage:" -Type Info -Prefix "💡"
    Write-Host "   Load in PowerShell: Get-Content $FilePath | ForEach-Object { if (\$_ -match '^([^#][^=]+)=(.*)') { [Environment]::SetEnvironmentVariable(\$Matches[1], \$Matches[2], 'Process') } }" -ForegroundColor White
    Write-Host "   View contents: Get-Content $FilePath" -ForegroundColor White
    Write-Host "   Edit manually: code $FilePath" -ForegroundColor White
    
    if ($ShowValues) {
        Write-Host ""
        Write-ColorOutput "⚠️  Configuration Values (SENSITIVE - DO NOT SHARE):" -Type Warning
        $content | Where-Object { $_ -match '^[A-Z][A-Z_]*=' } | ForEach-Object {
            Write-Host "   $_" -ForegroundColor Gray
        }
    }
}

#endregion

#region Main

function Main {
    # Get parameters with defaults
    $script:AzdEnvName = if ($EnvironmentName) { 
        $EnvironmentName 
    } else { 
        Get-AzdValue -Key 'AZURE_ENV_NAME' -Fallback $script:DefaultEnvName 
    }
    
    $script:OutputFile = if ($OutputFile) { 
        $OutputFile 
    } else { 
        ".env.$script:AzdEnvName" 
    }
    
    Write-ColorOutput "Generating Environment Configuration File" -Type Info -Prefix "📄"
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-ColorOutput "Configuration:" -Type Info -Prefix "🔧"
    Write-Host "   Environment: $script:AzdEnvName" -ForegroundColor White
    Write-Host "   Output File: $script:OutputFile" -ForegroundColor White
    Write-Host ""
    
    Write-ColorOutput "Starting environment file generation..." -Type Info -Prefix "🚀"
    
    try {
        # Validate AZD environment
        Test-AzdEnvironment
        
        # Generate environment file
        New-EnvironmentFile -FilePath $script:OutputFile -EnvName $script:AzdEnvName
        
        # Validate generated file
        Test-EnvironmentFile -FilePath $script:OutputFile
        
        # Show summary
        Show-EnvironmentSummary -FilePath $script:OutputFile -EnvName $script:AzdEnvName
        
        Write-Host ""
        Write-ColorOutput "Environment file generation complete!" -Type Success
        Write-ColorOutput "Generated: $script:OutputFile" -Type Success -Prefix "📄"
        exit 0
    }
    catch {
        Write-ColorOutput "Environment file generation failed: $($_.Exception.Message)" -Type Error
        exit 1
    }
}

# Run main function
Main

#endregion
