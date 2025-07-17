#Requires -Version 7.0

<#
.SYNOPSIS
    Azure App Service Deployment Script
.DESCRIPTION
    Deploys backend applications to Azure App Service with configurable file 
    inclusion/exclusion patterns and automatic validation. Handles deployment 
    timeouts gracefully.
.PARAMETER AgentName
    The agent name to deploy (defaults to 'RTAgent')
.EXAMPLE
    .\appsvc-deploy.ps1
    .\appsvc-deploy.ps1 -AgentName "RTMedAgent"
#>

[CmdletBinding()]
param(
    [string]$AgentName = 'RTAgent'
)

# ========================================================================
# 🚀 Azure App Service Deployment Script
# ========================================================================
# This script deploys backend applications to Azure App Service with
# configurable file inclusion/exclusion patterns and automatic validation.
#
# Usage: .\appsvc-deploy.ps1 [AgentName]
#
# ========================================================================

# Configuration
$script:BackendDirs = @('src', 'utils')
$script:RequiredFiles = @('requirements.txt')
$script:ExcludePatterns = @('__pycache__', '*.pyc', '.pytest_cache', '*.log', '.coverage', 'htmlcov', '.DS_Store', '.git', 'node_modules', '*.tmp', '*.temp')

# Helper functions
function Write-LogInfo { param([string]$Message) Write-Host "ℹ️  [INFO] $Message" -ForegroundColor Cyan }
function Write-LogSuccess { param([string]$Message) Write-Host "✅ [SUCCESS] $Message" -ForegroundColor Green }
function Write-LogWarning { param([string]$Message) Write-Host "⚠️  [WARNING] $Message" -ForegroundColor Yellow }
function Write-LogError { param([string]$Message) Write-Host "❌ [ERROR] $Message" -ForegroundColor Red }

# Check if required commands exist
function Test-Dependencies {
    $requiredCommands = @('az', 'azd')
    $missingCommands = @()
    
    foreach ($cmd in $requiredCommands) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            $missingCommands += $cmd
        }
    }
    
    if ($missingCommands.Count -gt 0) {
        Write-LogError "Missing required commands: $($missingCommands -join ', ')"
        Write-LogError "Please install missing dependencies and try again."
        exit 1
    }
}

# Get azd environment variable value
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

# Validate deployment configuration
function Test-DeploymentConfig {
    Write-LogInfo "Validating deployment configuration..."
    
    $errors = @()
    
    # Get AZD variables
    $script:ResourceGroup = Get-AzdEnvValue -Key "AZURE_RESOURCE_GROUP"
    $script:BackendApp = Get-AzdEnvValue -Key "BACKEND_APP_SERVICE_NAME"
    $script:AzdEnv = Get-AzdEnvValue -Key "AZURE_ENV_NAME"
    $script:AgentBackend = "rtagents/$AgentName/backend"
    
    # Check required AZD variables
    if ([string]::IsNullOrEmpty($script:ResourceGroup)) { $errors += "AZURE_RESOURCE_GROUP" }
    if ([string]::IsNullOrEmpty($script:BackendApp)) { $errors += "BACKEND_APP_SERVICE_NAME" }
    if ([string]::IsNullOrEmpty($script:AzdEnv)) { $errors += "AZURE_ENV_NAME" }
    
    # Debug output
    Write-LogInfo "Debug: Retrieved environment values:"
    Write-Host "  AZURE_RESOURCE_GROUP: '$script:ResourceGroup'" -ForegroundColor Gray
    Write-Host "  BACKEND_APP_SERVICE_NAME: '$script:BackendApp'" -ForegroundColor Gray
    Write-Host "  AZURE_ENV_NAME: '$script:AzdEnv'" -ForegroundColor Gray
    
    # Check agent backend directory
    if (-not (Test-Path $script:AgentBackend -PathType Container)) {
        $errors += "Agent backend directory: $script:AgentBackend"
    }
    
    if ($errors.Count -gt 0) {
        Write-LogError "Configuration validation failed:"
        foreach ($error in $errors) {
            Write-Host "   - Missing: $error" -ForegroundColor Red
        }
        exit 1
    }
    
    Write-LogSuccess "Configuration validated successfully"
    Write-Host "  Resource Group: $script:ResourceGroup"
    Write-Host "  Backend App: $script:BackendApp"
    Write-Host "  Agent: $AgentName"
    Write-Host "  AZD Environment: $script:AzdEnv"
}

# Copy files with exclusions
function Copy-WithExclusions {
    param([string]$Source, [string]$Destination)
    
    if (-not (Test-Path $Source -PathType Container)) {
        Write-LogWarning "Source directory not found: $Source"
        return $false
    }
    
    Write-LogInfo "Copying: $Source -> $Destination"
    
    # Ensure destination exists
    if (-not (Test-Path $Destination -PathType Container)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }
    
    # Use robocopy on Windows, rsync elsewhere
    if ($IsWindows -and (Get-Command robocopy -ErrorAction SilentlyContinue)) {
        $robocopyArgs = @($Source, $Destination, "/E", "/XD") + $script:ExcludePatterns + @("/XF") + $script:ExcludePatterns + @("/NFL", "/NDL", "/NJH", "/NJS")
        $result = Start-Process -FilePath "robocopy" -ArgumentList $robocopyArgs -Wait -PassThru -NoNewWindow
        return ($result.ExitCode -le 7)  # Robocopy exit codes 0-7 are success
    }
    else {
        # Fallback to PowerShell copy with manual exclusion
        Get-ChildItem -Path $Source -Recurse | Where-Object {
            $item = $_
            $relativePath = $item.FullName.Substring($Source.Length + 1)
            $exclude = $false
            foreach ($pattern in $script:ExcludePatterns) {
                if ($relativePath -like $pattern -or $item.Name -like $pattern) {
                    $exclude = $true
                    break
                }
            }
            return -not $exclude
        } | ForEach-Object {
            $destPath = $_.FullName.Replace($Source, $Destination)
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            if ($_.PSIsContainer) {
                if (-not (Test-Path $destPath)) {
                    New-Item -ItemType Directory -Path $destPath -Force | Out-Null
                }
            } else {
                Copy-Item $_.FullName -Destination $destPath -Force
            }
        }
        return $true
    }
}

# Prepare deployment package
function New-DeploymentPackage {
    param([string]$TempDir)
    
    Write-LogInfo "Preparing deployment package..."
    
    # Clean and create temp deployment directory
    if (Test-Path $TempDir) { Remove-Item -Path $TempDir -Recurse -Force }
    New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
    
    # Copy agent backend
    $agentDestination = Join-Path $TempDir $script:AgentBackend
    New-Item -ItemType Directory -Path $agentDestination -Force | Out-Null
    Copy-WithExclusions -Source $script:AgentBackend -Destination $agentDestination
    
    # Copy shared directories
    foreach ($dir in $script:BackendDirs) {
        if (Test-Path $dir -PathType Container) {
            $dirDestination = Join-Path $TempDir $dir
            Copy-WithExclusions -Source $dir -Destination $dirDestination
        } else {
            Write-LogWarning "Configured directory not found: $dir"
        }
    }
    
    # Copy required files
    foreach ($file in $script:RequiredFiles) {
        if (Test-Path $file -PathType Leaf) {
            Write-LogInfo "Copying required file: $file"
            Copy-Item -Path $file -Destination $TempDir -Force
        } else {
            Write-LogError "Required file missing: $file"
            exit 1
        }
    }
    
    Write-LogSuccess "Deployment package prepared successfully"
}

# Create deployment zip
function New-DeploymentZip {
    param([string]$TempDir)
    
    Write-LogInfo "Creating deployment zip..."
    
    Push-Location $TempDir
    try {
        # Get all files excluding patterns
        $filesToZip = Get-ChildItem -Recurse -File | Where-Object {
            $file = $_
            $relativePath = $file.FullName.Substring($TempDir.Length + 1)
            $exclude = $false
            foreach ($pattern in $script:ExcludePatterns) {
                if ($relativePath -like $pattern -or $file.Name -like $pattern) {
                    $exclude = $true
                    break
                }
            }
            return -not $exclude
        }
        
        $zipPath = Join-Path $TempDir "backend.zip"
        
        if ($filesToZip) {
            Compress-Archive -Path $filesToZip.FullName -DestinationPath $zipPath -CompressionLevel Optimal -Force
        } else {
            Write-LogError "No files found to zip"
            exit 1
        }
        
        if (-not (Test-Path $zipPath)) {
            Write-LogError "Failed to create backend.zip"
            exit 1
        }
        
        $zipSize = (Get-Item $zipPath).Length
        $zipSizeHuman = if ($zipSize -gt 1MB) { "{0:N2} MB" -f ($zipSize / 1MB) } 
                       elseif ($zipSize -gt 1KB) { "{0:N2} KB" -f ($zipSize / 1KB) } 
                       else { "$zipSize bytes" }
        
        Write-LogSuccess "Deployment zip created successfully (size: $zipSizeHuman)"
        return $zipPath
    }
    finally {
        Pop-Location
    }
}

# Configure App Service settings
function Set-AppServiceConfig {
    Write-LogInfo "Configuring App Service settings..."
    
    # Set startup command
    az webapp config set --resource-group $script:ResourceGroup --name $script:BackendApp --startup-file "python -m uvicorn main:app --host 0.0.0.0 --port 8000" --output none
    
    # Set environment variables
    az webapp config appsettings set --resource-group $script:ResourceGroup --name $script:BackendApp --settings "PYTHONPATH=/home/site/wwwroot" "SCM_DO_BUILD_DURING_DEPLOYMENT=true" "ENABLE_ORYX_BUILD=true" "ORYX_APP_TYPE=webapps" "WEBSITES_PORT=8000" --output none
    
    Write-LogSuccess "App Service configured successfully"
}

# Deploy to Azure App Service with timeout handling
function Invoke-AppServiceDeployment {
    param([string]$TempDir)
    
    Write-LogInfo "Deploying to Azure App Service..."
    
    Push-Location $TempDir
    try {
        # Attempt deployment with timeout handling
        $deploymentOutput = ""
        $deploymentStatus = 0
        
        try {
            $deploymentOutput = az webapp deploy --resource-group $script:ResourceGroup --name $script:BackendApp --src-path "backend.zip" --type zip 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-LogSuccess "Deployment command completed successfully"
                return "success"
            } else {
                $deploymentStatus = $LASTEXITCODE
            }
        }
        catch {
            $deploymentOutput = $_.Exception.Message
            $deploymentStatus = 1
        }
        
        Write-LogWarning "Deployment command returned exit code: $deploymentStatus"
        
        # Check if it's likely a timeout or server-side issue
        if ($deploymentOutput -match "(timeout|timed out|request timeout|gateway timeout|502|503|504)") {
            Write-LogWarning "Deployment appears to have timed out on client side"
            Write-LogInfo "This doesn't necessarily mean the deployment failed on the server"
            Write-LogInfo "Will continue to check deployment status..."
            return "uncertain"
        }
        elseif ($deploymentOutput -match "(conflict|409|deployment.*progress|another deployment)") {
            Write-LogWarning "Another deployment may be in progress"
            Write-LogInfo "Will continue to check deployment status..."
            return "uncertain"
        }
        else {
            Write-LogError "Deployment command failed with actual error:"
            Write-Host ($deploymentOutput -split "`n" | Select-Object -First 10) -ForegroundColor Red
            return "failed"
        }
    }
    finally {
        Pop-Location
    }
}

# Wait for app to be ready and verify deployment
function Wait-AppReady {
    Write-LogInfo "Waiting for app to be ready..."
    
    $maxAttempts = 30
    $deploymentVerified = $false
    
    for ($i = 1; $i -le $maxAttempts; $i++) {
        try {
            $appState = az webapp show --resource-group $script:ResourceGroup --name $script:BackendApp --query "state" --output tsv 2>$null
            
            if ($appState -eq "Running") {
                Write-LogSuccess "App is running and ready"
                $deploymentVerified = $true
                break
            }
            elseif ($appState -eq "Stopped") {
                Write-LogWarning "App is stopped, attempting to start..."
                az webapp start --resource-group $script:ResourceGroup --name $script:BackendApp --output none 2>$null
            }
            
            Write-Host "   App state: $appState (attempt $i/$maxAttempts)"
            Start-Sleep -Seconds 5
        }
        catch {
            Write-Host "   Checking app state... (attempt $i/$maxAttempts)"
            Start-Sleep -Seconds 5
        }
    }
    
    if ($deploymentVerified) {
        return $true
    } else {
        Write-LogWarning "App state verification timed out after $($maxAttempts * 5) seconds"
        return $false
    }
}

# Perform health check
function Test-HealthEndpoint {
    param([string]$AppUrl)
    
    Write-LogInfo "Performing health check..."
    
    try {
        $response = Invoke-WebRequest -Uri "https://$AppUrl/health" -TimeoutSec 5 -ErrorAction Stop
        Write-LogSuccess "Health endpoint is responding"
    }
    catch {
        Write-LogWarning "Health endpoint not responding (application may be starting up)"
    }
}

# Cleanup deployment artifacts
function Remove-DeploymentArtifacts {
    param([string]$TempDir)
    
    Write-LogInfo "Cleaning up deployment artifacts..."
    
    $zipFile = Join-Path $TempDir "backend.zip"
    if (Test-Path $zipFile) {
        Remove-Item -Path $zipFile -Force
    }
    
    Write-LogSuccess "Cleanup completed"
}

# Display deployment summary
function Show-DeploymentSummary {
    param([string]$AppUrl, [string]$DeploymentStatus)
    
    Write-Host ""
    Write-Host "========================================================================="
    
    switch ($DeploymentStatus) {
        "success" {
            Write-LogSuccess "Deployment completed successfully!"
        }
        "uncertain" {
            Write-LogWarning "Deployment completed with uncertain status"
            Write-Host "   The deployment command timed out, but the app appears to be running."
            Write-Host "   This is common with large deployments and usually indicates success."
        }
        default {
            Write-LogSuccess "Deployment process completed!"
        }
    }
    
    Write-Host ""
    Write-Host "📊 Deployment Summary:"
    Write-Host "   Agent: $AgentName"
    Write-Host "   App Service: $script:BackendApp"
    Write-Host "   Resource Group: $script:ResourceGroup"
    Write-Host "   Environment: $script:AzdEnv"
    Write-Host "   App URL: https://$AppUrl"
    Write-Host "   Status: $DeploymentStatus"
    Write-Host ""
    Write-Host "🌐 Test your deployment at: https://$AppUrl"
    Write-Host "========================================================================="
}

# Main function
function Main {
    Write-Host "========================================================================="
    Write-Host "🚀 Azure App Service Deployment"
    Write-Host "========================================================================="
    
    # Check dependencies
    Test-Dependencies
    
    # Validate configuration
    Test-DeploymentConfig
    
    # Set deployment directory
    $tempDir = ".azure/$script:AzdEnv/backend"
    Write-LogInfo "Using deployment directory: $tempDir"
    
    try {
        # Prepare deployment
        New-DeploymentPackage -TempDir $tempDir
        New-DeploymentZip -TempDir $tempDir
        
        # Configure and deploy
        Set-AppServiceConfig
        
        # Attempt deployment with error handling
        $deploymentResult = Invoke-AppServiceDeployment -TempDir $tempDir
        
        if ($deploymentResult -eq "failed") {
            Write-LogError "Deployment failed with actual error"
            Write-LogError "Exiting due to deployment failure"
            exit 1
        }
        elseif ($deploymentResult -eq "uncertain") {
            Write-LogWarning "Deployment status uncertain due to timeout/server issues"
            Write-LogInfo "Continuing with verification steps..."
        }
        else {
            Write-LogSuccess "Deployment completed successfully"
        }
        
        # Wait for app and get URL
        Wait-AppReady
        $appUrl = az webapp show --resource-group $script:ResourceGroup --name $script:BackendApp --query "defaultHostName" --output tsv
        
        # Health check and cleanup
        Test-HealthEndpoint -AppUrl $appUrl
        Remove-DeploymentArtifacts -TempDir $tempDir
        
        # Show summary
        Show-DeploymentSummary -AppUrl $appUrl -DeploymentStatus $deploymentResult
        exit 0
    }
    catch {
        Write-LogError "Deployment failed: $($_.Exception.Message)"
        exit 1
    }
}

# Handle script interruption
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-LogError "Script interrupted by user"
}

# Run main function
Main
