# Tools Architecture & Service Integration

This guide provides comprehensive documentation on the tools available in the ART Voice Agent Accelerator, how they integrate with external services, and how to leverage and extend the demo profile endpoint.

## Table of Contents

1. [Tool Registry Overview](#tool-registry-overview)
2. [Available Tools by Category](#available-tools-by-category)
3. [External Service Integration](#external-service-integration)
4. [Demo Profile Endpoint](#demo-profile-endpoint)
5. [Jinja Template Parameters](#jinja-template-parameters)
6. [Extending the Demo Profile Endpoint](#extending-the-demo-profile-endpoint)
7. [Best Practices](#best-practices)

---

## Tool Registry Overview

The ART Voice Agent uses a **centralized registry pattern** for tool management. All tools are registered at import time using the `@register_tool` decorator and stored in a global registry accessible by AI agents.

### Architecture

```
apps/artagent/backend/registries/toolstore/
├── registry.py              # Central tool registration & executor
├── auth.py                  # Identity verification tools
├── banking/
│   ├── banking.py           # Core banking operations
│   └── constants.py         # Card products & templates
├── insurance/
│   ├── fnol.py              # First Notice of Loss
│   ├── policy.py            # Policy management
│   ├── subro.py             # Subrogation tools
│   └── constants.py         # Insurance test scenarios
├── customer_intelligence.py # Customer insights
├── fraud.py                 # Fraud detection
├── compliance.py            # Regulatory compliance
├── escalation.py            # Issue escalation
├── handoffs.py              # Agent transfer tools
├── knowledge_base.py        # RAG search
├── voicemail.py             # Voicemail handling
├── call_transfer.py         # Call routing
└── transfer_agency.py       # Fund transfers
```

### Tool Registration Pattern

Tools are registered using a decorator pattern:

```python
from apps.artagent.backend.registries.toolstore.registry import register_tool

@register_tool(
    name="get_user_profile",
    schema={
        "name": "get_user_profile",
        "description": "Retrieve customer profile including account info...",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string", "description": "Customer identifier"}
            },
            "required": ["client_id"]
        }
    },
    tags={"banking", "profile"},
    is_handoff=False
)
async def get_user_profile_executor(args: dict) -> dict:
    """Retrieve user profile from Cosmos DB."""
    client_id = args["client_id"]
    # ... implementation
    return profile_data
```

---

## Available Tools by Category

### Authentication & Identity (auth.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `verify_client_identity` | Verify user identity using name + SSN4 | Cosmos DB |
| `send_mfa_code` | Send MFA verification code via email/SMS | Redis, ACS Email |
| `verify_mfa_code` | Validate MFA code from user | Redis, Cosmos DB |
| `resend_mfa_code` | Resend expired MFA code | Redis, ACS Email |

### Banking Operations (banking/banking.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `get_user_profile` | Retrieve full customer profile | Cosmos DB |
| `get_account_summary` | Get account balances & numbers | Cosmos DB |
| `get_recent_transactions` | Fetch transaction history | Cosmos DB |
| `refund_fee` | Process fee refund | Cosmos DB |
| `get_spending_analysis` | Analyze spending patterns | Cosmos DB |
| `get_credit_card_info` | Get card details & limits | Cosmos DB |
| `apply_for_credit_card` | Submit card application | Cosmos DB |
| `send_esignature_code` | Email card agreement | ACS Email |
| `order_replacement_card` | Request card replacement | Cosmos DB |
| `get_account_statement` | Retrieve statements | Cosmos DB |

### Insurance Operations

#### First Notice of Loss (insurance/fnol.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `record_fnol_claim` | Record new insurance claim | Cosmos DB |
| `get_fnol_claim_status` | Check claim status | Cosmos DB |

#### Policy Management (insurance/policy.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `get_policy_info` | Retrieve policy details | Cosmos DB |
| `get_policy_coverage` | Get coverage limits | Cosmos DB |
| `check_policy_renewal` | Check renewal status | Cosmos DB |
| `update_policy_contact` | Update contact info | Cosmos DB |
| `get_premium_info` | Get premium details | Cosmos DB |

#### Subrogation (insurance/subro.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `get_claim_status` | Get subrogation claim status | Cosmos DB |
| `get_demand_status` | Check demand payment status | Cosmos DB |
| `get_liability_decision` | Get liability determination | Cosmos DB |
| `get_coverage_status` | Check coverage verification | Cosmos DB |
| `get_payment_info` | Get payment details | Cosmos DB |
| `escalate_rush_request` | Escalate urgent demand | Cosmos DB, ACS Email |
| `send_call_summary` | Email call summary to CC rep | ACS Email |
| `get_insured_vehicle_info` | Get vehicle details | Cosmos DB |
| `get_policy_limits` | Get policy coverage limits | Cosmos DB |

### Customer Intelligence (customer_intelligence.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `get_customer_intelligence` | Fetch personalized insights | Cosmos DB |

### Knowledge Base (knowledge_base.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `search_knowledge_base` | RAG semantic search | Azure AI Search, Azure OpenAI |

### Agent Handoffs (handoffs.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `handoff_card_recommendation` | Transfer to card specialist | None (agent routing) |
| `handoff_investment_advisor` | Transfer to investment agent | None (agent routing) |
| `handoff_fraud_specialist` | Transfer to fraud team | None (agent routing) |
| `handoff_compliance_desk` | Transfer to compliance | None (agent routing) |
| `handoff_fnol_agent` | Transfer to claims agent | None (agent routing) |
| `handoff_subro_agent` | Transfer to subrogation agent | None (agent routing) |

All handoff tools have `is_handoff=True` to enable special routing behavior.

### Fraud Detection (fraud.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `analyze_transaction_risk` | Evaluate fraud risk | Cosmos DB, Azure OpenAI |
| `get_fraud_alerts` | Get active fraud alerts | Cosmos DB |
| `flag_suspicious_activity` | Report suspicious transaction | Cosmos DB |
| `verify_transaction_location` | Verify transaction geography | Cosmos DB |
| `get_fraud_history` | Get historical fraud cases | Cosmos DB |

### Compliance (compliance.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `check_kyc_status` | Check KYC verification | Cosmos DB |
| `check_aml_status` | Check AML screening | Cosmos DB |
| `get_regulatory_report` | Generate compliance report | Cosmos DB |
| `log_compliance_event` | Log regulatory event | Cosmos DB |

### Escalation (escalation.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `escalate_to_supervisor` | Route to supervisor queue | Cosmos DB |
| `escalate_emergency` | Emergency escalation | Cosmos DB, ACS Email |
| `create_escalation_ticket` | Create support ticket | Cosmos DB |
| `transfer_call_to_call_center` | Transfer to call center | ACS Call Automation |

### Call Management

| Tool | Description | External Services |
|------|-------------|-------------------|
| `record_voicemail` (voicemail.py) | Record voicemail message | Cosmos DB |
| `retrieve_voicemail` (voicemail.py) | Retrieve voicemail | Cosmos DB |
| `transfer_call` (call_transfer.py) | Queue-based call transfer | ACS Call Automation |

### Fund Transfers (transfer_agency.py)

| Tool | Description | External Services |
|------|-------------|-------------------|
| `initiate_wire_transfer` | Start wire transfer | Cosmos DB |
| `check_transfer_status` | Check transfer status | Cosmos DB |
| `add_beneficiary` | Add transfer beneficiary | Cosmos DB |

---

## External Service Integration

### Azure Communication Services (ACS)

**Purpose:** Email delivery for MFA codes, agreements, and notifications

**Import Pattern:**
```python
try:
    from src.acs.email_service import send_email as send_email_async, is_email_configured
except ImportError:
    send_email_async = None
    is_email_configured = lambda: False
```

**Tools Using ACS Email:**
- `send_mfa_code` - Sends MFA verification codes
- `resend_mfa_code` - Resends expired codes
- `send_esignature_code` - Sends card application agreements
- `send_call_summary` - Emails call summaries to insurance reps
- `escalate_emergency` - Sends emergency notifications

**ACS Call Automation:**
- `transfer_call` - Transfers calls to queue
- `transfer_call_to_call_center` - Routes to call center

**Configuration:**
- Email service requires `AZURE_COMMUNICATION_CONNECTION_STRING`
- Gracefully degrades if not configured (tools return warnings)

### Azure Cosmos DB

**Purpose:** Primary data store for user profiles, claims, policies, transactions

**Import Pattern:**
```python
try:
    from src.cosmosdb.manager import CosmosDBMongoCoreManager as _CosmosManagerImpl
    from src.cosmosdb.config import get_database_name, get_users_collection_name
except Exception:
    _CosmosManagerImpl = None
    def get_database_name() -> str:
        return os.getenv("AZURE_COSMOS_DATABASE_NAME", "audioagentdb")
    def get_users_collection_name() -> str:
        return os.getenv("AZURE_COSMOS_USERS_COLLECTION_NAME", "users")
```

**Collections:**
- **`users`** - Customer profiles, MFA codes, verification status
- **`claims`** - Insurance claims (FNOL, subrogation)
- **`policies`** - Insurance policy data
- **`transactions`** - Banking transactions
- **`sessions`** - Call session state

**Tools Using Cosmos DB:**
- **All authentication tools** - User lookup & verification
- **All banking tools** - Account data, transactions, cards
- **All insurance tools** - Claims, policies, subrogation
- **All fraud tools** - Risk analysis, alerts
- **All compliance tools** - KYC/AML checks

**Manager Resolution:**
```python
def _get_cosmos_manager() -> CosmosDBMongoCoreManager | None:
    """Resolve the shared Cosmos DB client from FastAPI app state."""
    try:
        from apps.artagent.backend import main as backend_main
    except Exception:
        return None
    
    app = getattr(backend_main, "app", None)
    state = getattr(app, "state", None) if app else None
    return getattr(state, "cosmos", None)
```

**Configuration:**
- `AZURE_COSMOS_CONNECTION_STRING` or individual endpoint/key settings
- Database name defaults to `audioagentdb`
- Container names configurable via environment

### Azure Redis Cache

**Purpose:** Temporary MFA code storage, session caching

**Import Pattern:**
```python
try:
    from src.redis.manager import AzureRedisManager
    _REDIS_MANAGER: AzureRedisManager | None = None
    
    def _get_redis_manager() -> AzureRedisManager | None:
        global _REDIS_MANAGER
        if _REDIS_MANAGER is None:
            try:
                _REDIS_MANAGER = AzureRedisManager()
            except Exception as exc:
                logger.warning("Could not initialize Redis manager: %s", exc)
        return _REDIS_MANAGER
except ImportError:
    _get_redis_manager = lambda: None
```

**Tools Using Redis:**
- `send_mfa_code` - Caches MFA codes with TTL
- `verify_mfa_code` - Validates codes against cache
- `resend_mfa_code` - Retrieves cached codes

**Configuration:**
- `AZURE_REDIS_CONNECTION_STRING`
- Falls back to Cosmos DB if Redis unavailable

### Azure AI Search

**Purpose:** RAG knowledge base semantic search

**Tools Using AI Search:**
- `search_knowledge_base` - Hybrid search (vector + keyword)

**Configuration:**
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_KEY`
- `AZURE_SEARCH_INDEX_NAME`

### Azure OpenAI

**Purpose:** Embeddings for RAG, fraud risk scoring

**Tools Using Azure OpenAI:**
- `search_knowledge_base` - Generates query embeddings
- `analyze_transaction_risk` - AI-powered fraud detection

**Configuration:**
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_KEY`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`

---

## Demo Profile Endpoint

The demo profile endpoint (`/api/v1/demo-env`) creates rich, ephemeral user profiles for testing and demonstrations. These profiles are automatically purged after a configurable TTL.

### Endpoint Details

**Location:** `apps/artagent/backend/api/v1/endpoints/demo_env.py`

**Endpoint:** `POST /api/v1/demo-env/create-profile`

### Request Schema

```python
class DemoUserRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone_number: str | None = Field(default=None, pattern=r"^\+\d{10,15}$")
    preferred_channel: Literal["email", "sms"] | None = Field(default=None)
    session_id: str | None = Field(default=None, min_length=5, max_length=120)
    scenario: Literal["banking", "insurance"] = Field(default="banking")
    
    # Insurance-specific fields
    insurance_company_name: str | None = Field(default=None)
    insurance_role: Literal["policyholder", "cc_rep"] | None = Field(default="policyholder")
    test_scenario: Literal[
        "golden_path",           # Full B2B workflow
        "demand_under_review",   # Demand pending
        "demand_paid",           # Demand paid
        "no_demand",             # No demand filed
        "coverage_denied",       # Coverage denied
        "pending_assignment",    # In queue
        "liability_denied",      # Liability denied
        "cvq_open",              # Coverage question open
        "demand_exceeds_limits", # Demand > limits
        "random"                 # Random generation
    ] | None = Field(default=None)
```

### Profile Attributes Created

The endpoint generates a comprehensive `DemoUserProfile` with the following attribute categories:

#### Identity Attributes

```python
client_id: str              # Unique identifier (e.g., "CI000002025")
full_name: str              # User's full name
email: EmailStr             # Email address
phone_number: str | None    # Phone in E.164 format
```

#### Institution Attributes

```python
institution_name: str           # "Contoso Financial Services", "XYMZ Insurance"
company_code: str               # "CI", "GCA", "XYMZ"
company_code_last4: str         # Last 4 digits of company code
authorization_level: str        # "institutional", "executive", "policyholder"
relationship_tier: str          # "Diamond", "Platinum", "Gold", "Standard"
client_type: str                # "institutional"
```

#### Security & Verification Attributes

```python
verification_codes: dict = {
    "ssn_last_4": "1234",
    "employee_id_last_4": "5678",
    "phone_last_4": "9876"
}

mfa_settings: dict = {
    "mfa_enabled": True,
    "default_mfa_method": "email",  # or "sms"
    "backup_methods": ["email"],
    "last_mfa_at": datetime
}
```

#### Compliance Attributes

```python
compliance: dict = {
    "kyc_verified": True,
    "kyc_verification_date": datetime,
    "aml_cleared": True,
    "aml_last_check": datetime,
    "risk_rating": "low",  # "low", "medium", "high"
    "last_compliance_review": datetime,
    "sanctions_screened": True
}
```

#### Customer Intelligence Attributes

This is the richest attribute category, used extensively by jinja templates:

```python
customer_intelligence: dict = {
    "relationship_context": {
        "relationship_tier": "Platinum Honors",
        "years_with_institution": 5,
        "total_products": 4,
        "cross_sell_opportunities": [...],
        "loyalty_score": 92
    },
    "bank_profile": {
        "primary_account": "checking",
        "current_balance": 265432.18,
        "average_balance": 198765.43,
        "accountTenureYears": 5,
        "overdraft_count": 0,
        "credit_score": 780
    },
    "retirement_profile": {
        "has_401k": True,
        "401k_balance": 185000.00,
        "previous_employer_401k": 67500.00,
        "ira_accounts": [...],
        "estimated_retirement_date": "2045-06-15"
    },
    "card_profile": {
        "cards": [
            {
                "card_name": "Platinum Travel Card",
                "card_type": "travel",
                "balance": 2450.00,
                "limit": 25000,
                "annual_fee": 95,
                "rewards_balance": 18500
            }
        ],
        "total_credit_limit": 25000,
        "credit_utilization": 0.098
    },
    "memory_score": {
        "transaction_patterns": [...],
        "spending_velocity": "moderate",
        "communication_style": "business_focused",  # or "relationship_oriented"
        "memory_score": 87
    },
    "fraud_context": {
        "risk_profile": "low",
        "typical_spending_range": "$1,000 - $15,000",
        "typical_locations": ["Seattle, WA", "San Francisco, CA"],
        "typical_merchants": ["Starbucks", "AWS", "Delta Airlines"],
        "security_preferences": {
            "preferred_verification": "Email",
            "notification_urgency": "Immediate",
            "card_replacement_speed": "Expedited"
        }
    },
    "preferences": {
        "preferredContactMethod": "phone",  # or "email", "sms", "app"
        "communicationStyle": "business_focused",
        "languagePreference": "en-US"
    },
    "conversation_context": {
        "known_preferences": [
            "Enjoys step-by-step walk-throughs.",
            "Wants rationale behind each security control."
        ],
        "suggested_talking_points": [
            "Your vigilance keeps operations running smoothly.",
            "Gold tier support remains prioritized for you."
        ]
    },
    "active_alerts": [
        {
            "type": "account_optimization",
            "message": "Demo identity issued. Data purges automatically within 24 hours.",
            "priority": "info"
        }
    ]
}
```

#### Insurance-Specific Attributes

For `scenario="insurance"`, additional attributes are created:

```python
insurance_profile: dict = {
    "claims": [
        {
            "claim_number": "CLM-2024-GOLDEN",
            "loss_date": "2024-01-15",
            "claim_type": "collision",
            "status": "open",
            "demand_status": "under_review",
            "demand_amount": 15000.00,
            "liability_decision": "pending",
            "coverage_status": "confirmed",
            "insured_vehicle": {
                "year": 2022,
                "make": "Toyota",
                "model": "Camry",
                "vin": "1HGBH..."
            },
            "claimant_carrier": "Fabrikam Insurance"
        }
    ],
    "policies": [
        {
            "policy_number": "POL-2024-001",
            "policy_type": "auto",
            "status": "active",
            "premium": 1200.00,
            "coverage_limits": {
                "bodily_injury": 100000,
                "property_damage": 50000
            }
        }
    ]
}
```

### Banking Scenario Templates

The endpoint uses predefined templates for consistent profile generation:

```python
BANKING_PROFILE_TEMPLATES = (
    {
        "key": "contoso_exec",
        "institution_name": "Contoso Financial Services",
        "company_code_prefix": "CI",
        "relationship_tier": "Diamond",
        "authorization_level": "executive",
        "max_txn_range": (100_000, 500_000),
        "conversation_profile": "executive_banking"
    },
    {
        "key": "global_advisors",
        "institution_name": "Global Capital Advisors",
        "company_code_prefix": "GCA",
        "relationship_tier": "Platinum Honors",
        "authorization_level": "institutional",
        "max_txn_range": (50_000, 250_000),
        "conversation_profile": "relationship_banking"
    }
)
```

### Insurance Scenario Templates

```python
INSURANCE_PROFILE_TEMPLATES = (
    {
        "key": "xymz_insurance",
        "institution_name": "XYMZ Insurance",
        "company_code_prefix": "XYMZ",
        "authorization_level": "policyholder",
        "relationship_tier": "Preferred",
        "default_phone": "+18885551234",
        "default_mfa_method": "email"
    },
    {
        "key": "contoso_insurance",
        "institution_name": "Contoso Insurance",
        "company_code_prefix": "CI",
        "authorization_level": "policyholder",
        "relationship_tier": "Standard",
        "default_phone": "+18005559876",
        "default_mfa_method": "email"
    }
)
```

### Test Scenario Support

The endpoint supports **predefined test scenarios** for consistent edge case testing:

```python
TEST_SCENARIOS = {
    "golden_path": {
        "claim_number": "CLM-2024-GOLDEN",
        "demand_status": "under_review",
        "liability_decision": "pending",
        "coverage_status": "confirmed",
        "payment_status": "pending"
    },
    "demand_paid": {
        "claim_number": "CLM-2024-005678",
        "demand_status": "paid",
        "liability_decision": "80% at fault",
        "payment_amount": 12000.00,
        "payment_date": "2024-02-15"
    },
    "coverage_denied": {
        "claim_number": "CLM-2024-003456",
        "coverage_status": "denied",
        "denial_reason": "Policy lapsed - premium not paid",
        "effective_date": "2023-12-01"
    }
}
```

---

## Jinja Template Parameters

Jinja templates for agent prompts consume attributes from the demo profile and session context.

### Template Locations

```
apps/artagent/backend/registries/agentstore/
├── banking_concierge/prompt.jinja
├── fraud_agent/prompt.jinja
├── compliance_desk/prompt.jinja
├── fnol_agent/prompt.jinja
├── subro_agent/prompt.jinja
├── auth_agent/prompt.jinja
├── policy_advisor/prompt.jinja
└── investment_advisor/prompt.jinja
```

### Common Template Variables

#### Session & Agent Context

```jinja
{{ agent_name }}              # Current agent name
{{ institution_name }}        # Financial institution name
{{ active_agent }}            # Current active agent ID
{{ previous_agent }}          # Previous agent (for handoffs)
{{ handoff_context }}         # Context passed during handoff
{{ session_profile }}         # Full DemoUserProfile object
```

#### Identity & Personalization

```jinja
{{ session_profile.full_name }}              # "John Smith"
{{ session_profile.client_id }}              # "CI000002025"
{{ session_profile.email }}                  # "john.smith@contoso.com"
{{ session_profile.phone_number }}           # "+14255551234"
{{ session_profile.relationship_tier }}      # "Platinum Honors"
{{ session_profile.authorization_level }}    # "executive"
```

#### Customer Intelligence (Nested Access)

```jinja
{# Safe extraction pattern #}
{% set ci = session_profile.customer_intelligence | default({}) %}
{% set rel_ctx = ci.relationship_context | default({}) %}
{% set prefs = ci.preferences | default({}) %}
{% set bank = ci.bank_profile | default({}) %}
{% set conv_ctx = ci.conversation_context | default({}) %}

# Then use extracted values:
{{ rel_ctx.relationship_tier }}              # "Platinum Honors"
{{ rel_ctx.years_with_institution }}         # 5
{{ prefs.preferredContactMethod }}           # "phone"
{{ prefs.communicationStyle }}               # "business_focused"
{{ bank.current_balance }}                   # 265432.18
{{ bank.accountTenureYears }}                # 5
```

#### Personalization Examples

**Greeting with Tier:**
```jinja
{% if session_profile %}
- Greet warmly by first name: "Hi {{ session_profile.full_name.split()[0] }}, I'm {{ agent_name | default('your banking assistant') }}."
- Reference tier: "As a {{ rel_ctx.relationship_tier }} customer, you have priority access."
{% endif %}
```

**Conditional Benefits:**
```jinja
{% set tier = rel_ctx.relationship_tier | default('Standard') %}
{% set tier_lower = tier | lower %}
{% if 'diamond' in tier_lower %}
- "As a {{ tier }} member, you have UNLIMITED non-network ATM fee waivers."
{% elif 'platinum' in tier_lower %}
- "As a {{ tier }} member, you get 1 non-network ATM fee waiver per cycle."
{% elif 'gold' in tier_lower %}
- "As a {{ tier }} member, I can refund this as a courtesy."
{% else %}
- "Based on your account history, I can refund that as a courtesy."
{% endif %}
```

**Suggested Talking Points:**
```jinja
{% if conv_ctx.suggested_talking_points %}
SUGGESTED TALKING POINTS (use naturally in conversation):
{% for point in conv_ctx.suggested_talking_points %}
   - {{ point }}
{% endfor %}
{% endif %}
```

**Active Alerts:**
```jinja
{% if ci.active_alerts %}
ACTIVE ALERTS:
{% for alert in ci.active_alerts %}
   - [{{ alert.priority | default('INFO') | upper }}] {{ alert.message | default('') }}
     Action: {{ alert.action | default('Review') }}
{% endfor %}
{% endif %}
```

### Banking Concierge Template Example

From `apps/artagent/backend/registries/agentstore/banking_concierge/prompt.jinja`:

```jinja
You are **{{ agent_name | default('the banking concierge') }}**, {{ institution_name | default('the bank') }}'s intelligent banking assistant.

{% if session_profile %}
# CUSTOMER PROFILE (Pre-loaded)
- Name: {{ session_profile.full_name }}
- Client ID: {{ session_profile.client_id }}
- Institution: {{ session_profile.institution_name }}
- Relationship Tier: {{ rel_ctx.relationship_tier | default('Standard') }}
- Primary Channel: {{ prefs.preferredContactMethod | default('phone') }}
- Account Balance: ${{ "{:,.2f}".format(bank.current_balance | default(0)) }}
- Accounts Tenure: {{ bank.accountTenureYears | default(1) }} years

# PERSONALIZATION
- Communication Style: {{ prefs.communicationStyle }}
- Spending Range: {{ ci.fraud_context.typical_spending_range }}
- Typical Locations: {{ ci.fraud_context.typical_locations | join(', ') }}
{% endif %}
```

### Discovering Existing Template Parameters

To find all parameters used in a template:

1. **View the template file:**
   ```bash
   cat apps/artagent/backend/registries/agentstore/banking_concierge/prompt.jinja | grep -o "{{ [^}]* }}" | sort -u
   ```

2. **Check profile creation code:**
   ```bash
   # Find where attributes are created in demo_env.py
   grep -A 5 "customer_intelligence\[" apps/artagent/backend/api/v1/endpoints/demo_env.py
   ```

3. **Trace attribute usage:**
   ```bash
   # Find which templates use a specific attribute
   grep -r "session_profile.relationship_tier" apps/artagent/backend/registries/agentstore/
   ```

---

## Extending the Demo Profile Endpoint

### Adding New Jinja Template Parameters

Follow these steps to add a new parameter accessible in templates:

#### Step 1: Add Attribute to Profile Schema

Edit `apps/artagent/backend/api/v1/endpoints/demo_env.py`:

```python
class DemoUserProfile(BaseModel):
    # ... existing fields ...
    
    # Add new field
    preferred_timezone: str | None = Field(
        default=None,
        description="User's preferred timezone for scheduling"
    )
```

#### Step 2: Generate Attribute in Profile Builder

In the `_build_profile()` or `_build_insurance_profile()` function:

```python
def _build_profile(payload: DemoUserRequest, rng: Random) -> DemoUserProfile:
    # ... existing code ...
    
    # Add timezone generation
    timezones = ["America/Los_Angeles", "America/New_York", "America/Chicago"]
    preferred_timezone = rng.choice(timezones)
    
    return DemoUserProfile(
        # ... existing fields ...
        preferred_timezone=preferred_timezone,
        # ... rest of fields ...
    )
```

#### Step 3: Add to Customer Intelligence (Optional)

For nested attributes in `customer_intelligence`:

```python
customer_intelligence = {
    # ... existing categories ...
    
    "scheduling_preferences": {
        "preferred_timezone": preferred_timezone,
        "preferred_call_time": rng.choice(["morning", "afternoon", "evening"]),
        "weekend_availability": rng.choice([True, False])
    }
}
```

#### Step 4: Use in Jinja Template

In your agent template (e.g., `prompt.jinja`):

```jinja
{% if session_profile.preferred_timezone %}
# SCHEDULING CONTEXT
- User Timezone: {{ session_profile.preferred_timezone }}
- Best Call Time: {{ ci.scheduling_preferences.preferred_call_time }}
{% endif %}
```

### Adding New Request Parameters

To add parameters users can specify when creating profiles:

#### Step 1: Update Request Schema

```python
class DemoUserRequest(BaseModel):
    # ... existing fields ...
    
    # Add new parameter
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] | None = Field(
        default="moderate",
        description="Investment risk tolerance level"
    )
```

#### Step 2: Use Parameter in Profile Generation

```python
def _build_profile(payload: DemoUserRequest, rng: Random) -> DemoUserProfile:
    # ... existing code ...
    
    # Use provided risk tolerance or generate
    risk_tolerance = payload.risk_tolerance or rng.choice(["conservative", "moderate", "aggressive"])
    
    customer_intelligence["investment_preferences"] = {
        "risk_tolerance": risk_tolerance,
        "asset_allocation": _generate_allocation(risk_tolerance),
        "rebalancing_frequency": "quarterly" if risk_tolerance == "aggressive" else "annually"
    }
```

### Adding New Scenario Templates

To add support for new industry scenarios:

#### Step 1: Define Template Constants

```python
# In demo_env.py

HEALTHCARE_PROFILE_TEMPLATES = (
    {
        "key": "patient_portal",
        "institution_name": "Contoso Health",
        "company_code_prefix": "CH",
        "authorization_level": "patient",
        "relationship_tier": "Premium",
        "default_phone": "+18005551234",
        "default_mfa_method": "email"
    },
    {
        "key": "provider_network",
        "institution_name": "Fabrikam Medical",
        "company_code_prefix": "FM",
        "authorization_level": "provider",
        "relationship_tier": "Network",
        "default_phone": "+18885559876",
        "default_mfa_method": "sms"
    }
)
```

#### Step 2: Add Scenario-Specific Builder

```python
def _build_healthcare_profile(payload: DemoUserRequest, rng: Random) -> DemoUserProfile:
    """Build healthcare scenario profile."""
    template = rng.choice(HEALTHCARE_PROFILE_TEMPLATES)
    
    # Generate healthcare-specific attributes
    healthcare_profile = {
        "patient_id": f"PAT-{rng.randint(100000, 999999)}",
        "insurance_provider": rng.choice(["Blue Cross", "Aetna", "UnitedHealth"]),
        "primary_care_physician": rng.choice(["Dr. Smith", "Dr. Johnson"]),
        "upcoming_appointments": [
            {
                "date": "2024-03-15",
                "provider": "Dr. Smith",
                "type": "Annual Physical"
            }
        ],
        "medications": [
            {
                "name": "Lisinopril",
                "dosage": "10mg",
                "frequency": "Daily"
            }
        ],
        "allergies": ["Penicillin"]
    }
    
    return DemoUserProfile(
        client_id=f"{template['company_code_prefix']}{rng.randint(1000, 9999)}",
        full_name=payload.full_name,
        # ... standard fields ...
        customer_intelligence={
            "healthcare_profile": healthcare_profile,
            # ... other intelligence ...
        }
    )
```

#### Step 3: Update Request Schema

```python
class DemoUserRequest(BaseModel):
    # ... existing fields ...
    
    scenario: Literal["banking", "insurance", "healthcare"] = Field(
        default="banking",
        description="Demo scenario type"
    )
```

#### Step 4: Route to Correct Builder

```python
@router.post("/create-profile")
async def create_demo_profile(payload: DemoUserRequest) -> DemoUserProfile:
    rng = Random()
    
    if payload.scenario == "banking":
        profile = _build_profile(payload, rng)
    elif payload.scenario == "insurance":
        profile = _build_insurance_profile(payload, rng)
    elif payload.scenario == "healthcare":
        profile = _build_healthcare_profile(payload, rng)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {payload.scenario}")
    
    # Store in Cosmos DB...
    return profile
```

### Adding Mock Data for Testing

To add test scenarios like the insurance `test_scenario` parameter:

#### Step 1: Define Mock Data Constants

```python
# In a constants file or demo_env.py

MOCK_INVESTMENT_SCENARIOS = {
    "high_performer": {
        "portfolio_value": 850000,
        "ytd_return": 0.185,  # 18.5%
        "asset_allocation": {
            "stocks": 0.70,
            "bonds": 0.20,
            "cash": 0.10
        },
        "top_holdings": [
            {"symbol": "AAPL", "value": 125000, "return": 0.32},
            {"symbol": "MSFT", "value": 110000, "return": 0.28}
        ]
    },
    "market_downturn": {
        "portfolio_value": 425000,
        "ytd_return": -0.12,  # -12%
        "asset_allocation": {
            "stocks": 0.40,
            "bonds": 0.40,
            "cash": 0.20
        },
        "margin_call_risk": True,
        "advisor_review_required": True
    }
}
```

#### Step 2: Add Request Parameter

```python
class DemoUserRequest(BaseModel):
    # ... existing fields ...
    
    investment_scenario: Literal[
        "high_performer",
        "market_downturn",
        "conservative_growth",
        "random"
    ] | None = Field(
        default="random",
        description="For banking scenario: select specific investment test case"
    )
```

#### Step 3: Apply Mock Data in Builder

```python
def _build_profile(payload: DemoUserRequest, rng: Random) -> DemoUserProfile:
    # ... existing code ...
    
    # Use predefined scenario if specified
    if payload.investment_scenario and payload.investment_scenario != "random":
        if payload.investment_scenario in MOCK_INVESTMENT_SCENARIOS:
            investment_data = MOCK_INVESTMENT_SCENARIOS[payload.investment_scenario]
        else:
            investment_data = _generate_random_investment_data(rng)
    else:
        investment_data = _generate_random_investment_data(rng)
    
    customer_intelligence["investment_profile"] = investment_data
```

### Modifying Profile TTL

Profiles auto-purge after TTL. To customize:

```python
# In demo_env.py

# Default TTL (hours)
DEFAULT_TTL_HOURS = 24

@router.post("/create-profile")
async def create_demo_profile(
    payload: DemoUserRequest,
    ttl_hours: int = Query(default=DEFAULT_TTL_HOURS, ge=1, le=168)  # 1-168 hours
) -> DemoUserProfile:
    # ... profile generation ...
    
    # Store with custom TTL
    ttl_seconds = ttl_hours * 3600
    await cosmos_manager.upsert_document(
        document=profile.model_dump(),
        ttl=ttl_seconds
    )
```

---

## Best Practices

### Tool Development

1. **Always use lazy imports** for external services:
   ```python
   try:
       from src.cosmosdb.manager import CosmosDBMongoCoreManager
   except ImportError:
       CosmosDBMongoCoreManager = None
   ```

2. **Provide graceful degradation**:
   ```python
   if not is_email_configured():
       return {
           "status": "warning",
           "message": "Email service not configured. Code logged to console."
       }
   ```

3. **Use structured logging**:
   ```python
   logger.info(
       "Tool executed",
       extra={
           "tool_name": "get_user_profile",
           "client_id": client_id,
           "execution_time_ms": elapsed
       }
   )
   ```

4. **Include telemetry spans**:
   ```python
   from opentelemetry import trace
   
   tracer = trace.get_tracer(__name__)
   
   async def get_user_profile_executor(args: dict) -> dict:
       with tracer.start_as_current_span(
           "tool.get_user_profile",
           attributes={"client_id": args["client_id"]}
       ):
           # ... implementation ...
   ```

5. **Validate tool arguments**:
   ```python
   if not client_id or len(client_id) < 5:
       raise ValueError("client_id must be at least 5 characters")
   ```

### Template Development

1. **Use safe extraction for nested dicts**:
   ```jinja
   {% set ci = session_profile.customer_intelligence | default({}) %}
   {% set prefs = ci.preferences | default({}) %}
   ```

2. **Provide fallback defaults**:
   ```jinja
   {{ prefs.preferredContactMethod | default('phone') }}
   ```

3. **Check existence before iteration**:
   ```jinja
   {% if ci.active_alerts %}
   {% for alert in ci.active_alerts %}
      - {{ alert.message }}
   {% endfor %}
   {% endif %}
   ```

4. **Format numbers consistently**:
   ```jinja
   ${{ "{:,.2f}".format(bank.current_balance | default(0)) }}
   ```

### Demo Profile Development

1. **Use consistent naming conventions**:
   - `relationship_tier` (not `tier` or `customer_tier`)
   - `client_id` (not `user_id` or `customer_id`)
   - `institution_name` (not `bank_name` or `company_name`)

2. **Generate realistic data**:
   ```python
   # Use Random with seed for reproducibility in tests
   rng = Random(f"{payload.full_name}{payload.email}")
   ```

3. **Support both random and deterministic generation**:
   ```python
   if payload.test_scenario and payload.test_scenario != "random":
       data = MOCK_SCENARIOS[payload.test_scenario]
   else:
       data = _generate_random_data(rng)
   ```

4. **Document all attributes** in docstrings:
   ```python
   class DemoUserProfile(BaseModel):
       """Demo user profile with rich attributes for testing.
       
       Attributes:
           client_id: Unique customer identifier (e.g., "CI000002025")
           institution_name: Financial institution name (e.g., "Contoso Financial")
           relationship_tier: Customer tier (Diamond, Platinum, Gold, Standard)
           ...
       """
   ```

5. **Validate profile completeness** before returning:
   ```python
   # Ensure required nested attributes exist
   assert "customer_intelligence" in profile.model_dump()
   assert "bank_profile" in profile.customer_intelligence
   ```

### Testing Tools

1. **Mock external services in unit tests**:
   ```python
   @pytest.fixture
   def mock_cosmos():
       with patch("apps.artagent.backend.registries.toolstore.banking.banking._get_cosmos_manager") as mock:
           mock.return_value = MockCosmosManager()
           yield mock
   ```

2. **Test with demo profiles**:
   ```python
   # Create test profile
   profile = await create_demo_profile(
       DemoUserRequest(
           full_name="Test User",
           email="test@example.com",
           scenario="banking"
       )
   )
   
   # Test tool execution
   result = await execute_tool(
       "get_user_profile",
       {"client_id": profile.client_id}
   )
   ```

3. **Validate tool schemas**:
   ```python
   def test_tool_schema():
       schema = get_user_profile_schema
       assert "name" in schema
       assert "description" in schema
       assert "parameters" in schema
       assert "required" in schema["parameters"]
   ```

---

## Summary

The ART Voice Agent tools system provides a flexible, extensible framework for building AI-powered voice applications:

- **40+ tools** across authentication, banking, insurance, fraud, compliance, and more
- **External service integration** with Azure Communication Services, Cosmos DB, Redis, AI Search, and OpenAI
- **Rich demo profiles** with 100+ attributes for realistic testing
- **Jinja template system** for personalized agent prompts
- **Extensible architecture** for adding new scenarios, parameters, and tools

For implementation details, see the source code in:
- `apps/artagent/backend/registries/toolstore/`
- `apps/artagent/backend/api/v1/endpoints/demo_env.py`
- `apps/artagent/backend/registries/agentstore/*/prompt.jinja`
