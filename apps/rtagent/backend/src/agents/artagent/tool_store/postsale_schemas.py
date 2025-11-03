"""
ARTAgent Post-Sale Tool Schemas (MVP - Email Confirmation Only)
================================================================

Minimal checkout tools for capturing cart and sending confirmation emails.
No payment processing yet - just order confirmation flow.

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

from typing import Any, Dict

# ═══════════════════════════════════════════════════════════════════
# POST-SALE CHECKOUT TOOLS (MVP - Single Tool)
# ═══════════════════════════════════════════════════════════════════

send_order_confirmation_email_schema: Dict[str, Any] = {
    "name": "send_order_confirmation_email",
    "description": (
        "Send order confirmation email with product details, images, and realistic order ID. "
        "Only call after customer explicitly confirms the order (says 'yes', 'correct', 'send it'). "
        "Product IDs come from handoff context (passed by Shopping Concierge/Stylist). "
        "Email is automatically sent to pablosal@microsoft.com (demo)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of product IDs from handoff context (e.g., ['PROD-ABC123', 'PROD-XYZ789']). "
                    "These are passed automatically from Shopping Concierge/Stylist handoff."
                ),
            },
            "customer_name": {
                "type": "string",
                "description": "Customer's first name for email personalization (from handoff or conversation).",
            },
        },
        "required": ["product_ids"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════
# CUSTOMER INFO TOOL
# ═══════════════════════════════════════════════════════════════════

get_customer_info_schema: Dict[str, Any] = {
    "name": "get_customer_info",
    "description": (
        "Get customer profile information including name, email, address, and loyalty tier. "
        "Call this first to get customer details for order confirmation."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════
# PRICING TOOL
# ═══════════════════════════════════════════════════════════════════

get_product_price_schema: Dict[str, Any] = {
    "name": "get_product_price",
    "description": (
        "Get the discounted price for a product based on customer's loyalty tier. "
        "Call this for each product to show personalized pricing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "Product ID to get pricing for (e.g., 'PROD-ABC123')",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

# Export schema list for agent registration
POSTSALE_SCHEMAS = [
    get_customer_info_schema,
    get_product_price_schema,
    send_order_confirmation_email_schema,
]
