#!/bin/bash
# Quick start script for bulk image upload

echo "🚀 Bulk Image Upload - Quick Start"
echo "=================================="
echo ""

# Check if images exist
if [ ! -d "utils/data/clothes" ]; then
    echo "❌ Error: utils/data/clothes directory not found"
    echo "   Please create this directory and add your product images"
    exit 1
fi

# Count images
IMAGE_COUNT=$(find utils/data/clothes -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \) | wc -l)
echo "📊 Found $IMAGE_COUNT images in utils/data/clothes"
echo ""

# Check Azure login
echo "🔐 Checking Azure login..."
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure"
    echo "   Please run: az login"
    exit 1
fi
echo "✅ Azure login verified"
echo ""

# Check environment variables
echo "🔍 Checking environment variables..."
MISSING_VARS=()

if [ -z "$AZURE_STORAGE_ACCOUNT_NAME" ]; then
    MISSING_VARS+=("AZURE_STORAGE_ACCOUNT_NAME")
fi

if [ -z "$AZURE_AI_SEARCH_SERVICE_ENDPOINT" ]; then
    MISSING_VARS+=("AZURE_AI_SEARCH_SERVICE_ENDPOINT")
fi

if [ -z "$AZURE_OPENAI_API_KEY" ]; then
    MISSING_VARS+=("AZURE_OPENAI_API_KEY")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "❌ Missing required environment variables:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "💡 Tip: Check your .env file or run:"
    echo "   source .env"
    exit 1
fi

echo "✅ All environment variables configured"
echo ""

# Offer dry run first
echo "Would you like to:"
echo "  1. Dry run (test without uploading)"
echo "  2. Process all images"
echo "  3. Process first 5 images (test)"
echo ""
read -p "Enter choice (1-3): " choice

case $choice in
    1)
        echo ""
        echo "🔄 Running dry run..."
        python scripts/bulk_image_upload.py --dry-run
        ;;
    2)
        echo ""
        echo "⚠️  This will upload all $IMAGE_COUNT images to Azure"
        read -p "Continue? (y/n): " confirm
        if [ "$confirm" = "y" ]; then
            python scripts/bulk_image_upload.py
        else
            echo "Cancelled"
        fi
        ;;
    3)
        echo ""
        echo "🔄 Processing first 5 images..."
        python scripts/bulk_image_upload.py --max 5
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "✅ Done!"
