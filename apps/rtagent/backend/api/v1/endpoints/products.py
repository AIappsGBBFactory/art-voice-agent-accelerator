"""
Product-related API endpoints.

Provides REST endpoints for product images and metadata.
"""
import logging
import httpx
from fastapi import APIRouter, HTTPException, Response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/products/image/{product_id}")
async def get_product_image(product_id: str) -> Response:
    """
    Proxy endpoint for product images from Azure Blob Storage.
    
    Uses Managed Identity to authenticate with blob storage, allowing
    frontend to display images without requiring public blob access.
    
    Args:
        product_id: Product ID (e.g., PROD-MN-JEAN-2F9B66DF)
        blob_client: Azure Blob Storage client (injected)
    
    Returns:
        Image bytes with appropriate content-type
        
    Raises:
        404: Image not found
        500: Blob storage error
    """
    if not blob_client:
        logger.error("Blob storage client not available")
        raise HTTPException(
            status_code=500,
            detail="Image service unavailable"
        )
    
    try:
        # Construct blob path: products/{product_id}.png
        blob_path = f"products/{product_id}.png"
        
        logger.debug(f"Fetching product image: {blob_path}")
        
        # Get blob client for specific image
        container_client = blob_client.get_container_client("clothesimages")
        blob = container_client.get_blob_client(blob_path)
        
        # Download image bytes
        download_stream = blob.download_blob()
        image_bytes = download_stream.readall()
        
        logger.info(
            f"Product image served: {product_id} ({len(image_bytes)} bytes)",
            extra={
                "product_id": product_id,
                "image_size_bytes": len(image_bytes),
                "event_type": "product_image_served"
            }
        )
        
        # Return image with correct content type
        return Response(
            content=image_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                "Content-Disposition": f"inline; filename={product_id}.png"
            }
        )
        
    except ResourceNotFoundError:
        logger.warning(
            f"Product image not found: {product_id}",
            extra={
                "product_id": product_id,
                "event_type": "product_image_not_found"
            }
        )
        raise HTTPException(
            status_code=404,
            detail=f"Image not found for product {product_id}"
        )
        
    except Exception as e:
        logger.error(
            f"Failed to fetch product image: {product_id} - {e}",
            exc_info=True,
            extra={
                "product_id": product_id,
                "error": str(e),
                "event_type": "product_image_error"
            }
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to load product image"
        )
