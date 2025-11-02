"""
ARTAgent Retail Tool Schemas
=============================

OpenAI function calling schemas for retail multi-agent system.
Defines structured parameters for checkout, returns, product search, and customer service tools.

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

from typing import Any, Dict

# ═══════════════════════════════════════════════════════════════════
# PRODUCT SEARCH TOOLS (Concierge + Stylist)
# ═══════════════════════════════════════════════════════════════════

search_products_general_schema: Dict[str, Any] = {
    "name": "search_products_general",
    "description": (
        "Fast semantic product search for direct queries. "
        "Use when customer asks for specific products without styling context. "
        "Returns top matching products with availability and pricing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language product search query (e.g., 'casual jeans', 'blue shirts', 'running shoes').",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of products to return (default: 5).",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

search_products_filtered_schema: Dict[str, Any] = {
    "name": "search_products_filtered",
    "description": (
        "Advanced filtered search for styling recommendations. "
        "Use when customer needs personalized outfit suggestions with context like occasion, weather, or formality. "
        "Applies Azure AI Search OData filters for precise matching."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Semantic search query describing desired style.",
            },
            "occasion": {
                "type": "string",
                "enum": ["wedding", "birthday", "work", "casual_outing", "date_night", "gym", "interview"],
                "description": "Event or occasion type (optional).",
            },
            "weather": {
                "type": "string",
                "enum": ["warm", "mild", "cold", "rainy"],
                "description": "Climate or weather conditions (optional).",
            },
            "formality": {
                "type": "string",
                "enum": ["casual", "business_casual", "smart_casual", "formal", "athletic"],
                "description": "Formality level (optional).",
            },
            "gender": {
                "type": "string",
                "enum": ["Men", "Women", "Unisex"],
                "description": "Target gender (optional).",
            },
            "age_group": {
                "type": "string",
                "enum": ["teen", "young_adult", "adult", "senior"],
                "description": "Age category for appropriate styling (optional, used semantically).",
            },
            "colors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Preferred color palette (optional).",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results (default: 5).",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

check_product_availability_schema: Dict[str, Any] = {
    "name": "check_product_availability",
    "description": (
        "Check real-time inventory availability for a specific product. "
        "Returns stock levels by region and availability status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "Product identifier from search results.",
            },
            "region": {
                "type": "string",
                "enum": ["US_WEST", "US_EAST", "US_SOUTH"],
                "description": "Specific region or omit for all regions (optional).",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════
# CHECKOUT & PAYMENT TOOLS (Post-Sale Agent)
# ═══════════════════════════════════════════════════════════════════

initiate_checkout_schema: Dict[str, Any] = {
    "name": "initiate_checkout",
    "description": (
        "Start checkout process with cart review. "
        "Step 1 of 6 in checkout flow. Returns cart summary with subtotal."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "User identifier from session.",
            },
            "cart_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of product IDs to purchase.",
            },
        },
        "required": ["customer_id", "cart_items"],
        "additionalProperties": False,
    },
}

apply_membership_discount_schema: Dict[str, Any] = {
    "name": "apply_membership_discount",
    "description": (
        "Apply loyalty member discount based on tier. "
        "Member: 10%, Gold: 15%, Platinum: 20%."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "User ID to check membership tier.",
            },
            "subtotal": {
                "type": "number",
                "description": "Cart subtotal before discount.",
                "minimum": 0,
            },
        },
        "required": ["customer_id", "subtotal"],
        "additionalProperties": False,
    },
}

get_shipping_options_schema: Dict[str, Any] = {
    "name": "get_shipping_options",
    "description": (
        "Display available shipping methods and costs. "
        "Free shipping on orders $50+. Options: standard (5-7 days), express (2-3 days), next day."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "order_total": {
                "type": "number",
                "description": "Total to check free shipping eligibility.",
                "minimum": 0,
            },
        },
        "required": ["order_total"],
        "additionalProperties": False,
    },
}

process_payment_schema: Dict[str, Any] = {
    "name": "process_payment",
    "description": (
        "Process payment transaction using tokenized payment method. "
        "PCI-compliant: NEVER accepts raw card numbers, only tokens. "
        "Returns transaction confirmation or decline reason."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "User ID.",
            },
            "payment_token": {
                "type": "string",
                "description": "Tokenized payment method (e.g., 'tok_visa1234'). Never raw card numbers.",
            },
            "amount": {
                "type": "number",
                "description": "Transaction amount in USD.",
                "minimum": 0.01,
            },
            "order_id": {
                "type": "string",
                "description": "Order identifier for tracking.",
            },
        },
        "required": ["customer_id", "payment_token", "amount", "order_id"],
        "additionalProperties": False,
    },
}

create_order_schema: Dict[str, Any] = {
    "name": "create_order",
    "description": (
        "Create order record after successful payment. "
        "Generates order number, saves to database, schedules delivery. "
        "Returns order confirmation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "User ID.",
            },
            "cart_items": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Products purchased with quantities.",
            },
            "total_amount": {
                "type": "number",
                "description": "Final amount paid.",
                "minimum": 0,
            },
            "shipping_method": {
                "type": "string",
                "enum": ["standard", "express", "next_day"],
                "description": "Selected shipping option.",
            },
            "shipping_address": {
                "type": "object",
                "description": "Delivery address.",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "zipcode": {"type": "string"},
                },
            },
            "transaction_id": {
                "type": "string",
                "description": "Payment transaction ID from process_payment.",
            },
        },
        "required": ["customer_id", "cart_items", "total_amount", "transaction_id"],
        "additionalProperties": False,
    },
}

get_order_status_schema: Dict[str, Any] = {
    "name": "get_order_status",
    "description": (
        "Track order status and delivery information. "
        "Returns current status, tracking number, and estimated delivery."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "order_number": {
                "type": "string",
                "description": "Order ID to track.",
            },
        },
        "required": ["order_number"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════
# HANDOFF TOOLS (All Agents)
# ═══════════════════════════════════════════════════════════════════

handoff_to_stylist_schema: Dict[str, Any] = {
    "name": "handoff_to_stylist",
    "description": (
        "Transfer customer to Personal Stylist for personalized fashion advice and outfit coordination. "
        "Use when customer needs styling help, outfit suggestions, or event-specific recommendations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Customer name if known (optional).",
            },
            "query_context": {
                "type": "string",
                "description": "What customer is looking for (required).",
            },
            "preferences": {
                "type": "string",
                "description": "Known style preferences (optional).",
            },
        },
        "required": ["query_context"],
        "additionalProperties": False,
    },
}

handoff_to_postsale_schema: Dict[str, Any] = {
    "name": "handoff_to_postsale",
    "description": (
        "Transfer customer to Post-Sale Agent for checkout, order tracking, returns, or exchanges. "
        "Use when customer is ready to buy or needs transaction support."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Customer name (optional).",
            },
            "cart_items": {
                "type": "string",
                "description": "Products to purchase or manage (optional).",
            },
            "intent": {
                "type": "string",
                "enum": ["checkout", "return", "track_order", "exchange"],
                "description": "Transaction intent (required).",
            },
        },
        "required": ["intent"],
        "additionalProperties": False,
    },
}

handoff_to_concierge_schema: Dict[str, Any] = {
    "name": "handoff_to_concierge",
    "description": (
        "Return customer to Shopping Concierge for general assistance. "
        "Use when customer needs basic product search, store info, or policy questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Customer name (optional).",
            },
            "reason": {
                "type": "string",
                "description": "Why returning to concierge (required).",
            },
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}

escalate_to_human_schema: Dict[str, Any] = {
    "name": "escalate_to_human",
    "description": (
        "Escalate to human customer service agent for complex issues. "
        "Use when customer explicitly requests human or issue is beyond AI capabilities."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Customer name (optional).",
            },
            "issue": {
                "type": "string",
                "description": "Description of problem (required).",
            },
            "urgency": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Priority level (default: medium).",
                "default": "medium",
            },
        },
        "required": ["issue"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════
# STORE INFORMATION & POLICY TOOLS
# ═══════════════════════════════════════════════════════════════════

get_product_details_schema: Dict[str, Any] = {
    "name": "get_product_details",
    "description": (
        "Get comprehensive product information including pricing, specifications, images, inventory, and reviews. "
        "Use when customer asks for more details about a specific product."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "Product identifier from search results.",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

get_pricing_for_tier_schema: Dict[str, Any] = {
    "name": "get_pricing_for_tier",
    "description": (
        "Calculate personalized pricing with loyalty tier discount. "
        "Member: 10% off, Gold: 15% off, Platinum: 20% off."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "Product to price.",
            },
            "customer_tier": {
                "type": "string",
                "enum": ["Member", "Gold", "Platinum"],
                "description": "Loyalty membership level.",
            },
        },
        "required": ["product_id", "customer_tier"],
        "additionalProperties": False,
    },
}

check_current_promotions_schema: Dict[str, Any] = {
    "name": "check_current_promotions",
    "description": (
        "Get active sales, promotions, and special offers. "
        "Can optionally filter by product category."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Optional category filter (jeans, shirts, shoes, outerwear, etc.).",
            },
        },
        "additionalProperties": False,
    },
}

get_store_hours_schema: Dict[str, Any] = {
    "name": "get_store_hours",
    "description": (
        "Get store operating hours and location information. "
        "Can optionally search for nearest store by location."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "Optional city or zip code to find nearest store.",
            },
        },
        "additionalProperties": False,
    },
}

get_return_policy_schema: Dict[str, Any] = {
    "name": "get_return_policy",
    "description": (
        "Explain store return and exchange policy. "
        "30-day return window, unworn with tags, refund in 5-7 business days."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
