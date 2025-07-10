#!/bin/bash

set -e

# ========================================================================
# 🚀 Simple Azure App Service Deployment
# ========================================================================

# Configuration
AGENT="${1:-RTAgent}"
MODE="${2:-both}"  # frontend, backend, or both

echo "🚀 Deploying $AGENT ($MODE) to App Service"

# Get AZD variables
RG=$(azd env get-value AZURE_RESOURCE_GROUP)
FRONTEND_APP=$(azd env get-value FRONTEND_APP_SERVICE_NAME)
BACKEND_APP=$(azd env get-value BACKEND_APP_SERVICE_NAME)

# Deploy Frontend
deploy_frontend() {
    echo "📱 Deploying frontend..."
    cd "rtagents/$AGENT/frontend"
    
    # Create deployment zip
    zip -r ../frontend.zip . -x node_modules/\* dist/\* .git/\*
    
    az webapp deployment source config-zip \
        --resource-group "$RG" \
        --name "$FRONTEND_APP" \
        --src ../frontend.zip
    
    rm ../frontend.zip
    cd - > /dev/null
}

# Deploy Backend  
deploy_backend() {
    echo "⚙️ Deploying backend..."
    
    # # Create requirements.txt if missing at agent backend level
    # if [ ! -f "rtagents/$AGENT/backend/requirements.txt" ]; then
    #     cp requirements.txt "rtagents/$AGENT/backend/requirements.txt"
    # fi
    
    # Create deployment zip from workspace root (like launch.json working directory)
    # Include entire workspace but exclude unnecessary files
    # Create a zip that preserves the folder structure but only includes the specific agent
    mkdir -p temp_deploy/rtagents/$AGENT/backend
    # Copy backend code excluding cache and artifacts
    rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
        --exclude='*.log' --exclude='.coverage' --exclude='htmlcov' \
        "rtagents/$AGENT/backend/" "temp_deploy/rtagents/$AGENT/backend/"
    
    # Copy src directory excluding cache
    rsync -av --exclude='__pycache__' --exclude='*.pyc' \
        src/ temp_deploy/src/
    
    # Copy requirements.txt
    cp requirements.txt temp_deploy/
    cd temp_deploy
    zip -r ../backend.zip . \
        -x "__pycache__" \
        -x "*/__pycache__/*" \
        -x "*.pyc" \
        -x ".DS_Store" \
        -x "*.log"
    cd ..
    
    # Clean up temp directory
    rm -rf temp_deploy
    # Deploy using remote build to avoid local OS/architecture mismatch
    az webapp deployment source config-zip \
        --resource-group "$RG" \
        --name "$BACKEND_APP" \
        --src backend.zip 
        
    # Set startup command to mirror launch.json structure
    # Working directory is workspace root, run uvicorn with module path
    az webapp config set \
        --resource-group "$RG" \
        --name "$BACKEND_APP" \
        --startup-file "python -m uvicorn rtagents.$AGENT.backend.main:app --host 0.0.0.0 --port 8000"
    
    # Set PYTHONPATH to workspace root (like launch.json env)
    az webapp config appsettings set \
        --resource-group "$RG" \
        --name "$BACKEND_APP" \
        --settings "PYTHONPATH=/home/site/wwwroot" \
        --output none
    
    rm backend.zip
}

# Main deployment
case "$MODE" in
    frontend) deploy_frontend ;;
    backend) deploy_backend ;;
    both) deploy_backend && deploy_frontend ;;
    *) echo "❌ Invalid mode. Use: frontend, backend, or both" && exit 1 ;;
esac

echo "✅ Deployment complete!"