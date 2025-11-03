"""
ARTAgent Post-Sale Tools (MVP - Cart Capture + Email Confirmation)
===================================================================

Minimal implementation for checkout flow:
1. Capture cart items from handoff
2. Send order confirmation email with product details

No payment processing yet - this is the foundation for future expansion.

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

import asyncio
import datetime
from typing import Any, Dict, List, Optional, TypedDict

from src.acs import EmailService
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger("tools.postsale")

# ──────────────────────────────────────────────────────────────────────────────
# Cosmos DB Manager for Cart Storage
# ──────────────────────────────────────────────────────────────────────────────

_cart_cosmos_manager = None
_product_cosmos_manager = None


def get_cart_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create Cosmos DB manager for cart storage."""
    global _cart_cosmos_manager
    if _cart_cosmos_manager is None:
        _cart_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="retail_db",
            collection_name="carts"
        )
    return _cart_cosmos_manager


def get_product_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create Cosmos DB manager for product lookups."""
    global _product_cosmos_manager
    if _product_cosmos_manager is None:
        _product_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="retail_db",
            collection_name="products"
        )
    return _product_cosmos_manager


# ──────────────────────────────────────────────────────────────────────────────
# TypedDict Models
# ──────────────────────────────────────────────────────────────────────────────

class CaptureCartArgs(TypedDict):
    """Arguments for capturing cart items."""
    product_ids: List[str]
    customer_email: str
    customer_name: Optional[str]


class CaptureCartResult(TypedDict):
    """Result of capturing cart items."""
    ok: bool
    message: str
    cart_id: Optional[str]
    item_count: int
    total_price: Optional[float]
    products: Optional[List[Dict[str, Any]]]


class SendEmailArgs(TypedDict):
    """Arguments for sending order confirmation email."""
    customer_email: str
    customer_name: Optional[str]


class SendEmailResult(TypedDict):
    """Result of sending confirmation email."""
    ok: bool
    message: str
    email_sent: bool


# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def _format_price_for_voice(price: float) -> str:
    """Format price for voice output: '90 dollars' not '$90.00'."""
    return f"{int(price)} dollars" if price == int(price) else f"{price:.2f} dollars"


def _create_order_confirmation_email_html(
    customer_name: str,
    products: List[Dict[str, Any]],
    total_price: float,
    order_id: str,
    loyalty_tier: str = "Member",
    address: Optional[Dict[str, str]] = None,
    total_discount: float = 0.0
) -> tuple[str, str, str]:
    """
    Create order confirmation email with customer info, address, loyalty tier, and discounted pricing.
    
    Returns:
        tuple: (subject, plain_text, html)
    """
    subject = f"✅ Order Confirmation {order_id} - Thank You for Your Purchase!"
    address = address or {}
    
    # Plain text version
    plain_text = f"""Dear {customer_name},

Thank you for your order! Your payment has been confirmed.

ORDER NUMBER: {order_id}
ORDER DATE: {datetime.datetime.utcnow().strftime('%B %d, %Y')}
LOYALTY STATUS: {loyalty_tier} Member

SHIPPING ADDRESS:
{address.get('street', '')}
{address.get('city', '')}, {address.get('state', '')} {address.get('zip', '')}
{address.get('country', '')}

Your order details:

"""
    
    for idx, product in enumerate(products, 1):
        plain_text += f"{idx}. {product['name']} by {product['brand']}\n"
        if product.get('base_price', 0) > product.get('price', 0):
            plain_text += f"   Original Price: ${product.get('base_price', 0):.2f}\n"
            plain_text += f"   Your Price: ${product['price']:.2f} ({loyalty_tier} Discount)\n"
        else:
            plain_text += f"   Price: ${product['price']:.2f}\n"
        if product.get('colors'):
            plain_text += f"   Colors: {', '.join(product['colors'])}\n"
        plain_text += "\n"
    
    plain_text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if total_discount > 0:
        plain_text += f"Subtotal: ${total_price + total_discount:.2f}\n"
        plain_text += f"{loyalty_tier} Discount: -${total_discount:.2f}\n"
    plain_text += f"TOTAL: ${total_price:.2f}\n"
    plain_text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    plain_text += f"✅ PAYMENT CONFIRMED\n"
    plain_text += f"Your payment has been successfully processed.\n\n"
    plain_text += f"📦 SHIPPING DETAILS\n"
    plain_text += f"Your order will be shipped to:\n"
    plain_text += f"{address.get('street', '')}, {address.get('city', '')}, {address.get('state', '')} {address.get('zip', '')}\n"
    plain_text += f"Expected delivery: 3-5 business days\n\n"
    plain_text += f"💎 {loyalty_tier} MEMBER BENEFITS\n"
    plain_text += f"You saved ${total_discount:.2f} on this order!\n"
    plain_text += f"Keep shopping to unlock more exclusive benefits.\n\n"
    plain_text += f"Questions? Reply to this email or contact our support team.\n\n"
    plain_text += f"Thank you for shopping with us!\n\n"
    plain_text += f"Best regards,\nThe Retail Team\n"
    plain_text += f"Order Reference: {order_id}"
    
    # HTML version with product images
    product_cards_html = ""
    for product in products:
        image_url = product.get('image_url', '')
        product_cards_html += f"""
        <div style="background: white; border-radius: 8px; padding: 15px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                    <td width="120" style="padding-right: 15px;">
                        <img src="{image_url}" alt="{product['name']}" style="width: 100px; height: 100px; object-fit: cover; border-radius: 8px;" />
                    </td>
                    <td>
                        <h3 style="margin: 0 0 5px 0; color: #333; font-size: 16px;">{product['name']}</h3>
                        <p style="margin: 0 0 5px 0; color: #666; font-size: 14px;">{product['brand']}</p>
                        <p style="margin: 0 0 5px 0; color: #0066cc; font-size: 18px; font-weight: bold;">${product['price']:.2f}</p>
                        {'<p style="margin: 0; color: #999; font-size: 12px;">Colors: ' + ', '.join(product.get('colors', [])) + '</p>' if product.get('colors') else ''}
                    </td>
                </tr>
            </table>
        </div>
        """
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f5f5f5;">
    <!-- Header -->
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 20px; text-align: center;">
        <h1 style="margin: 0; font-size: 32px; font-weight: 600;">✅ Order Confirmed!</h1>
        <p style="margin: 15px 0 5px 0; font-size: 18px;">Thank you for your purchase, {customer_name}!</p>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">Order #{order_id}</p>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">{datetime.datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')}</p>
    </div>
    
    <!-- Content -->
    <div style="padding: 30px 20px; background: #f9f9f9;">
        <!-- Payment Confirmed Banner -->
        <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; border-radius: 8px; padding: 20px; margin: 0 0 25px 0; text-align: center;">
            <h2 style="margin: 0; font-size: 20px; font-weight: 600;">✅ Payment Confirmed</h2>
            <p style="margin: 8px 0 0 0; font-size: 14px; opacity: 0.95;">Your payment has been successfully processed</p>
        </div>
        
        <h3 style="font-size: 18px; color: #333; margin: 0 0 15px 0;">Your Order Details:</h3>
        
        <!-- Product Cards -->
        {product_cards_html}
        
        <!-- Total -->
        <div style="background: white; border-radius: 8px; padding: 25px; margin: 25px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="text-align: left;">
                            <p style="margin: 0; color: #666; font-size: 14px;">Subtotal</p>
                        </td>
                        <td style="text-align: right;">
                            <p style="margin: 0; color: #333; font-size: 16px;">${total_price:.2f}</p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding-top: 15px; border-top: 2px solid #e5e7eb; text-align: left;">
                            <h2 style="margin: 0; color: #111; font-size: 24px; font-weight: 700;">Total</h2>
                        </td>
                        <td style="padding-top: 15px; border-top: 2px solid #e5e7eb; text-align: right;">
                            <h2 style="margin: 0; color: #667eea; font-size: 28px; font-weight: 700;">${total_price:.2f}</h2>
                        </td>
                    </tr>
                </table>
            </div>
        </div>
        
        <!-- Next Steps -->
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 20px; margin: 20px 0; border-radius: 4px;">
            <h3 style="margin: 0 0 12px 0; color: #92400e; font-size: 16px; font-weight: 600;">📦 What Happens Next?</h3>
            <ul style="margin: 0; padding-left: 20px; color: #78350f; font-size: 14px; line-height: 1.6;">
                <li>We're preparing your order now</li>
                <li>You'll receive shipping details within 24 hours</li>
                <li>Track your order with reference: <strong>{order_id}</strong></li>
            </ul>
        </div>
        
        <!-- Support Section -->
        <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 10px 0; color: #333; font-size: 16px;">Need Help?</h3>
            <p style="margin: 0; color: #666; font-size: 14px;">Reply to this email or contact our support team</p>
            <p style="margin: 10px 0 0 0; color: #667eea; font-size: 14px; font-weight: 600;">Order Reference: {order_id}</p>
        </div>
    </div>
    
    <!-- Footer -->
    <div style="background: #333; color: white; padding: 20px; text-align: center;">
        <p style="margin: 0; font-size: 14px;">Thank you for shopping with us!</p>
        <p style="margin: 10px 0 0 0; font-size: 12px; color: #999;">Retail Team</p>
    </div>
</body>
</html>"""
    
    return subject, plain_text, html


# ──────────────────────────────────────────────────────────────────────────────
# Post-Sale Tools
# ──────────────────────────────────────────────────────────────────────────────

async def capture_cart_items(args: CaptureCartArgs) -> CaptureCartResult:
    """
    Capture cart items from handoff and store in Cosmos DB.
    
    This tool:
    1. Validates product IDs exist
    2. Fetches full product details (name, price, images)
    3. Calculates total
    4. Stores cart in Cosmos DB with TTL for cleanup
    """
    try:
        product_ids = args.get("product_ids", [])
        customer_email = args.get("customer_email", "").strip()
        customer_name = args.get("customer_name", "").strip() or "Customer"
        
        if not product_ids:
            return {
                "ok": False,
                "message": "No products provided. Please select items first.",
                "cart_id": None,
                "item_count": 0,
                "total_price": None,
                "products": None
            }
        
        if not customer_email:
            return {
                "ok": False,
                "message": "Customer email is required for order confirmation.",
                "cart_id": None,
                "item_count": 0,
                "total_price": None,
                "products": None
            }
        
        logger.info(f"📦 Capturing cart: {len(product_ids)} items for {customer_email}",
                   extra={"customer_email": customer_email, "item_count": len(product_ids)})
        
        # Fetch product details from Cosmos DB
        product_cosmos = get_product_cosmos_manager()
        products = []
        total_price = 0.0
        
        for product_id in product_ids:
            try:
                product_data = await asyncio.to_thread(
                    product_cosmos.read_document,
                    {"id": product_id}
                )
                
                if product_data:
                    products.append({
                        "product_id": product_id,
                        "name": product_data.get("name", "Unknown Product"),
                        "brand": product_data.get("brand", ""),
                        "price": product_data.get("price", 0),
                        "image_url": product_data.get("image_url", ""),
                        "colors": product_data.get("colors", []),
                        "category": product_data.get("category", "")
                    })
                    total_price += product_data.get("price", 0)
                else:
                    logger.warning(f"⚠️ Product not found: {product_id}")
            except Exception as lookup_error:
                logger.error(f"❌ Error fetching product {product_id}: {lookup_error}")
        
        if not products:
            return {
                "ok": False,
                "message": "Unable to find product details. Please try again.",
                "cart_id": None,
                "item_count": 0,
                "total_price": None,
                "products": None
            }
        
        # Create cart document
        cart_id = f"cart_{customer_email.replace('@', '_')}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        cart_document = {
            "_id": cart_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "products": products,
            "total_price": total_price,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "pending_confirmation",
            "ttl": 86400  # Auto-delete after 24 hours
        }
        
        # Store cart in Cosmos DB
        cart_cosmos = get_cart_cosmos_manager()
        await asyncio.to_thread(
            cart_cosmos.upsert_document,
            document=cart_document,
            query={"_id": cart_id}
        )
        
        # Build voice-friendly message
        items_description = ", ".join([f"{p['name']} for {_format_price_for_voice(p['price'])}" for p in products[:2]])
        if len(products) > 2:
            items_description += f" and {len(products) - 2} more item{'s' if len(products) > 2 else ''}"
        
        message = f"I've captured your cart with {len(products)} item{'s' if len(products) > 1 else ''}: {items_description}. Your total is {_format_price_for_voice(total_price)}."
        
        logger.info(f"✅ Cart captured: {cart_id} with {len(products)} items, total ${total_price:.2f}",
                   extra={"cart_id": cart_id, "customer_email": customer_email, "total": total_price})
        
        return {
            "ok": True,
            "message": message,
            "cart_id": cart_id,
            "item_count": len(products),
            "total_price": total_price,
            "products": products
        }
        
    except Exception as e:
        logger.error(f"❌ Error capturing cart: {e}", exc_info=True)
        return {
            "ok": False,
            "message": "Unable to capture cart. Please try again.",
            "cart_id": None,
            "item_count": 0,
            "total_price": None,
            "products": None
        }


async def get_product_details(product_id: str) -> Optional[Dict[str, Any]]:
    """
    Query Cosmos DB to get full product information by product ID.
    
    Args:
        product_id: Product ID (e.g., "PROD-ABC123")
    
    Returns:
        dict: Full product details including name, price, images, etc.
    """
    try:
        product_cosmos = get_product_cosmos_manager()
        product_data = await asyncio.to_thread(
            product_cosmos.read_document,
            {"id": product_id}
        )
        
        if product_data:
            logger.info(f"✅ Product details retrieved: {product_id}",
                       extra={"product_id": product_id})
            return {
                "product_id": product_id,
                "name": product_data.get("name", "Unknown Product"),
                "brand": product_data.get("brand", ""),
                "price": product_data.get("price", 0),
                "image_url": product_data.get("image_url", ""),
                "colors": product_data.get("colors", []),
                "sizes": product_data.get("sizes", []),
                "category": product_data.get("category", ""),
                "description": product_data.get("rich_description", "")
            }
        else:
            logger.warning(f"⚠️ Product not found: {product_id}")
            return None
    except Exception as e:
        logger.error(f"❌ Error fetching product {product_id}: {e}")
        return None


async def send_order_confirmation_email(args: SendEmailArgs) -> SendEmailResult:
    """
    Send order confirmation email with customer info, discounted prices, and shipping details.
    
    Products come from handoff context (passed by Shopping Concierge/Stylist).
    Gets customer profile, applies loyalty discounts, and sends complete order confirmation.
    """
    try:
        product_ids = args.get("product_ids", [])
        
        if not product_ids:
            return {
                "ok": False,
                "message": "No products selected. Please select items first.",
                "email_sent": False
            }
        
        # Get customer profile (name, email, address, loyalty tier)
        customer_info = await get_customer_info({})
        if not customer_info.get("ok"):
            return {
                "ok": False,
                "message": "Unable to retrieve customer information.",
                "email_sent": False
            }
        
        customer_name = customer_info.get("name", "Customer")
        customer_email = customer_info.get("email", "pablosal@microsoft.com")
        loyalty_tier = customer_info.get("loyalty_tier", "Member")
        address = customer_info.get("address", {})
        
        logger.info(f"📧 Sending order confirmation to {customer_email} ({loyalty_tier}) for {len(product_ids)} products",
                   extra={"customer_email": customer_email, "product_count": len(product_ids), "loyalty_tier": loyalty_tier})
        
        # Fetch product details with discounted prices
        products = []
        total_base_price = 0.0
        total_discount = 0.0
        total_price = 0.0
        
        for product_id in product_ids:
            # Get pricing info with loyalty discount
            price_info = await get_product_price({"product_id": product_id})
            if price_info.get("ok"):
                # Also get full product details for images
                product_details = await get_product_details(product_id)
                products.append({
                    "product_id": product_id,
                    "name": price_info.get("product_name", "Unknown"),
                    "brand": price_info.get("brand", ""),
                    "base_price": price_info.get("base_price", 0),
                    "discount_amount": price_info.get("discount_amount", 0),
                    "price": price_info.get("final_price", 0),  # Discounted price
                    "image_url": product_details.get("image_url", "") if product_details else "",
                    "colors": product_details.get("colors", []) if product_details else [],
                    "category": product_details.get("category", "") if product_details else ""
                })
                total_base_price += price_info.get("base_price", 0)
                total_discount += price_info.get("discount_amount", 0)
                total_price += price_info.get("final_price", 0)
        
        if not products:
            return {
                "ok": False,
                "message": "Unable to retrieve product details. Please try again.",
                "email_sent": False
            }
        
        # Generate realistic order ID
        order_id = f"ORD-{datetime.datetime.utcnow().strftime('%Y%m%d')}-{datetime.datetime.utcnow().strftime('%H%M%S')}"
        
        # Create complete email content with customer info, address, and pricing
        subject, plain_text, html = _create_order_confirmation_email_html(
            customer_name=customer_name,
            products=products,
            total_price=total_price,
            order_id=order_id,
            loyalty_tier=loyalty_tier,
            address=address,
            total_discount=total_discount
        )
        
        # Send email via Azure Communication Services
        email_service = EmailService()
        if not email_service.is_configured():
            logger.error("❌ Email service not configured")
            return {
                "ok": False,
                "message": "Email service temporarily unavailable. Please contact support.",
                "email_sent": False
            }
        
        await email_service.send_email(
            email_address=customer_email,
            subject=subject,
            plain_text_body=plain_text,
            html_body=html
        )
        
        logger.info(f"✅ Order confirmation sent to {customer_email}",
                   extra={"customer_email": customer_email, "order_id": order_id, "item_count": len(products)})
        
        return {
            "ok": True,
            "message": f"Perfect! Your order confirmation has been sent to {customer_email}. Order number {order_id}. You'll receive it in the next minute with all the details!",
            "email_sent": True
        }
        
    except Exception as e:
        logger.error(f"❌ Error sending confirmation email: {e}", exc_info=True)
        return {
            "ok": False,
            "message": "Unable to send confirmation email. Please try again.",
            "email_sent": False
        }


# ──────────────────────────────────────────────────────────────────────────────
# NEW: Simplified Checkout Tools (Customer Info + Pricing)
# ──────────────────────────────────────────────────────────────────────────────

async def get_customer_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get customer profile information for checkout.
    
    Returns mock customer data for demo (would query Cosmos DB users collection in production).
    """
    try:
        logger.info("📋 Getting customer profile for checkout")
        
        # Mock customer data (TODO: Query Cosmos DB users collection)
        customer_data = {
            "ok": True,
            "name": "Michael",
            "email": "pablosal@microsoft.com",
            "loyalty_tier": "Platinum",
            "address": {
                "street": "123 Fashion Ave",
                "city": "Seattle",
                "state": "WA",
                "zip": "98101",
                "country": "USA"
            },
            "phone": "+1 (206) 555-0123",
            "member_since": "2023-01-15"
        }
        
        logger.info(f"✅ Customer profile retrieved: {customer_data['name']} ({customer_data['loyalty_tier']})")
        return customer_data
        
    except Exception as e:
        logger.error(f"❌ Error getting customer info: {e}", exc_info=True)
        return {
            "ok": False,
            "message": "Unable to retrieve customer information."
        }


async def get_product_price(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get discounted price for a product based on customer's loyalty tier.
    
    Queries product from Cosmos DB and applies tier-based discount.
    """
    try:
        product_id = args.get("product_id", "").strip()
        
        if not product_id:
            return {
                "ok": False,
                "message": "Product ID required."
            }
        
        # Get customer info to apply correct discount
        customer_info = await get_customer_info({})
        loyalty_tier = customer_info.get("loyalty_tier", "Member")
        
        # Fetch product from Cosmos DB (use "id" not "_id")
        product_cosmos = get_product_cosmos_manager()
        product_data = await asyncio.to_thread(
            product_cosmos.read_document,
            {"id": product_id}
        )
        
        if not product_data:
            return {
                "ok": False,
                "message": f"Product {product_id} not found."
            }
        
        # Apply tier-based discount
        base_price = product_data.get("price", 0)
        discount_rates = {
            "Member": 0.10,
            "Gold": 0.15,
            "Platinum": 0.20
        }
        discount_rate = discount_rates.get(loyalty_tier, 0.10)
        discount_amount = base_price * discount_rate
        final_price = base_price - discount_amount
        
        logger.info(f"💰 Pricing: {product_data.get('name')} | ${base_price:.2f} → ${final_price:.2f} ({loyalty_tier})")
        
        return {
            "ok": True,
            "product_id": product_id,
            "product_name": product_data.get("name", "Unknown"),
            "brand": product_data.get("brand", ""),
            "base_price": base_price,
            "discount_percent": int(discount_rate * 100),
            "discount_amount": discount_amount,
            "final_price": final_price,
            "loyalty_tier": loyalty_tier,
            "message": f"The {product_data.get('name')} is ${final_price:.2f} with your {loyalty_tier} discount. That's ${discount_amount:.2f} off the regular price of ${base_price:.2f}!"
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting product price: {e}", exc_info=True)
        return {
            "ok": False,
            "message": "Unable to calculate pricing right now."
        }
