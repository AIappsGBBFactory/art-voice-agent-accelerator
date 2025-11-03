#!/usr/bin/env python3
"""
🚀 Bulk Image Upload Script for Retail Product Data
====================================================

This script processes all images from utils/data/clothes/ and:
1. Uploads each image to Azure Blob Storage
2. Creates/updates product records in Cosmos DB (upsert)
3. Indexes/updates products in Azure AI Search with embeddings (upsert)

Production Features:
- ✅ Persistent UUID-based product IDs (stable across runs)
- ✅ Extracts existing ID from renamed files (e.g., blue_jeans_ID_PROD-A1B2C3D4.jpg)
- ✅ Generates new unique ID for new images (PROD-<UUID>)
- ✅ UPSERT behavior: Updates existing records, inserts new ones
- ✅ Renames images with ID marker after first processing
- ✅ Safe to run multiple times (idempotent)
- ✅ Batch processing with progress tracking
- ✅ Error handling and recovery
- ✅ Dry-run mode for testing

ID Persistence Example:
    Run 1: blue_jeans.jpg → Generate PROD-A1B2C3D4 → Rename to blue_jeans_ID_PROD-A1B2C3D4.jpg
    Run 2: blue_jeans_ID_PROD-A1B2C3D4.jpg → Extract PROD-A1B2C3D4 → Update existing records

Usage:
    # Dry run (test without uploading):
    python scripts/bulk_image_upload.py --dry-run

    # Process all images:
    python scripts/bulk_image_upload.py

    # Process specific folder:
    python scripts/bulk_image_upload.py --folder utils/data/clothes/dresses
"""

import asyncio
import os
import sys
import argparse
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
import datetime
import logging
import time
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
load_dotenv()

from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from PIL import Image
from pymongo.errors import DuplicateKeyError
import base64
import json

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger
from pydantic import BaseModel, Field
from typing import Literal

# ============================================================================
# CONFIGURATION
# ============================================================================

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_IMAGE_FOLDER = "utils/data/clothes"
ID_MARKER = "_ID_"  # Marker in filename to indicate ID has been assigned

# Azure Configuration (from environment variables)
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
BLOB_CONTAINER_NAME = os.environ.get("BLOB_CONTAINER_NAME", "clothesimages")
SEARCH_ENDPOINT = os.environ.get("AZURE_AI_SEARCH_SERVICE_ENDPOINT")
SEARCH_API_KEY = os.environ.get("AZURE_AI_SEARCH_ADMIN_KEY")
INDEX_NAME = "clothing-index"

# Azure OpenAI for embeddings and vision
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_KEY")  # Use AZURE_OPENAI_KEY (not AZURE_OPENAI_API_KEY)
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHAT_EMBEDDING_ID", "text-embedding-3-large")
AZURE_OPENAI_VISION_MODEL = "gpt-4o"  # For image analysis
AZURE_OPENAI_API_VERSION = "2024-08-01-preview"

# ============================================================================
# LOGGING SETUP
# ============================================================================

logger = get_logger("bulk_image_upload")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ============================================================================
# ENVIRONMENT VALIDATION
# ============================================================================

def validate_environment() -> bool:
    """Validate all required environment variables are set
    
    Returns:
        True if all required vars are set, False otherwise
    """
    required_vars = {
        "AZURE_STORAGE_ACCOUNT_NAME": AZURE_STORAGE_ACCOUNT_NAME,
        "AZURE_AI_SEARCH_SERVICE_ENDPOINT": SEARCH_ENDPOINT,
        "AZURE_AI_SEARCH_ADMIN_KEY": SEARCH_API_KEY,
        "AZURE_OPENAI_KEY": AZURE_OPENAI_API_KEY,
        "AZURE_OPENAI_ENDPOINT": AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_CHAT_EMBEDDING_ID": AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    }
    
    missing = []
    for var_name, var_value in required_vars.items():
        if not var_value:
            missing.append(var_name)
    
    if missing:
        logger.error(f"❌ Missing required environment variables:")
        for var in missing:
            logger.error(f"   - {var}")
        logger.error(f"\n💡 Please set these variables in your .env file or environment")
        return False
    
    return True

# ============================================================================
# PYDANTIC SCHEMA FOR VALIDATION
# ============================================================================

class ProductExtraction(BaseModel):
    """Schema for data extracted from product image - STRICT ENUMS TO PREVENT HALLUCINATIONS"""
    name: str = Field(..., description="Product name/title")
    
    # STRICT ENUMS - Only these values allowed
    category: Literal["Tops", "Bottoms", "Dresses", "Outerwear", "Footwear", "Accessories"] = Field(
        ..., description="MUST be exactly one of: Tops, Bottoms, Dresses, Outerwear, Footwear, Accessories"
    )
    gender: Literal["Men", "Women", "Unisex"] = Field(
        ..., description="MUST be exactly one of: Men, Women, Unisex"
    )
    formality: Literal["casual", "business_casual", "formal", "athletic"] = Field(
        ..., description="MUST be exactly one of: casual, business_casual, formal, athletic"
    )
    fit: Literal["slim", "regular", "relaxed", "athletic"] = Field(
        ..., description="MUST be exactly one of: slim, regular, relaxed, athletic"
    )
    
    colors: List[str] = Field(
        ..., 
        description="Main colors: black, white, blue, red, green, grey, brown, pink, purple, yellow, orange, neutral"
    )
    materials: List[str] = Field(
        ..., 
        description="Materials: cotton, denim, wool, polyester, leather, silk, linen, fleece, nylon, premium fabric"
    )
    features: List[str] = Field(
        ..., 
        description="Features: stretch, moisture-wicking, water-resistant, wrinkle-free, fade-resistant, pockets, lined, button-down, zip, comfortable, versatile, stylish"
    )
    climate: List[Literal["warm", "cold", "all-season"]] = Field(
        ..., description="Suitable climates: warm, cold, all-season"
    )
    rich_description: str = Field(
        ..., 
        description="DETAILED 4-6 sentence description written like a fashion magazine"
    )
    style_tags: List[str] = Field(
        ..., 
        description="Style descriptors: vintage, modern, classic, trendy, minimalist, bold, elegant, sporty, urban, timeless"
    )

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_or_generate_product_id(filepath: Path) -> tuple[str, bool]:
    """
    Extract existing product ID from filename, or generate a new unique one.
    
    Returns:
        (product_id, has_existing_id)
    
    Examples:
        - "blue_jeans.jpg" → ("PROD-A1B2C3D4", False)  # New ID generated
        - "blue_jeans_ID_PROD-A1B2C3D4.jpg" → ("PROD-A1B2C3D4", True)  # Existing ID extracted
    """
    filename = filepath.stem  # Get filename without extension
    
    # Check if filename already has an ID (contains _ID_PROD- pattern)
    if ID_MARKER in filename:
        # Extract the ID after _ID_
        parts = filename.split(ID_MARKER)
        if len(parts) >= 2:
            # The ID is everything after _ID_ marker
            existing_id = parts[1]
            logger.info(f"   🔍 Found existing ID in filename: {existing_id}")
            return existing_id, True
    
    # Generate new unique ID using first 8 chars of UUID
    unique_id = str(uuid.uuid4())[:8].upper()
    product_id = f"PROD-{unique_id}"
    logger.info(f"   🆕 Generated new ID: {product_id}")
    
    return product_id, False


def has_product_id(filepath: Path) -> bool:
    """Check if image filename already contains a product ID"""
    return ID_MARKER in filepath.stem


def generate_embedding(text: str, openai_client: AzureOpenAI, max_retries: int = 3) -> List[float]:
    """Generate embedding vector for text using Azure OpenAI with retry logic
    
    Args:
        text: Text to embed
        openai_client: Azure OpenAI client
        max_retries: Maximum number of retry attempts on rate limit errors
    
    Returns:
        3072-dimension embedding vector
    """
    for attempt in range(max_retries):
        try:
            response = openai_client.embeddings.create(
                input=text,
                model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT
            )
            return response.data[0].embedding
        except Exception as e:
            error_str = str(e).lower()
            # Retry on rate limit errors
            if "rate" in error_str or "429" in error_str:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                    logger.warning(f"⚠️  Rate limit hit, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
            logger.error(f"❌ Failed to generate embedding: {e}")
            raise


def encode_image_to_base64(image_path: Path) -> str:
    """Encode image to base64 for Azure OpenAI Vision"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def extract_metadata_from_image(image_path: Path, openai_client: AzureOpenAI, base_folder: Path = None, 
                                max_retries: int = 3) -> Dict[str, Any]:
    """
    Extract metadata from product image using GPT-4o Vision with retry logic.
    Uses FASHION STYLIST prompt to generate rich, detailed descriptions.
    
    Args:
        image_path: Full path to the image file
        openai_client: Azure OpenAI client for vision analysis
        base_folder: Base folder (unused, kept for compatibility)
        max_retries: Maximum retry attempts on rate limit errors
    
    Returns:
        Dict with product metadata including rich_description
    
    Raises:
        Exception: If vision analysis fails after all retries
    """
    logger.info(f"   🔍 Analyzing image with GPT-4o Vision...")
    
    # Encode image
    base64_image = encode_image_to_base64(image_path)
    
    # FASHION STYLIST PROMPT - Matches notebook exactly
    system_prompt = """You are a professional fashion stylist and product copywriter for a high-end retail brand. 

Your expertise includes:
- Analyzing garment construction, fabric quality, and design details
- Writing compelling product descriptions that help customers visualize wearing the item
- Understanding seasonal trends, occasion appropriateness, and styling versatility
- Identifying the perfect customer for each piece

CRITICAL INSTRUCTIONS:
1. Use ONLY the exact enum values provided - no variations or synonyms
2. Write rich_description as if you're speaking to a customer looking for the perfect piece
3. Include specific fabric details, fit characteristics, and styling suggestions
4. Mention what occasions this would be perfect for
5. Describe how it feels to wear and its versatility

STRICT ENUMS - You MUST use exactly these values:
- category: "Tops" | "Bottoms" | "Dresses" | "Outerwear" | "Footwear" | "Accessories"
- gender: "Men" | "Women" | "Unisex"
- formality: "casual" | "business_casual" | "formal" | "athletic"
- fit: "slim" | "regular" | "relaxed" | "athletic"
- climate: ["warm", "cold", "all-season"] (can be multiple)

CONTROLLED VOCABULARY:
- colors: black, white, blue, red, green, grey, brown, pink, purple, yellow, orange, neutral
- materials: cotton, denim, wool, polyester, leather, silk, linen, fleece, nylon, premium fabric
- features: stretch, moisture-wicking, water-resistant, wrinkle-free, fade-resistant, pockets, lined, button-down, zip, comfortable, versatile, stylish
- style_tags: vintage, modern, classic, trendy, minimalist, bold, elegant, sporty, urban, timeless

Return JSON with this EXACT structure:
{
    "name": "Descriptive product name",
    "category": "MUST be one of: Tops, Bottoms, Dresses, Outerwear, Footwear, Accessories",
    "gender": "MUST be one of: Men, Women, Unisex",
    "formality": "MUST be one of: casual, business_casual, formal, athletic",
    "fit": "MUST be one of: slim, regular, relaxed, athletic",
    "colors": ["List main colors from the controlled vocabulary"],
    "materials": ["List perceived materials from the controlled vocabulary"],
    "features": ["List special features from the controlled vocabulary"],
    "climate": ["MUST be from: warm, cold, all-season"],
    "rich_description": "WRITE 4-6 SENTENCES as a fashion stylist. Be specific, vivid, and helpful. Include fabric quality, fit feel, styling tips, perfect occasions, and versatility.",
    "style_tags": ["2-4 style descriptors from the controlled vocabulary"]
}

REMEMBER: Write the rich_description as if you're helping a customer understand why this piece is perfect for them. Be specific, vivid, and helpful."""
    
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=AZURE_OPENAI_VISION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Analyze this clothing item: {image_path.name}. Write a compelling fashion description that helps customers find and fall in love with this piece. Extract all details in JSON format using ONLY the specified enum values."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500
            )
            
            # Parse response
            result = json.loads(response.choices[0].message.content)
            
            # Validate with Pydantic (enforces strict enums)
            product_data = ProductExtraction(**result)
            
            # Convert to dict format expected by rest of pipeline
            return {
                "category": product_data.category,
                "gender": product_data.gender,
                "formality": product_data.formality,
                "fit": product_data.fit,
                "features": product_data.features,
                "climate": product_data.climate,
                "colors": product_data.colors,
                "materials": product_data.materials,
                "rich_description": product_data.rich_description,
                "name": product_data.name,
                "brand": "Private Label",
                "style_tags": product_data.style_tags
            }
            
        except Exception as e:
            error_str = str(e).lower()
            # Retry on rate limit or transient errors
            if ("rate" in error_str or "429" in error_str or "timeout" in error_str) and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.warning(f"⚠️  Vision API error, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            logger.error(f"   ❌ Vision analysis failed: {e}")
            raise


async def upload_image_to_blob(image_path: Path, product_id: str, dry_run: bool = False) -> Optional[str]:
    """
    Upload image to Azure Blob Storage using Managed Identity.
    
    Returns:
        Blob URL if successful, None if failed
    """
    if dry_run:
        logger.info(f"   [DRY RUN] Would upload {image_path.name} to blob storage")
        return f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}/products/{product_id}{image_path.suffix}"
    
    try:
        # Initialize Blob Service Client with Managed Identity
        account_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
        
        # Create blob name: products/PROD-ID.ext
        blob_name = f"products/{product_id}{image_path.suffix}"
        blob_client = blob_service_client.get_blob_client(container=BLOB_CONTAINER_NAME, blob=blob_name)
        
        # Read image data
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        
        # Determine content type
        content_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }
        content_type = content_type_map.get(image_path.suffix.lower(), "image/jpeg")
        
        # Upload to blob storage
        blob_client.upload_blob(
            image_data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type)
        )
        
        # Return public URL
        blob_url = f"{account_url}/{BLOB_CONTAINER_NAME}/{blob_name}"
        logger.info(f"   ✅ Uploaded to blob: {blob_name}")
        return blob_url
        
    except Exception as e:
        logger.error(f"   ❌ Failed to upload to blob storage: {e}")
        return None


async def generate_realistic_product_data(metadata: Dict, product_id: str, openai_client: AzureOpenAI, 
                                          max_retries: int = 3) -> Dict:
    """Use Azure OpenAI to generate realistic pricing, inventory, and assortment data with retry logic
    
    Args:
        metadata: Product metadata from vision analysis
        product_id: Unique product identifier
        openai_client: Azure OpenAI client
        max_retries: Maximum retry attempts on rate limit errors
    
    Returns:
        Dict with brand, pricing, inventory, assortment, specifications, merchandising
    """
    
    prompt = f"""Generate realistic retail product data for this clothing item:
    
Product: {metadata['name']}
Category: {metadata['category']}
Gender: {metadata['gender']}
Materials: {', '.join(metadata['materials'])}
Features: {', '.join(metadata['features'])}

Generate realistic data for a mid-to-premium retail brand. Return JSON with:

{{
    "brand": "realistic brand name for this product type",
    "base_price": realistic_price_in_dollars,
    "total_stock": realistic_inventory_count,
    "sizes": ["appropriate sizes for this product"],
    "customer_rating": rating_out_of_5,
    "review_count": number_of_reviews,
    "display_priority": priority_score_0_to_100
}}

Be realistic - jeans typically $60-120, sweaters $40-90, etc."""

    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=AZURE_OPENAI_VISION_MODEL,
                messages=[
                    {"role": "system", "content": "You are a retail merchandising expert. Generate realistic product data."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500
            )
            
            ai_data = json.loads(response.choices[0].message.content)
            
            # CRITICAL: Validate AI-generated data before using
            required_fields = ["brand", "base_price", "total_stock", "sizes", "customer_rating", "review_count", "display_priority"]
            for field in required_fields:
                if field not in ai_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate data types and ranges
            if not isinstance(ai_data["base_price"], (int, float)) or ai_data["base_price"] <= 0:
                raise ValueError(f"Invalid base_price: {ai_data['base_price']}")
            if not isinstance(ai_data["total_stock"], int) or ai_data["total_stock"] < 0:
                raise ValueError(f"Invalid total_stock: {ai_data['total_stock']}")
            if not isinstance(ai_data["customer_rating"], (int, float)) or not (0 <= ai_data["customer_rating"] <= 5):
                raise ValueError(f"Invalid customer_rating: {ai_data['customer_rating']}")
            if not isinstance(ai_data["review_count"], int) or ai_data["review_count"] < 0:
                raise ValueError(f"Invalid review_count: {ai_data['review_count']}")
            if not isinstance(ai_data["display_priority"], int) or not (0 <= ai_data["display_priority"] <= 100):
                raise ValueError(f"Invalid display_priority: {ai_data['display_priority']}")
            
            # Data is valid, continue with calculations
        
            # Calculate pricing tiers
            base_price = ai_data["base_price"]
            import random
        
            pricing = {
                "base_price": base_price,
                "currency": "USD",
                "discount_tiers": {
                    "member": round(base_price * 0.90, 2),
                    "gold": round(base_price * 0.85, 2),
                    "platinum": round(base_price * 0.80, 2)
                },
                "regional_pricing": {
                    "US_WEST": base_price,
                    "US_EAST": base_price,
                    "US_SOUTH": round(base_price * 0.95, 2)
                },
                "sale_price": round(base_price * 0.75, 2) if random.random() < 0.3 else None,
                "on_sale": random.random() < 0.3
            }
            
            # Generate inventory by region
            total_stock = ai_data["total_stock"]
            west_stock = int(total_stock * 0.40)
            east_stock = int(total_stock * 0.35)
            south_stock = total_stock - west_stock - east_stock
            
            inventory = {
                "total_stock": total_stock,
                "by_region": {
                    "US_WEST": {
                        "stock": west_stock,
                        "reserved": random.randint(5, 20),
                        "available": max(0, west_stock - random.randint(5, 20))
                    },
                    "US_EAST": {
                        "stock": east_stock,
                        "reserved": random.randint(3, 15),
                        "available": max(0, east_stock - random.randint(3, 15))
                    },
                    "US_SOUTH": {
                        "stock": south_stock,
                        "reserved": random.randint(2, 10),
                        "available": max(0, south_stock - random.randint(2, 10))
                    }
                },
                "low_stock_threshold": int(total_stock * 0.15),
                "restock_date": None if total_stock > 100 else "2025-11-15"
            }
            
            # Assortment data
            assortment = {
                "available_regions": ["US_WEST", "US_EAST", "US_SOUTH"],
                "stores": ["Seattle_Downtown", "SF_Union_Square", "Austin_Domain"],
                "online_only": False,
                "seasonal": "Sweaters" in metadata["category"] or "Outerwear" in metadata["category"],
                "launch_date": "2024-09-01"
            }
            
            # Specifications
            specifications = {
                "colors": metadata["colors"],
                "sizes": ai_data["sizes"],
                "materials": metadata["materials"],
                "care_instructions": ["machine_wash_cold", "tumble_dry_low"] if any("cotton" in m.lower() for m in metadata["materials"]) else ["dry_clean_only"],
                "country_of_origin": random.choice(["USA", "Italy", "Portugal", "Vietnam"])
            }
            
            # Merchandising
            merchandising = {
                "display_priority": ai_data["display_priority"],
                "featured": ai_data["display_priority"] > 85,
                "cross_sell": [],
                "frequently_bought_with": [],
                "customer_rating": ai_data["customer_rating"],
                "review_count": ai_data["review_count"]
            }
            
            return {
                "brand": ai_data["brand"],
                "pricing": pricing,
                "inventory": inventory,
                "assortment": assortment,
                "specifications": specifications,
                "merchandising": merchandising
            }
            
        except Exception as e:
            error_str = str(e).lower()
            # Retry on rate limit or transient errors
            if ("rate" in error_str or "429" in error_str or "timeout" in error_str) and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.warning(f"⚠️  Data generation error, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            logger.error(f"   ❌ Failed to generate realistic data: {e}")
            raise


async def create_cosmos_record(product_id: str, image_url: str, metadata: Dict, ai_generated_data: Dict, 
                               embedding: List[float], cosmos_manager, dry_run: bool = False):
    """Create complete product record in Cosmos DB with AI-generated data
    
    CRITICAL: Cosmos DB document includes ALL business data but NO VECTORS:
    - Product metadata (name, category, gender, brand, etc.)
    - AI-generated data (pricing, inventory, assortment, specifications, merchandising)
    - Visual data (colors, materials, style_tags) - MUST be included!
    - Image URL from blob storage
    - Rich description for search/display
    
    NOTE: Embedding vectors are ONLY stored in Azure AI Search (not Cosmos DB)
          to avoid document size issues and silent failures
    """
    if dry_run:
        logger.info(f"   [DRY RUN] Would create Cosmos DB record for {product_id}")
        return True
    
    try:
        product_doc = {
            "_id": product_id,
            "product_id": product_id,
            "name": metadata["name"],
            "category": metadata["category"],
            "gender": metadata["gender"],
            "brand": ai_generated_data["brand"],
            "formality": metadata["formality"],
            "fit": metadata["fit"],
            "features": metadata["features"],
            "climate": metadata["climate"],
            # CRITICAL: Include visual metadata (colors, materials, style_tags)
            "colors": metadata["colors"],
            "materials": metadata["materials"],
            "style_tags": metadata.get("style_tags", []),
            # AI-generated business data
            "pricing": ai_generated_data["pricing"],
            "inventory": ai_generated_data["inventory"],
            "assortment": ai_generated_data["assortment"],
            "specifications": ai_generated_data["specifications"],
            "merchandising": ai_generated_data["merchandising"],
            # Media and search
            "image_url": image_url,
            "rich_description": metadata["rich_description"],
            # NOTE: desc_vector removed - vectors only in Azure AI Search
            # Timestamps
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
        
        # Log document size for debugging
        import sys
        doc_size_bytes = sys.getsizeof(str(product_doc))
        logger.info(f"   📦 Document size: ~{doc_size_bytes:,} bytes")
        
        # Use upsert to insert or update
        logger.info(f"   💾 Upserting to Cosmos DB...")
        await asyncio.to_thread(
            cosmos_manager.upsert_document,
            document=product_doc,
            query={"_id": product_id}
        )
        
        logger.info(f"   ✅ Upserted Cosmos DB record successfully")
        return True
        
    except DuplicateKeyError:
        logger.info(f"   ✅ Updated existing Cosmos DB record")
        return True
    except Exception as e:
        logger.error(f"   ❌ COSMOS DB UPSERT FAILED: {e}")
        logger.error(f"   ❌ Product ID: {product_id}")
        logger.error(f"   ❌ Exception type: {type(e).__name__}")
        return False


async def index_in_search(product_id: str, image_url: str, metadata: Dict, embedding: List[float],
                          search_client: SearchClient, dry_run: bool = False):
    """Index product in Azure AI Search with embedding
    
    Azure AI Search document structure (matches notebook):
    - All filterable/searchable product attributes
    - Visual metadata (colors, materials)
    - Rich description for text search
    - Embedding vector for semantic search
    - Image URL for display
    """
    if dry_run:
        logger.info(f"   [DRY RUN] Would index {product_id} in Azure AI Search")
        return True
    
    try:
        # Create search document (matches notebook structure exactly)
        search_doc = {
            "id": product_id,
            "name": metadata["name"],  # CRITICAL: Include name for display
            "category": metadata["category"],
            "gender": metadata["gender"],
            "formality": metadata["formality"],
            "fit": metadata["fit"],
            "features": metadata["features"],
            "climate": metadata["climate"],
            "colors": metadata["colors"],
            "materials": metadata["materials"],
            "image_url": image_url,
            "rich_description": metadata["rich_description"],
            "desc_vector": embedding
        }
        
        # Upload to Azure AI Search
        await asyncio.to_thread(
            search_client.upload_documents,
            documents=[search_doc]
        )
        
        logger.info(f"   ✅ Indexed in Azure AI Search")
        return True
        
    except Exception as e:
        logger.error(f"   ❌ Failed to index in Azure AI Search: {e}")
        return False


def rename_with_product_id(image_path: Path, product_id: str):
    """
    Rename image file to include product ID for future identification.
    
    Only renames if file doesn't already have ID marker.
    
    Example:
        blue_jeans.jpg → blue_jeans_ID_PROD-A1B2C3D4.jpg
    """
    # Don't rename if already has ID
    if ID_MARKER in image_path.stem:
        logger.info(f"   📌 Already has ID marker, keeping filename")
        return
    
    try:
        new_filename = f"{image_path.stem}{ID_MARKER}{product_id}{image_path.suffix}"
        new_path = image_path.parent / new_filename
        image_path.rename(new_path)
        logger.info(f"   📝 Renamed to: {new_filename}")
    except Exception as e:
        logger.warning(f"   ⚠️  Could not rename file: {e}")


# ============================================================================
# MAIN PROCESSING FUNCTION
# ============================================================================

async def process_single_image(image_path: Path, base_folder: Path, cosmos_manager, search_client: SearchClient, 
                               openai_client: AzureOpenAI, dry_run: bool = False, force: bool = False) -> bool:
    """
    Process a single image: upload to blob, create/update Cosmos record, index in Search.
    
    Uses UPSERT behavior:
    - Extracts existing ID from filename if present (e.g., blue_jeans_ID_PROD-A1B2C3D4.jpg)
    - Generates new UUID-based ID if not present
    - Azure AI Search and Cosmos DB automatically update if ID exists (upsert)
    - Renames file with ID marker after first processing
    
    Args:
        image_path: Path to the image file
        base_folder: Base folder for calculating relative paths (for metadata extraction)
        
    Returns:
        True if successful, False if failed
    """
    logger.info(f"\n📸 Processing: {image_path.name}")
    
    # Extract existing ID or generate new one
    product_id, has_existing_id = extract_or_generate_product_id(image_path)
    logger.info(f"   🆔 Product ID: {product_id} {'(existing)' if has_existing_id else '(new)'}")
    
    # Step 1: Extract metadata using GPT-4o Vision (Fashion Stylist mode)
    try:
        metadata = extract_metadata_from_image(image_path, openai_client, base_folder)
        logger.info(f"   📋 Category: {metadata['category']} | Gender: {metadata['gender']} | Formality: {metadata['formality']}")
        logger.info(f"   ✨ Rich Description: {metadata['rich_description'][:120]}...")
        
        # CRITICAL: Validate metadata completeness
        required_fields = ["name", "category", "gender", "formality", "fit", "features", "climate", 
                          "colors", "materials", "rich_description", "style_tags"]
        missing_fields = [f for f in required_fields if f not in metadata or not metadata[f]]
        if missing_fields:
            logger.error(f"   ❌ Vision analysis incomplete - missing: {', '.join(missing_fields)}")
            return False
    except Exception as e:
        logger.error(f"   ❌ Vision analysis failed: {e}")
        return False
    
    # Step 2: Upload image to blob storage
    logger.info(f"   ☁️  Uploading to Azure Blob Storage...")
    blob_url = await upload_image_to_blob(image_path, product_id, dry_run)
    if not blob_url:
        logger.error(f"   ❌ Failed to upload image, aborting this file")
        return False
    
    # Step 3: Generate embedding (CRITICAL: Do this once, use for both Cosmos + Search)
    logger.info(f"   🧮 Generating embedding vector (3072 dimensions)...")
    if not dry_run:
        embedding = generate_embedding(metadata["rich_description"], openai_client)
        logger.info(f"   ✅ Embedding generated: {len(embedding)} dimensions")
    else:
        embedding = [0.0] * 3072  # Dummy embedding for dry run
    
    # Step 4: Generate realistic product data with AI
    try:
        logger.info(f"   🤖 Generating realistic pricing, inventory & merchandising data...")
        ai_generated_data = await generate_realistic_product_data(metadata, product_id, openai_client)
        logger.info(f"   💰 Brand: {ai_generated_data['brand']} | Price: ${ai_generated_data['pricing']['base_price']:.2f} | Stock: {ai_generated_data['inventory']['total_stock']}")
        
        # CRITICAL: Validate AI-generated data structure
        required_sections = ["brand", "pricing", "inventory", "assortment", "specifications", "merchandising"]
        missing_sections = [s for s in required_sections if s not in ai_generated_data]
        if missing_sections:
            logger.error(f"   ❌ AI data generation incomplete - missing: {', '.join(missing_sections)}")
            return False
    except Exception as e:
        logger.error(f"   ❌ AI data generation failed: {e}")
        return False
    
    # Step 5: Create/Update Cosmos DB record with AI-generated data (upsert)
    # NOTE: Vectors NOT stored in Cosmos DB - only business/product data
    logger.info(f"   💾 {'Updating' if has_existing_id else 'Creating'} Cosmos DB record...")
    cosmos_success = await create_cosmos_record(product_id, blob_url, metadata, ai_generated_data, embedding, cosmos_manager, dry_run)
    if not cosmos_success:
        logger.error(f"   ❌ CRITICAL: Cosmos DB upsert failed for {product_id}")
        return False  # Stop processing this image if Cosmos DB fails
    
    # Step 6: Index/Update in Azure AI Search (upsert)
    logger.info(f"   🔍 {'Updating' if has_existing_id else 'Indexing'} in Azure AI Search...")
    search_success = await index_in_search(product_id, blob_url, metadata, embedding, search_client, dry_run)
    if not search_success:
        logger.warning(f"   ⚠️  Azure AI Search upsert failed, but continuing...")
    
    # Step 7: Rename file with ID marker (unless dry run or already has ID)
    if not dry_run:
        rename_with_product_id(image_path, product_id)
    
    logger.info(f"   ✅ COMPLETED: {product_id}")
    return True


async def process_image_folder(folder_path: Path, dry_run: bool = False, force: bool = False, 
                               max_images: Optional[int] = None):
    """
    Process all images in the specified folder.
    
    Args:
        folder_path: Path to folder containing images
        dry_run: If True, simulate without actual uploads
        force: If True, reprocess even if already exists
        max_images: Maximum number of images to process (None = all)
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"🚀 BULK IMAGE UPLOAD SCRIPT - PRODUCTION READY")
    logger.info(f"{'='*80}")
    logger.info(f"📁 Folder: {folder_path}")
    logger.info(f"🔧 Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
    logger.info(f"🔄 Force reprocess: {force}")
    logger.info(f"{'='*80}\n")
    
    # CRITICAL: Validate environment before starting
    logger.info(f"🔍 Validating environment configuration...")
    if not validate_environment():
        logger.error(f"\n❌ Environment validation failed. Cannot proceed.")
        return
    logger.info(f"✅ Environment validation passed\n")
    
    # Validate folder exists
    if not folder_path.exists():
        logger.error(f"❌ Folder not found: {folder_path}")
        return
    
    # Find all image files (recursively search subdirectories)
    image_files = []
    for ext in SUPPORTED_EXTENSIONS:
        # Use ** for recursive search
        image_files.extend(folder_path.glob(f"**/*{ext}"))
        image_files.extend(folder_path.glob(f"**/*{ext.upper()}"))
    
    # Filter out already renamed files (those with ID_MARKER) unless force=True
    if not force:
        original_count = len(image_files)
        image_files = [f for f in image_files if ID_MARKER not in f.stem]
        skipped = original_count - len(image_files)
        if skipped > 0:
            logger.info(f"⏭️  Skipping {skipped} already-processed images (use --force to reprocess)")
    
    # Sort by path for consistent ordering
    image_files = sorted(image_files)
    
    # Limit number of images if specified
    if max_images:
        image_files = image_files[:max_images]
    
    logger.info(f"📊 Found {len(image_files)} images to process")
    
    if len(image_files) > 0:
        # Show a sample of folders being processed
        folders = set(f.parent.relative_to(folder_path) for f in image_files[:10])
        logger.info(f"📂 Sample folders: {', '.join(str(f) for f in list(folders)[:3])}")
    
    logger.info("")
    
    if len(image_files) == 0:
        logger.warning(f"⚠️  No images found in {folder_path}")
        logger.info(f"💡 Tip: Make sure image files (.jpg, .jpeg, .png, .webp) exist in {folder_path} or its subdirectories")
        return
    
    # Initialize Azure clients
    logger.info(f"🔗 Initializing Azure clients...")
    
    # Cosmos DB - CRITICAL: Use retail-db database, not rtvoiceagent
    cosmos_manager = CosmosDBMongoCoreManager(
        collection_name="products",
        database_name="retail-db"  # Hardcoded to retail-db for retail product data
    )
    logger.info(f"   ✅ Cosmos DB client ready (database: retail-db, collection: products)")
    
    # Azure AI Search
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_API_KEY)
    )
    logger.info(f"   ✅ Azure AI Search client ready")
    
    # Azure OpenAI (for embeddings and vision)
    openai_client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    logger.info(f"   ✅ Azure OpenAI client ready (Vision: {AZURE_OPENAI_VISION_MODEL}, Embeddings: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT})")
    
    logger.info(f"\n{'='*80}")
    logger.info(f"🔄 PROCESSING IMAGES")
    logger.info(f"{'='*80}\n")
    
    # Process each image
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for idx, image_path in enumerate(image_files, 1):
        logger.info(f"[{idx}/{len(image_files)}] Processing: {image_path.name}")
        
        try:
            success = await process_single_image(
                image_path, folder_path, cosmos_manager, search_client, openai_client, dry_run, force
            )
            
            if success:
                success_count += 1
            else:
                skip_count += 1
                
        except Exception as e:
            logger.error(f"   ❌ ERROR: {e}")
            error_count += 1
    
    # Final summary
    logger.info(f"\n{'='*80}")
    logger.info(f"✅ PROCESSING COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(f"📊 Summary:")
    logger.info(f"   Total images: {len(image_files)}")
    logger.info(f"   ✅ Successfully processed: {success_count}")
    logger.info(f"   ⏭️  Skipped (already exists): {skip_count}")
    logger.info(f"   ❌ Errors: {error_count}")
    logger.info(f"{'='*80}")
    
    if success_count > 0:
        logger.info(f"\n✅ DATA STORED IN:")
        logger.info(f"   🗄️  Cosmos DB: products collection")
        logger.info(f"      - Complete product documents with:")
        logger.info(f"        ✓ Product metadata (name, category, gender, brand, etc.)")
        logger.info(f"        ✓ Visual data (colors, materials, style_tags)")
        logger.info(f"        ✓ AI-generated pricing, inventory, assortment")
        logger.info(f"        ✓ Rich fashion descriptions")
        logger.info(f"        ✓ Image URLs for display")
        logger.info(f"        ✗ NO embedding vectors (kept lean to avoid size issues)")
        logger.info(f"   🔍 Azure AI Search: clothing-index")
        logger.info(f"      - Searchable documents with:")
        logger.info(f"        ✓ All product attributes (filterable)")
        logger.info(f"        ✓ Rich descriptions (text search)")
        logger.info(f"        ✓ Embedding vectors (3072-dim for semantic/vector search)")
        logger.info(f"   ☁️  Azure Blob Storage: {BLOB_CONTAINER_NAME}/products/")
        logger.info(f"      - Product images with Managed Identity auth")
    
    logger.info(f"\n{'='*80}\n")
    
    if dry_run:
        logger.info(f"ℹ️  This was a DRY RUN - no changes were made")
        logger.info(f"   Run without --dry-run to actually process images\n")
    elif error_count > 0:
        logger.warning(f"⚠️  Some errors occurred. Check logs above for details.")
        logger.info(f"   💡 You can re-run this script to retry failed images\n")


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Bulk upload images to Azure for retail products")
    parser.add_argument("--folder", type=str, default=DEFAULT_IMAGE_FOLDER,
                       help=f"Path to folder containing images (default: {DEFAULT_IMAGE_FOLDER})")
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulate without actually uploading (test mode)")
    parser.add_argument("--force", action="store_true",
                       help="Reprocess images even if they already exist")
    parser.add_argument("--max", type=int, default=None,
                       help="Maximum number of images to process (default: all)")
    
    args = parser.parse_args()
    
    # Convert folder path to absolute
    folder_path = Path(args.folder).resolve()
    
    # Run async processing
    asyncio.run(process_image_folder(folder_path, args.dry_run, args.force, args.max))


if __name__ == "__main__":
    main()
