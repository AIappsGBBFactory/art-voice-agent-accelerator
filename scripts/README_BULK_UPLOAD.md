# 🚀 Bulk Image Upload Script

This script automatically processes all product images from `utils/data/clothes/` and uploads them to Azure infrastructure (Blob Storage, Cosmos DB, and Azure AI Search).

## ✨ Features

- ✅ **Persistent UUID-Based IDs**: Generates stable unique IDs (e.g., `PROD-A1B2C3D4`) that persist across runs
- ✅ **Smart ID Extraction**: Reads existing ID from renamed files (e.g., `blue_jeans_ID_PROD-A1B2C3D4.jpg`)
- ✅ **UPSERT Behavior**: Updates existing records or inserts new ones (idempotent - safe to run multiple times)
- ✅ **File Renaming**: Adds ID marker after first processing for future identification
- ✅ **Metadata Extraction**: Automatically infers category, gender, colors, formality from filename
- ✅ **Complete Pipeline**: Uploads to Blob Storage + Creates/Updates Cosmos DB record + Indexes in Azure AI Search
- ✅ **Error Handling**: Continues processing even if individual images fail
- ✅ **Dry Run Mode**: Test without actually uploading anything

## 📋 Prerequisites

1. **Azure Resources** must be configured:
   ```bash
   export AZURE_STORAGE_ACCOUNT_NAME="your-storage-account"
   export BLOB_CONTAINER_NAME="clothesimages"
   export AZURE_AI_SEARCH_SERVICE_ENDPOINT="https://your-search.search.windows.net"
   export AZURE_AI_SEARCH_ADMIN_KEY="your-search-key"
   export AZURE_OPENAI_API_KEY="your-openai-key"
   export AZURE_OPENAI_ENDPOINT="https://your-openai.openai.azure.com"
   export AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large"
   export AZURE_COSMOSDB_MONGODB_NAME="rtvoiceagent"
   ```

2. **Azure Login** (for Managed Identity):
   ```bash
   az login
   ```

3. **Python Dependencies** installed:
   ```bash
   pip install -r requirements.txt
   ```

## 🎯 Usage

### Dry Run (Test Mode)
Test the script without actually uploading anything:
```bash
python scripts/bulk_image_upload.py --dry-run
```

### Process All Images
Upload all images from default folder (`utils/data/clothes/`):
```bash
python scripts/bulk_image_upload.py
```

### Process Specific Folder
Upload images from a custom folder:
```bash
python scripts/bulk_image_upload.py --folder utils/data/clothes/dresses
```

### Force Reprocess
Reprocess images even if they already exist:
```bash
python scripts/bulk_image_upload.py --force
```

### Limit Number of Images
Process only the first 10 images:
```bash
python scripts/bulk_image_upload.py --max 10
```

## 📁 File Naming Convention

The script uses intelligent filename parsing to extract metadata. For best results, name your image files descriptively:

### Good Examples:
- `mens_blue_jeans_casual.jpg` → Men's Jeans (Blue, Casual)
- `womens_red_dress_formal.png` → Women's Dress (Red, Formal)
- `athletic_black_shorts.jpg` → Athletic Shorts (Black)
- `winter_coat_grey.jpg` → Winter Coat (Grey)

### What Gets Extracted:
- **Gender**: men, women, male, female, guy, lady → Auto-detected
- **Category**: jeans, shirt, dress, jacket, shoes → Auto-detected
- **Colors**: black, white, blue, red, navy, grey → Auto-detected
- **Formality**: casual, formal, business, athletic → Auto-detected
- **Season**: winter, summer → Influences climate tags

## 🔄 How It Works

For each image, the script:

1. **Checks for Existing ID** in filename
   - If found (e.g., `blue_jeans_ID_PROD-A1B2C3D4.jpg`): Extract `PROD-A1B2C3D4`
   - If not found: Generate new UUID-based ID (e.g., `PROD-B7F3E8A2`)

2. **Extracts Metadata**
   - Parses filename to infer category, gender, colors, formality
   - Generates rich description for search

3. **Uploads to Azure Blob Storage**
   - Uses Managed Identity (DefaultAzureCredential)
   - Stores in `clothesimages/products/PROD-ID.jpg`

4. **Upserts Cosmos DB Record**
   - Creates new product document OR updates existing one (same `_id`)
   - Full product data with pricing, inventory, metadata

5. **Upserts in Azure AI Search**
   - Generates 3072-dimensional embedding using Azure OpenAI
   - Creates new index entry OR updates existing one (same `id`)
   - Includes filters (category, gender, formality, colors, etc.)

6. **Renames File with ID Marker** (first time only)
   - Example: `blue_jeans.jpg` → `blue_jeans_ID_PROD-A1B2C3D4.jpg`
   - Future runs will extract `PROD-A1B2C3D4` and update existing records

## 💡 ID Persistence Example

**First Run**:
```
blue_jeans.jpg → Generate PROD-A1B2C3D4 → Upload & Create Records → Rename to blue_jeans_ID_PROD-A1B2C3D4.jpg
```

**Second Run** (e.g., updated metadata):
```
blue_jeans_ID_PROD-A1B2C3D4.jpg → Extract PROD-A1B2C3D4 → Upload & Update Records → Keep same filename
```

This ensures:
- ✅ Same image always gets same ID
- ✅ Running multiple times updates existing records (no duplicates)
- ✅ Stable IDs across deployments and environments

## 📊 Output Example

```
================================================================================
🚀 BULK IMAGE UPLOAD SCRIPT
================================================================================
📁 Folder: /path/to/utils/data/clothes
🔧 Mode: PRODUCTION
🔄 Force reprocess: False
================================================================================

📊 Found 15 images to process

🔗 Initializing Azure clients...
   ✅ Cosmos DB client ready
   ✅ Azure AI Search client ready
   ✅ Azure OpenAI client ready

================================================================================
🔄 PROCESSING IMAGES
================================================================================

[1/15] Processing: mens_jeans_blue.jpg

📸 Processing: mens_jeans_blue.jpg
   � Generated new ID: PROD-A1B2C3D4
   �🆔 Product ID: PROD-A1B2C3D4 (new)
   📋 Category: Bottoms | Gender: Men | Formality: casual
   ☁️  Uploading to Azure Blob Storage...
   ✅ Uploaded to blob: products/PROD-A1B2C3D4.jpg
   💾 Creating Cosmos DB record...
   ✅ Created Cosmos DB record
   🔍 Indexing in Azure AI Search...
   🧮 Generating embedding...
   ✅ Indexed in Azure AI Search
   📝 Renamed to: mens_jeans_blue_ID_PROD-A1B2C3D4.jpg
   ✅ COMPLETED: PROD-A1B2C3D4

[2/15] Processing: womens_dress_red_ID_PROD-F7E8D2C1.jpg
   🔍 Found existing ID in filename: PROD-F7E8D2C1
   🆔 Product ID: PROD-F7E8D2C1 (existing)
   📋 Category: Tops | Gender: Women | Formality: formal
   ☁️  Uploading to Azure Blob Storage...
   ✅ Uploaded to blob: products/PROD-F7E8D2C1.jpg
   💾 Updating Cosmos DB record...
   ✅ Updated Cosmos DB record
   🔍 Updating in Azure AI Search...
   🧮 Generating embedding...
   ✅ Updated in Azure AI Search
   📌 Already has ID marker, keeping filename
   ✅ COMPLETED: PROD-F7E8D2C1

...

================================================================================
✅ PROCESSING COMPLETE
================================================================================
📊 Summary:
   Total images: 15
   ✅ Successfully processed: 12
   ⏭️  Skipped (already exists): 2
   ❌ Errors: 1
================================================================================
```

## 🛠️ Troubleshooting

### "No images found"
- Make sure images are in `utils/data/clothes/` folder
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`

### "Failed to upload to blob storage"
- Ensure you're logged in: `az login`
- Verify Managed Identity has "Storage Blob Data Contributor" role
- Check environment variable: `AZURE_STORAGE_ACCOUNT_NAME`

### "Failed to create Cosmos DB record"
- Check MongoDB connection string in `.env`
- Verify database name: `AZURE_COSMOSDB_MONGODB_NAME`

### "Failed to index in Azure AI Search"
- Verify `AZURE_AI_SEARCH_SERVICE_ENDPOINT` and `AZURE_AI_SEARCH_ADMIN_KEY`
- Check index exists: `clothing-index`
- Ensure embedding deployment is available

## 🎉 After Processing

Once images are processed, they will:

1. ✅ **Appear in search results** when users ask for products
2. ✅ **Display with SAS URLs** (~100ms load time vs 6-7 seconds with base64)
3. ✅ **Support filtering** by category, gender, formality, colors, climate
4. ✅ **Work in voice agent** - images show up instantly in frontend

## 📝 Notes

- **Idempotent**: Safe to run multiple times - skips already-processed images
- **Production-Ready**: Includes error handling and recovery
- **Scalable**: Can process hundreds of images in one run
- **Clean**: Renames files to track progress, avoiding confusion

## 🤝 Contributing

To add more metadata extraction logic, edit the `extract_metadata_from_image()` function in `scripts/bulk_image_upload.py`.

---

**Questions?** Check the main project README or contact the development team.
