"""
Banking Tools
=============

Core banking tools for account info, transactions, cards, and user profiles.
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.registries.toolstore.registry import register_tool
from utils.ml_logging import get_logger

from .constants import (
    CARD_KNOWLEDGE_BASE,
    CARD_PRODUCTS,
    CREDIT_LIMITS_BY_INCOME,
)

try:  # pragma: no cover - optional dependency during tests
    from src.cosmosdb.manager import CosmosDBMongoCoreManager as _CosmosManagerImpl
except Exception:  # pragma: no cover - handled at runtime
    _CosmosManagerImpl = None

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.cosmosdb.manager import CosmosDBMongoCoreManager

logger = get_logger("agents.tools.banking")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

get_user_profile_schema: dict[str, Any] = {
    "name": "get_user_profile",
    "description": (
        "Retrieve customer profile including account info, preferences, and relationship tier. "
        "Call this immediately after identity verification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["client_id"],
    },
}

get_account_summary_schema: dict[str, Any] = {
    "name": "get_account_summary",
    "description": (
        "Get summary of customer's accounts including balances, account numbers, and routing info. "
        "Useful for direct deposit setup or balance inquiries."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["client_id"],
    },
}

get_recent_transactions_schema: dict[str, Any] = {
    "name": "get_recent_transactions",
    "description": (
        "Get recent transactions for customer's primary account. "
        "Includes merchant, amount, date, and fee breakdowns."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "limit": {"type": "integer", "description": "Max transactions to return (default 10)"},
        },
        "required": ["client_id"],
    },
}

search_card_products_schema: dict[str, Any] = {
    "name": "search_card_products",
    "description": (
        "Search available credit card products based on customer profile and preferences. "
        "Returns personalized card recommendations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_profile": {
                "type": "string",
                "description": "Customer tier and spending info",
            },
            "preferences": {
                "type": "string",
                "description": "What they want (travel, cash back, etc.)",
            },
            "spending_categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories like travel, dining, groceries",
            },
        },
        "required": ["preferences"],
    },
}

get_card_details_schema: dict[str, Any] = {
    "name": "get_card_details",
    "description": "Get detailed information about a specific card product.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "Card product ID"},
            "query": {"type": "string", "description": "Specific question about the card"},
        },
        "required": ["product_id"],
    },
}

refund_fee_schema: dict[str, Any] = {
    "name": "refund_fee",
    "description": (
        "Process a fee refund for the customer as a courtesy. "
        "Only call after customer explicitly approves the refund."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "transaction_id": {"type": "string", "description": "ID of the fee transaction"},
            "amount": {"type": "number", "description": "Amount to refund"},
            "reason": {"type": "string", "description": "Reason for refund"},
        },
        "required": ["client_id", "amount"],
    },
}

send_card_agreement_schema: dict[str, Any] = {
    "name": "send_card_agreement",
    "description": "Send cardholder agreement email with verification code for e-signature.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "card_product_id": {"type": "string", "description": "Card product ID"},
        },
        "required": ["client_id", "card_product_id"],
    },
}

verify_esignature_schema: dict[str, Any] = {
    "name": "verify_esignature",
    "description": "Verify the e-signature code provided by customer.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "verification_code": {"type": "string", "description": "6-digit code from email"},
        },
        "required": ["client_id", "verification_code"],
    },
}

finalize_card_application_schema: dict[str, Any] = {
    "name": "finalize_card_application",
    "description": "Complete card application after e-signature verification.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "card_product_id": {"type": "string", "description": "Card product ID"},
            "card_name": {"type": "string", "description": "Full card product name"},
        },
        "required": ["client_id", "card_product_id"],
    },
}

search_credit_card_faqs_schema: dict[str, Any] = {
    "name": "search_credit_card_faqs",
    "description": "Search credit card FAQ knowledge base for information about APR, fees, benefits, eligibility, and rewards. Returns relevant FAQ entries matching the query.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'APR', 'foreign transaction fees', 'travel insurance')",
            },
            "card_name": {
                "type": "string",
                "description": "Optional card name to filter results (e.g., 'Travel Rewards', 'Premium Rewards')",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 3)",
            },
        },
        "required": ["query"],
    },
}

evaluate_card_eligibility_schema: dict[str, Any] = {
    "name": "evaluate_card_eligibility",
    "description": (
        "Evaluate if a customer is pre-approved or eligible for a specific credit card. "
        "Returns eligibility status, credit limit estimate, and next steps."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "card_product_id": {"type": "string", "description": "Card product to evaluate eligibility for"},
        },
        "required": ["client_id", "card_product_id"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# COSMOS DB HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

_COSMOS_USERS_MANAGER: CosmosDBMongoCoreManager | None = None

# User profiles are stored in audioagentdb.users
_DEFAULT_DEMO_DB = "audioagentdb"
_DEFAULT_DEMO_USERS_COLLECTION = "users"


def _get_demo_database_name() -> str:
    """Get the database name from environment or use default."""
    value = os.getenv("AZURE_COSMOS_DATABASE_NAME")
    if value:
        stripped = value.strip()
        if stripped:
            return stripped
    return _DEFAULT_DEMO_DB


def _get_demo_users_collection_name() -> str:
    """Get the users collection name from environment or use default."""
    value = os.getenv("AZURE_COSMOS_USERS_COLLECTION_NAME")
    if value:
        stripped = value.strip()
        if stripped:
            return stripped
    return _DEFAULT_DEMO_USERS_COLLECTION


def _manager_targets_collection(
    manager: CosmosDBMongoCoreManager,
    database_name: str,
    collection_name: str,
) -> bool:
    """Return True when the manager already points to the requested db/collection."""
    try:
        db_name = getattr(getattr(manager, "database", None), "name", None)
        coll_name = getattr(getattr(manager, "collection", None), "name", None)
    except Exception:
        return False
    return db_name == database_name and coll_name == collection_name


def _get_cosmos_manager() -> CosmosDBMongoCoreManager | None:
    """Resolve the shared Cosmos DB client from FastAPI app state."""
    try:
        from apps.artagent.backend import main as backend_main
    except Exception:
        return None

    app = getattr(backend_main, "app", None)
    state = getattr(app, "state", None) if app else None
    return getattr(state, "cosmos", None)


def _get_demo_users_manager() -> CosmosDBMongoCoreManager | None:
    """Return a Cosmos DB manager pointed at the demo users collection."""
    global _COSMOS_USERS_MANAGER
    database_name = _get_demo_database_name()
    container_name = _get_demo_users_collection_name()

    if _COSMOS_USERS_MANAGER is not None:
        if _manager_targets_collection(_COSMOS_USERS_MANAGER, database_name, container_name):
            return _COSMOS_USERS_MANAGER
        logger.warning("Cached Cosmos users manager pointed to different collection; refreshing")
        _COSMOS_USERS_MANAGER = None

    base_manager = _get_cosmos_manager()
    if base_manager is not None:
        if _manager_targets_collection(base_manager, database_name, container_name):
            _COSMOS_USERS_MANAGER = base_manager
            return _COSMOS_USERS_MANAGER
        logger.info("Base Cosmos manager uses different collection; creating scoped users manager")

    if _CosmosManagerImpl is None:
        logger.warning("Cosmos manager implementation unavailable; cannot query users collection")
        return None

    try:
        _COSMOS_USERS_MANAGER = _CosmosManagerImpl(
            database_name=database_name,
            collection_name=container_name,
        )
        logger.info(
            "Banking tools connected to Cosmos users collection | db=%s collection=%s",
            database_name,
            container_name,
        )
        return _COSMOS_USERS_MANAGER
    except Exception as exc:
        logger.warning("Unable to initialize Cosmos users manager: %s", exc)
        return None


def _sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize a value to be JSON-serializable.

    Handles:
    - BSON ObjectId → str
    - datetime → ISO string
    - MongoDB extended JSON ({"$date": ...}) → ISO string
    - bytes → base64 string
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, dict):
        # Handle MongoDB extended JSON date format
        if "$date" in obj and len(obj) == 1:
            date_val = obj["$date"]
            if isinstance(date_val, str):
                return date_val
            return str(date_val)
        # Handle MongoDB ObjectId format
        if "$oid" in obj and len(obj) == 1:
            return str(obj["$oid"])
        # Recursively process dict
        return {k: _sanitize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]

    # Handle datetime
    if hasattr(obj, "isoformat"):
        return obj.isoformat()

    # Handle bytes
    if isinstance(obj, bytes):
        import base64

        return base64.b64encode(obj).decode("utf-8")

    # Fallback: convert to string
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


async def _lookup_user_by_client_id(client_id: str) -> dict[str, Any] | None:
    """Query Cosmos DB for user by client_id or _id."""
    cosmos = _get_demo_users_manager()
    if cosmos is None:
        return None

    # Try both client_id field and _id (MongoDB document ID)
    queries = [
        {"client_id": client_id},
        {"_id": client_id},
    ]

    for query in queries:
        try:
            document = await asyncio.to_thread(cosmos.read_document, query)
            if document:
                logger.info("📋 User profile loaded from Cosmos: %s", client_id)
                # Sanitize document for JSON serialization
                return _sanitize_for_json(document)
        except Exception as exc:
            logger.debug("Cosmos lookup failed for query %s: %s", query, exc)
            continue

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CARD PRODUCTS & E-SIGN STATE
# ═══════════════════════════════════════════════════════════════════════════════

# Mock transactions for get_recent_transactions (sample data for demo)
_MOCK_TRANSACTIONS = [
    {
        "id": "TXN-001",
        "merchant": "Starbucks",
        "amount": 5.75,
        "date": "2024-12-01",
        "category": "dining",
    },
    {
        "id": "TXN-002",
        "merchant": "ATM - Non-Network",
        "amount": 18.00,
        "date": "2024-11-30",
        "is_fee": True,
        "fee_breakdown": {"atm_fee": 10.00, "owner_surcharge": 8.00},
    },
    {
        "id": "TXN-003",
        "merchant": "Amazon",
        "amount": 127.50,
        "date": "2024-11-29",
        "category": "shopping",
    },
    {
        "id": "TXN-004",
        "merchant": "Whole Foods",
        "amount": 89.23,
        "date": "2024-11-28",
        "category": "groceries",
    },
    {
        "id": "TXN-005",
        "merchant": "Uber",
        "amount": 24.50,
        "date": "2024-11-27",
        "category": "transport",
    },
]

_CARD_PRODUCTS = {
    "travel-rewards-001": {
        "product_id": "travel-rewards-001",
        "name": "Contoso Bank Travel Rewards",
        "annual_fee": 0,
        "rewards": "1.5 points per $1 on all purchases",
        "benefits": ["No foreign transaction fees", "Flexible redemption"],
        "intro_apr": "0% for 15 billing cycles",
        "regular_apr": "17.24% - 27.24%",
    },
    "premium-travel-002": {
        "product_id": "premium-travel-002",
        "name": "Contoso Bank Premium Rewards Elite",
        "annual_fee": 550,
        "rewards": "3x on travel and dining, 1.5x on everything else",
        "benefits": [
            "$300 travel credit",
            "TSA PreCheck credit",
            "Airport lounge access",
            "No foreign fees",
        ],
        "intro_apr": "N/A",
        "regular_apr": "19.24% - 29.24%",
    },
    "cash-back-003": {
        "product_id": "cash-back-003",
        "name": "Contoso Bank Customized Cash Rewards",
        "annual_fee": 0,
        "rewards": "3% in category of choice, 2% grocery/wholesale, 1% everywhere",
        "benefits": ["No annual fee", "Online shopping protection"],
        "intro_apr": "0% for 15 billing cycles",
        "regular_apr": "16.24% - 26.24%",
    },
}

_PENDING_ESIGN: dict[str, dict] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════


async def get_user_profile(args: dict[str, Any]) -> dict[str, Any]:
    """Get customer profile from Cosmos DB."""
    client_id = (args.get("client_id") or "").strip()

    if not client_id:
        return {"success": False, "message": "client_id is required."}

    # Get profile from Cosmos DB
    profile = await _lookup_user_by_client_id(client_id)
    if profile:
        return {"success": True, "profile": profile, "data_source": "cosmos"}

    return {"success": False, "message": f"Profile not found for {client_id}. Please create a profile first."}


async def get_account_summary(args: dict[str, Any]) -> dict[str, Any]:
    """Get account summary with balances and routing info."""
    client_id = (args.get("client_id") or "").strip()

    if not client_id:
        return {"success": False, "message": "client_id is required."}

    # First, check if session profile was injected by the orchestrator
    profile = args.get("_session_profile")
    data_source = "session"
    
    # Fallback to Cosmos DB lookup if no session profile
    if not profile:
        profile = await _lookup_user_by_client_id(client_id)
        data_source = "cosmos"

    if not profile:
        return {"success": False, "message": f"Account not found for {client_id}. Please create a profile first."}

    # Extract account data from customer_intelligence
    customer_intel = profile.get("customer_intelligence", {})
    bank_profile = customer_intel.get("bank_profile", {})
    accounts_data = customer_intel.get("accounts", {})
    
    # Build accounts list from actual data
    accounts = []
    
    # Checking account
    checking = accounts_data.get("checking", {})
    if checking:
        accounts.append({
            "type": "checking",
            "balance": checking.get("balance", 0),
            "available": checking.get("available", checking.get("balance", 0)),
            "account_number_last4": checking.get("account_number_last4", bank_profile.get("account_number_last4", "----")),
            "routing_number": bank_profile.get("routing_number", "021000021"),
        })
    
    # Savings account
    savings = accounts_data.get("savings", {})
    if savings:
        accounts.append({
            "type": "savings",
            "balance": savings.get("balance", 0),
            "available": savings.get("available", savings.get("balance", 0)),
            "account_number_last4": savings.get("account_number_last4", "----"),
            "routing_number": bank_profile.get("routing_number", "021000021"),
        })
    
    # Fallback if no accounts data available
    if not accounts:
        balance = (
            customer_intel.get("account_status", {}).get("current_balance")
            or bank_profile.get("current_balance")
            or 0
        )
        accounts = [
            {
                "type": "checking",
                "balance": balance,
                "available": balance,
                "account_number_last4": bank_profile.get("account_number_last4", "----"),
                "routing_number": bank_profile.get("routing_number", "021000021"),
            },
        ]

    return {
        "success": True,
        "accounts": accounts,
    }


async def get_recent_transactions(args: dict[str, Any]) -> dict[str, Any]:
    """Get recent transactions from user profile or fallback to mock data."""
    client_id = (args.get("client_id") or "").strip()
    limit = args.get("limit", 10)

    if not client_id:
        return {"success": False, "message": "client_id is required."}

    # First, check if session profile was injected by the orchestrator
    # This avoids redundant Cosmos DB lookups for already-loaded profiles
    session_profile = args.get("_session_profile")
    if session_profile:
        customer_intel = session_profile.get("demo_metadata", {})
        transactions = customer_intel.get("transactions", [])
        if transactions:
            logger.info("📋 Loaded %d transactions from session profile: %s", len(transactions), client_id)
            return {
                "success": True,
                "transactions": transactions[:limit],
                "data_source": "session",
            }

    # Fallback: Try to get transactions from Cosmos DB
    profile = await _lookup_user_by_client_id(client_id)
    if profile:
        customer_intel = profile.get("demo_metadata", {})
        transactions = customer_intel.get("transactions", [])
        if transactions:
            logger.info("📋 Loaded %d transactions from Cosmos: %s", len(transactions), client_id)
            return {
                "success": True,
                "transactions": transactions[:limit],
                "data_source": "cosmos",
            }

    # Fallback to mock transactions if no profile or no transactions found
    logger.info("📋 Using mock transactions for: %s (no profile data)", client_id)
    return {
        "success": True,
        "transactions": _MOCK_TRANSACTIONS[:limit],
        "data_source": "mock",
    }


async def search_card_products(args: dict[str, Any]) -> dict[str, Any]:
    """Search for card products based on preferences."""
    preferences = (args.get("preferences") or "").strip().lower()
    categories = args.get("spending_categories", [])

    results = []
    for card in _CARD_PRODUCTS.values():
        score = 0
        if "travel" in preferences and "travel" in card["name"].lower():
            score += 3
        if "cash" in preferences and "cash" in card["name"].lower():
            score += 3
        if "no fee" in preferences and card["annual_fee"] == 0:
            score += 2
        if score > 0:
            results.append({**card, "_score": score})

    # Sort by score
    results.sort(key=lambda x: x.get("_score", 0), reverse=True)

    return {
        "success": True,
        "cards": results[:3],
        "message": f"Found {len(results)} matching cards",
    }


async def get_card_details(args: dict[str, Any]) -> dict[str, Any]:
    """Get details for a specific card."""
    product_id = (args.get("product_id") or "").strip()
    query = (args.get("query") or "").strip()

    card = _CARD_PRODUCTS.get(product_id)
    if not card:
        return {"success": False, "message": f"Card {product_id} not found"}

    return {"success": True, "card": card}


async def refund_fee(args: dict[str, Any]) -> dict[str, Any]:
    """Process fee refund."""
    client_id = (args.get("client_id") or "").strip()
    amount = args.get("amount", 0)
    reason = (args.get("reason") or "courtesy refund").strip()

    if not client_id:
        return {"success": False, "message": "client_id is required."}

    logger.info("💰 Fee refund processed: %s - $%.2f", client_id, amount)

    return {
        "success": True,
        "refunded": True,
        "amount": amount,
        "message": f"Refund of ${amount:.2f} processed. Credit in 2 business days.",
    }


async def send_card_agreement(args: dict[str, Any]) -> dict[str, Any]:
    """Send card agreement email."""
    client_id = (args.get("client_id") or "").strip()
    product_id = (args.get("card_product_id") or "").strip()

    if not client_id or not product_id:
        return {"success": False, "message": "client_id and card_product_id required."}

    card = _CARD_PRODUCTS.get(product_id)
    if not card:
        return {"success": False, "message": f"Card {product_id} not found"}

    # Generate verification code
    import random
    import string

    code = "".join(random.choices(string.digits, k=6))

    _PENDING_ESIGN[client_id] = {"code": code, "card_product_id": product_id}

    # Get customer email from Cosmos DB
    profile = await _lookup_user_by_client_id(client_id)
    email = profile.get("contact_info", {}).get("email", "customer@email.com") if profile else "customer@email.com"

    logger.info("📧 Card agreement sent: %s - code: %s", client_id, code)

    return {
        "success": True,
        "email_sent": True,
        "verification_code": code,
        "email": email,
        "card_name": card["name"],
        "expires_in_hours": 24,
    }


async def verify_esignature(args: dict[str, Any]) -> dict[str, Any]:
    """Verify e-signature code."""
    client_id = (args.get("client_id") or "").strip()
    code = (args.get("verification_code") or "").strip()

    if not client_id or not code:
        return {"success": False, "message": "client_id and code required."}

    pending = _PENDING_ESIGN.get(client_id)
    if not pending:
        return {"success": False, "message": "No pending agreement found."}

    if pending["code"] == code:
        return {
            "success": True,
            "verified": True,
            "verified_at": datetime.now(UTC).isoformat(),
            "card_product_id": pending["card_product_id"],
            "next_step": "finalize_card_application",
        }

    return {"success": False, "verified": False, "message": "Invalid code."}


async def finalize_card_application(args: dict[str, Any]) -> dict[str, Any]:
    """Finalize card application."""
    client_id = (args.get("client_id") or "").strip()
    product_id = (args.get("card_product_id") or "").strip()
    card_name = (args.get("card_name") or "").strip()

    if not client_id or not product_id:
        return {"success": False, "message": "client_id and card_product_id required."}

    # Clean up pending
    _PENDING_ESIGN.pop(client_id, None)

    card = _CARD_PRODUCTS.get(product_id, {})

    logger.info("✅ Card application approved: %s - %s", client_id, card.get("name"))

    return {
        "success": True,
        "approved": True,
        "card_number_last4": "".join(random.choices("0123456789", k=4)),
        "credit_limit": random.choice([5000, 7500, 10000, 15000, 20000]),
        "physical_delivery": "3-5 business days",
        "digital_wallet_ready": True,
        "confirmation_email_sent": True,
    }


async def search_credit_card_faqs(args: dict[str, Any]) -> dict[str, Any]:
    """
    Search credit card FAQ knowledge base.
    
    Uses local CARD_KNOWLEDGE_BASE for RAG fallback when Azure AI Search is unavailable.
    Returns matching FAQ entries for card-specific questions about APR, fees, benefits, etc.
    
    Args:
        args: Dict with 'query', optional 'card_name' and 'top_k'
        
    Returns:
        Dict with 'success', 'results' list, and 'source' indicator
    """
    query = (args.get("query") or "").strip().lower()
    card_name_filter = (args.get("card_name") or "").strip().lower()
    top_k = args.get("top_k", 3)
    
    if not query:
        return {"success": False, "message": "Query is required.", "results": []}
    
    # Map card names to product IDs
    card_name_to_id = {
        "travel rewards": "travel-rewards-001",
        "premium rewards": "premium-rewards-001",
        "cash rewards": "cash-rewards-002",
        "unlimited cash": "unlimited-cash-003",
    }
    
    # Map query keywords to knowledge base keys
    query_key_mapping = {
        "apr": "apr",
        "interest": "apr",
        "rate": "apr",
        "foreign": "foreign_fees",
        "international": "foreign_fees",
        "transaction fee": "foreign_fees",
        "atm": "atm_cash_advance",
        "cash advance": "atm_cash_advance",
        "withdraw": "atm_cash_advance",
        "eligible": "eligibility",
        "qualify": "eligibility",
        "credit score": "eligibility",
        "fico": "eligibility",
        "benefit": "benefits",
        "perk": "benefits",
        "annual fee": "benefits",
        "insurance": "benefits",
        "reward": "rewards",
        "point": "rewards",
        "cash back": "rewards",
        "earn": "rewards",
        "balance transfer": "balance_transfer",
        "transfer": "balance_transfer",
        "travel": "best_for_travel",
        "abroad": "best_for_travel",
    }
    
    results = []
    
    # Determine which cards to search
    if card_name_filter and card_name_filter in card_name_to_id:
        cards_to_search = {card_name_to_id[card_name_filter]: CARD_KNOWLEDGE_BASE.get(card_name_to_id[card_name_filter], {})}
    else:
        cards_to_search = CARD_KNOWLEDGE_BASE
    
    # Find matching knowledge base key
    matched_key = None
    for keyword, kb_key in query_key_mapping.items():
        if keyword in query:
            matched_key = kb_key
            break
    
    # Search through cards
    for card_id, card_kb in cards_to_search.items():
        if not card_kb:
            continue
            
        # Format card name from ID
        card_display_name = card_id.replace("-", " ").replace("001", "").replace("002", "").replace("003", "").strip().title()
        
        if matched_key and matched_key in card_kb:
            results.append({
                "card_name": card_display_name,
                "card_id": card_id,
                "topic": matched_key,
                "answer": card_kb[matched_key],
            })
        else:
            # Fallback: search all entries for query terms
            for topic, answer in card_kb.items():
                if query in answer.lower() or query in topic.lower():
                    results.append({
                        "card_name": card_display_name,
                        "card_id": card_id,
                        "topic": topic,
                        "answer": answer,
                    })
    
    # Limit results
    results = results[:top_k]
    
    logger.info("🔍 FAQ search: query='%s', card_filter='%s', results=%d", query, card_name_filter, len(results))
    
    return {
        "success": True,
        "query": query,
        "card_filter": card_name_filter or None,
        "results": results,
        "source": "CARD_KNOWLEDGE_BASE",
        "note": "Results from local FAQ knowledge base. For real-time data, Azure AI Search integration recommended.",
    }


async def evaluate_card_eligibility(args: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate if a customer is pre-approved or eligible for a specific credit card.
    
    Uses customer tier and profile to determine eligibility status:
    - PRE_APPROVED: Customer can proceed directly to e-signature
    - APPROVED_WITH_REVIEW: Approved but may get different terms
    - PENDING_VERIFICATION: Need additional information
    - DECLINED: Not eligible (suggest alternatives)
    
    Args:
        args: Dict with 'client_id' and 'card_product_id'
        
    Returns:
        Dict with eligibility_status, credit_limit, and next_steps
    """
    client_id = (args.get("client_id") or "").strip()
    card_product_id = (args.get("card_product_id") or "").strip()
    
    if not client_id or not card_product_id:
        return {"success": False, "message": "client_id and card_product_id are required."}
    
    logger.info("🔍 Evaluating card eligibility | client_id=%s card=%s", client_id, card_product_id)
    
    # Get card product details
    card_product = CARD_PRODUCTS.get(card_product_id)
    if not card_product:
        return {"success": False, "message": f"Unknown card product: {card_product_id}"}
    
    # Fetch customer data from Cosmos DB
    mgr = _get_demo_users_manager()
    customer_data = None
    if mgr:
        try:
            customer_data = await asyncio.to_thread(mgr.read_document, {"client_id": client_id})
        except Exception as exc:
            logger.warning("Could not fetch customer data: %s", exc)
    
    # Require customer data from Cosmos DB - no mock fallback
    if not customer_data:
        return {"success": False, "message": f"Customer profile not found for {client_id}. Please create a profile first."}
    
    # Extract customer profile
    customer_intelligence = customer_data.get("customer_intelligence", {})
    relationship_context = customer_intelligence.get("relationship_context", {})
    bank_profile = customer_intelligence.get("bank_profile", {})
    
    customer_tier = relationship_context.get("relationship_tier", customer_data.get("tier", "Standard"))
    existing_cards = bank_profile.get("cards", [])
    
    # Simple eligibility scoring
    tier_lower = customer_tier.lower()
    eligibility_score = 50  # Base score
    
    if "diamond" in tier_lower or "platinum" in tier_lower:
        eligibility_score += 30
    elif "gold" in tier_lower:
        eligibility_score += 15
    
    if len(existing_cards) > 0:
        eligibility_score += 15
    
    # Determine credit limit
    if eligibility_score >= 80:
        credit_limit = CREDIT_LIMITS_BY_INCOME.get("high", 15000)
    elif eligibility_score >= 60:
        credit_limit = CREDIT_LIMITS_BY_INCOME.get("medium", 8500)
    else:
        credit_limit = CREDIT_LIMITS_BY_INCOME.get("low", 5000)
    
    # Determine status
    if eligibility_score >= 75:
        eligibility_status = "PRE_APPROVED"
        status_message = "Great news! You're pre-approved for this card."
        next_step = "send_card_agreement"
        can_proceed = True
    elif eligibility_score >= 55:
        eligibility_status = "APPROVED_WITH_REVIEW"
        status_message = "You're approved! I'll send you the agreement to review and sign."
        next_step = "send_card_agreement"
        can_proceed = True
    else:
        eligibility_status = "PENDING_VERIFICATION"
        status_message = "We need a bit more information to complete your application."
        next_step = "request_more_info"
        can_proceed = False
    
    logger.info(
        "✅ Eligibility evaluated | client_id=%s card=%s score=%d status=%s limit=$%d",
        client_id, card_product_id, eligibility_score, eligibility_status, credit_limit
    )
    
    return {
        "success": True,
        "message": status_message,
        "eligibility_status": eligibility_status,
        "eligibility_score": eligibility_score,
        "credit_limit": credit_limit,
        "card_name": card_product.name,
        "card_product_id": card_product_id,
        "can_proceed_to_agreement": can_proceed,
        "next_step": next_step,
        "customer_tier": customer_tier,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

register_tool(
    "get_user_profile", get_user_profile_schema, get_user_profile, tags={"banking", "profile"}
)
register_tool(
    "get_account_summary",
    get_account_summary_schema,
    get_account_summary,
    tags={"banking", "account"},
)
register_tool(
    "get_recent_transactions",
    get_recent_transactions_schema,
    get_recent_transactions,
    tags={"banking", "transactions"},
)
register_tool(
    "search_card_products",
    search_card_products_schema,
    search_card_products,
    tags={"banking", "cards"},
)
register_tool(
    "get_card_details", get_card_details_schema, get_card_details, tags={"banking", "cards"}
)
register_tool("refund_fee", refund_fee_schema, refund_fee, tags={"banking", "fees"})
register_tool(
    "send_card_agreement",
    send_card_agreement_schema,
    send_card_agreement,
    tags={"banking", "cards", "esign"},
)
register_tool(
    "verify_esignature",
    verify_esignature_schema,
    verify_esignature,
    tags={"banking", "cards", "esign"},
)
register_tool(
    "finalize_card_application",
    finalize_card_application_schema,
    finalize_card_application,
    tags={"banking", "cards", "esign"},
)
register_tool(
    "search_credit_card_faqs",
    search_credit_card_faqs_schema,
    search_credit_card_faqs,
    tags={"banking", "cards", "faq"},
)
register_tool(
    "evaluate_card_eligibility",
    evaluate_card_eligibility_schema,
    evaluate_card_eligibility,
    tags={"banking", "cards", "eligibility"},
)
