"""
Investment and retirement planning tools for Bank of America voice assistant.

Implements 401(k) rollover guidance, direct deposit setup, contribution modeling,
and financial advisor handoff for the Investment Advisor agent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from utils.ml_logging import get_logger
from src.cosmosdb.manager import CosmosDBMongoCoreManager

# Import centralized constants
from ..constants.banking_constants import (
    INSTITUTION_CONFIG,
    TAX_WITHHOLDING_INDIRECT_ROLLOVER,
    EARLY_WITHDRAWAL_PENALTY,
    ESTIMATED_TAX_BRACKET,
    ROLLOVER_OPTIONS,
)

logger = get_logger("investment_tools")

# Initialize Cosmos DB manager
_banking_cosmos_manager = None

def get_banking_users_manager() -> CosmosDBMongoCoreManager:
    """Get or create the banking services Cosmos DB manager."""
    global _banking_cosmos_manager
    if _banking_cosmos_manager is None:
        _banking_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="banking_services_db",
            collection_name="users"
        )
    return _banking_cosmos_manager


def _json(
    success: bool,
    message: str,
    **extras: Any,
) -> Dict[str, Any]:
    """Helper to build consistent JSON responses."""
    result = {"success": success, "message": message}
    result.update(extras)
    return result


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# ACCOUNT & DIRECT DEPOSIT TOOLS
# ═══════════════════════════════════════════════════════════════════


class GetAccountRoutingInfoArgs(TypedDict, total=False):
    """Input schema for get_account_routing_info."""
    client_id: str


async def get_account_routing_info(args: GetAccountRoutingInfoArgs) -> Dict[str, Any]:
    """
    Retrieve account and routing numbers for direct deposit setup.
    
    Returns primary checking account details needed for employer direct deposit forms.
    Customer can use this information to set up payroll with new employer.
    
    Args:
        client_id: Unique customer identifier
    
    Returns:
        Dict with account_number_last4, routing_number, account_type, and bank details
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info("🏦 Fetching account routing info | client_id=%s", client_id)
        
        # Fetch customer profile from Cosmos DB
        try:
            users_cosmos = get_banking_users_manager()
            customer = await asyncio.to_thread(
                users_cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error: {db_error}")
            return _json(False, "Unable to retrieve account information.")
        
        if not customer:
            logger.warning(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer profile not found.")
        
        # Extract bank profile data
        bank_profile = customer.get("customer_intelligence", {}).get("bank_profile", {})
        routing = bank_profile.get("routing_number", INSTITUTION_CONFIG.routing_number)
        acct_last4 = bank_profile.get("account_number_last4", "****")
        acct_id = bank_profile.get("primaryCheckingAccountId", "unknown")
        
        logger.info(
            "✅ Account info retrieved | client=%s acct=****%s routing=%s",
            client_id, acct_last4, routing
        )
        
        return _json(
            True,
            "Retrieved account and routing information for direct deposit.",
            account_number_last4=acct_last4,
            routing_number=routing,
            account_id=acct_id,
            account_type="checking",
            bank_name=INSTITUTION_CONFIG.name,
            swift_code=INSTITUTION_CONFIG.swift_code,
            note="Provide these details to your employer for direct deposit setup."
        )
    
    except Exception as error:
        logger.error(f"❌ Failed to retrieve account routing info: {error}", exc_info=True)
        return _json(False, "Unable to retrieve account information at this time.")


# ═══════════════════════════════════════════════════════════════════
# 401(K) & RETIREMENT TOOLS
# ═══════════════════════════════════════════════════════════════════


class Get401kDetailsArgs(TypedDict, total=False):
    """Input schema for get_401k_details."""
    client_id: str


async def get_401k_details(args: Get401kDetailsArgs) -> Dict[str, Any]:
    """
    Retrieve customer's current 401(k) details and retirement accounts.
    
    Returns information about current employer 401(k), previous employer 401(k)s,
    IRAs, contribution rates, employer match, and vesting status.
    
    Args:
        client_id: Unique customer identifier
    
    Returns:
        Dict with retirement account details, balances, contributions, and rollover opportunities
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info("💼 Fetching 401(k) details | client_id=%s", client_id)
        
        # Fetch customer profile
        try:
            users_cosmos = get_banking_users_manager()
            customer = await asyncio.to_thread(
                users_cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error: {db_error}")
            return _json(False, "Unable to retrieve retirement account information.")
        
        if not customer:
            logger.warning(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer profile not found.")
        
        # Extract retirement profile
        retirement = customer.get("customer_intelligence", {}).get("retirement_profile", {})
        employment = customer.get("customer_intelligence", {}).get("employment", {})
        
        accounts = retirement.get("retirement_accounts", [])
        merrill_accounts = retirement.get("merrill_accounts", [])
        plan_features = retirement.get("plan_features", {})
        
        current_employer = employment.get("currentEmployerName", "Unknown")
        uses_bofa_401k = employment.get("usesBofAFor401k", False)
        
        logger.info(
            "✅ 401(k) details retrieved | client=%s accounts=%d merrill=%d",
            client_id, len(accounts), len(merrill_accounts)
        )
        
        return _json(
            True,
            f"Retrieved retirement account details for {current_employer} and any previous accounts.",
            retirement_accounts=accounts,
            merrill_accounts=merrill_accounts,
            current_employer=current_employer,
            uses_bofa_for_401k=uses_bofa_401k,
            employer_match_pct=plan_features.get("currentEmployerMatchPct", 0),
            has_401k_pay=plan_features.get("has401kPayOnCurrentPlan", False),
            rollover_eligible=plan_features.get("rolloverEligible", False),
            risk_profile=retirement.get("risk_profile", "moderate"),
            investment_knowledge=retirement.get("investmentKnowledgeLevel", "beginner")
        )
    
    except Exception as error:
        logger.error(f"❌ Failed to retrieve 401(k) details: {error}", exc_info=True)
        return _json(False, "Unable to retrieve retirement account information at this time.")


class GetRolloverOptionsArgs(TypedDict, total=False):
    """Input schema for get_rollover_options."""
    client_id: str
    previous_employer: Optional[str]


async def get_rollover_options(args: GetRolloverOptionsArgs) -> Dict[str, Any]:
    """
    Present 401(k) rollover options with pros/cons for each choice.
    
    Explains the 4 main options for handling a previous employer's 401(k):
    1. Leave it in old employer's plan
    2. Roll over to new employer's 401(k)
    3. Roll over to an IRA
    4. Cash out (not recommended)
    
    Args:
        client_id: Unique customer identifier
        previous_employer: Name of previous employer (optional, for context)
    
    Returns:
        Dict with detailed rollover options tailored to customer's situation
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        previous_employer = (args.get("previous_employer") or "").strip()
        
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info(
            "📊 Presenting rollover options | client=%s prev_employer=%s",
            client_id, previous_employer or "unspecified"
        )
        
        # Fetch customer profile to tailor recommendations
        try:
            users_cosmos = get_banking_users_manager()
            customer = await asyncio.to_thread(
                users_cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error: {db_error}")
            return _json(False, "Unable to retrieve customer information.")
        
        if not customer:
            logger.warning(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer profile not found.")
        
        # Extract context for personalization
        employment = customer.get("customer_intelligence", {}).get("employment", {})
        retirement = customer.get("customer_intelligence", {}).get("retirement_profile", {})
        
        current_employer = employment.get("currentEmployerName", "your new employer")
        uses_bofa_401k = employment.get("usesBofAFor401k", False)
        plan_features = retirement.get("plan_features", {})
        has_401k_pay = plan_features.get("has401kPayOnCurrentPlan", False)
        
        # Build rollover options
        options = [
            {
                "option_id": "leave_in_old_plan",
                "name": "Leave it in your old employer's plan",
                "description": "Your money continues to grow tax-deferred with no action required.",
                "pros": [
                    "No immediate action needed",
                    "Funds remain tax-deferred",
                    "May have access to institutional investment options"
                ],
                "cons": [
                    "Cannot make new contributions",
                    "May have limited investment choices",
                    "Could face higher fees",
                    "Multiple accounts to track if you change jobs again"
                ],
                "best_for": "Those who like their current plan's investment options and fees",
                "recommended": False
            },
            {
                "option_id": "roll_to_new_401k",
                "name": f"Roll over to {current_employer}'s 401(k)",
                "description": "Consolidate your retirement savings in one place with your new employer.",
                "pros": [
                    "Consolidates retirement savings in one account",
                    "May offer lower fees and better investment options",
                    "Easier to manage and track",
                    "Continues tax-deferred growth",
                    "Access to employer match on future contributions"
                ],
                "cons": [
                    "Investment options limited to new plan's offerings",
                    "May have to wait for new plan's enrollment period"
                ],
                "best_for": "Those who want simplicity and their new employer has a good plan",
                "recommended": uses_bofa_401k,  # Recommend if new employer uses BofA
                "special_features": [
                    "401(k) Pay available - converts savings to steady paycheck in retirement"
                ] if has_401k_pay else []
            },
            {
                "option_id": "roll_to_ira",
                "name": "Roll over to an IRA (Individual Retirement Account)",
                "description": "Move funds to an IRA for maximum control and investment flexibility.",
                "pros": [
                    "Widest range of investment options",
                    "More control over your money",
                    "Can choose between Traditional IRA or Roth IRA",
                    "No employer plan restrictions",
                    "Potential for lower fees"
                ],
                "cons": [
                    "Must actively manage investments",
                    "Roth conversion triggers immediate taxes on converted amount",
                    "No employer match (personal savings only)"
                ],
                "best_for": "Those who want maximum investment flexibility and control",
                "recommended": not uses_bofa_401k,  # Recommend if new employer doesn't use BofA
                "tax_note": "Traditional IRA rollover is tax-free. Roth IRA conversion is taxable but offers tax-free withdrawals in retirement."
            },
            {
                "option_id": "cash_out",
                "name": "Cash out (not recommended)",
                "description": "Withdraw funds now, but face significant tax consequences.",
                "pros": [
                    "Immediate access to cash"
                ],
                "cons": [
                    "Full amount added to taxable income for the year",
                    "10% early withdrawal penalty if under age 59½",
                    "Loses years of tax-deferred growth",
                    "Significantly reduces retirement savings"
                ],
                "best_for": "Emergency situations only - strongly discouraged",
                "recommended": False,
                "warning": "This option typically results in losing 30-40% of your balance to taxes and penalties."
            }
        ]
        
        logger.info("✅ Rollover options presented | client=%s options=%d", client_id, len(options))
        
        return _json(
            True,
            "Here are your rollover options for your previous employer's 401(k).",
            options=options,
            current_employer=current_employer,
            previous_employer=previous_employer or "your previous employer",
            uses_bofa_for_new_401k=uses_bofa_401k,
            has_401k_pay_benefit=has_401k_pay,
            next_steps="Choose the option that best fits your financial goals. I can explain any of these in more detail or connect you with a financial advisor."
        )
    
    except Exception as error:
        logger.error(f"❌ Failed to present rollover options: {error}", exc_info=True)
        return _json(False, "Unable to present rollover options at this time.")


class CalculateTaxImpactArgs(TypedDict, total=False):
    """Input schema for calculate_tax_impact."""
    client_id: str
    rollover_type: str  # "direct_rollover", "indirect_rollover", "roth_conversion", "cash_out"
    amount: Optional[float]


async def calculate_tax_impact(args: CalculateTaxImpactArgs) -> Dict[str, Any]:
    """
    Calculate tax implications of different 401(k) rollover strategies.
    
    Explains tax consequences for:
    - Direct rollover (no taxes)
    - Indirect rollover (20% withholding, 60-day rule)
    - Roth conversion (taxable as income)
    - Cash out (taxes + 10% penalty)
    
    Args:
        client_id: Unique customer identifier
        rollover_type: Type of rollover (direct_rollover, indirect_rollover, roth_conversion, cash_out)
        amount: 401(k) balance amount (optional, for precise calculations)
    
    Returns:
        Dict with tax impact details, withholding amounts, and recommendations
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        rollover_type = (args.get("rollover_type") or "").strip().lower()
        amount = args.get("amount")
        
        if not client_id:
            return _json(False, "client_id is required.")
        if not rollover_type:
            return _json(False, "rollover_type is required.")
        
        logger.info(
            "💰 Calculating tax impact | client=%s type=%s amount=%s",
            client_id, rollover_type, amount
        )
        
        # Fetch customer profile
        try:
            users_cosmos = get_banking_users_manager()
            customer = await asyncio.to_thread(
                users_cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error: {db_error}")
            return _json(False, "Unable to retrieve customer information.")
        
        if not customer:
            logger.warning(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer profile not found.")
        
        # Get 401(k) balance if not provided
        if amount is None:
            retirement = customer.get("customer_intelligence", {}).get("retirement_profile", {})
            accounts = retirement.get("retirement_accounts", [])
            # Find previous employer 401(k) (status != "current_employer_plan")
            prev_accounts = [a for a in accounts if a.get("status") != "current_employer_plan"]
            if prev_accounts:
                amount = prev_accounts[0].get("estimatedBalance", 50000)
            else:
                amount = 50000  # Default estimate
        
        # Calculate tax impact based on rollover type using constants
        indirect_withholding = TAX_WITHHOLDING_INDIRECT_ROLLOVER
        early_penalty = EARLY_WITHDRAWAL_PENALTY
        tax_bracket = ESTIMATED_TAX_BRACKET
        
        tax_scenarios = {
            "direct_rollover": {
                "name": "Direct Rollover",
                "description": "Funds transfer directly from old 401(k) to new 401(k) or IRA.",
                "tax_withholding": 0,
                "penalty": 0,
                "total_taxes": 0,
                "net_amount": amount,
                "timeline": "No tax deadline - funds remain tax-deferred",
                "recommendation": "Highly recommended - avoids all taxes and penalties",
                "steps": [
                    "Contact your previous plan administrator",
                    "Request a direct rollover to your new account",
                    "Funds transfer directly - you never touch the money",
                    "No taxes owed, no forms to file"
                ]
            },
            "indirect_rollover": {
                "name": "Indirect Rollover",
                "description": "Check issued to you, then you deposit into new account within 60 days.",
                "tax_withholding": amount * indirect_withholding,
                "penalty": 0,
                "total_taxes": 0,
                "net_amount": amount * (1 - indirect_withholding),  # You receive 80%, need to deposit full 100%
                "timeline": "60 days to complete rollover or face taxes + penalty",
                "recommendation": "Not recommended - complicated and risky",
                "warning": f"You'll receive ${amount * (1 - indirect_withholding):,.2f} ({int((1 - indirect_withholding) * 100)}% of ${amount:,.2f}) but must deposit the full ${amount:,.2f} within 60 days to avoid taxes. You need to come up with the missing ${amount * indirect_withholding:,.2f} from other sources.",
                "steps": [
                    f"Old plan sends you a check for {int((1 - indirect_withholding) * 100)}% of balance",
                    "You have 60 days to deposit FULL amount into new account",
                    "If you miss deadline or deposit less, IRS treats it as withdrawal",
                    f"Withheld {int(indirect_withholding * 100)}% refunded when you file taxes next year"
                ]
            },
            "roth_conversion": {
                "name": "Roth IRA Conversion",
                "description": "Convert traditional 401(k) to Roth IRA (after-tax account).",
                "tax_withholding": 0,
                "penalty": 0,
                "total_taxes": amount * tax_bracket,
                "net_amount": amount,  # Full amount goes to Roth, but taxes owed
                "timeline": "Taxes due when you file next year's tax return",
                "recommendation": "Consider if you expect higher tax bracket in retirement",
                "benefit": "Qualified withdrawals in retirement are completely tax-free",
                "steps": [
                    "Roll over to Roth IRA",
                    f"Entire ${amount:,.2f} added to your taxable income",
                    f"Estimated tax bill: ${amount * tax_bracket:,.2f} (depends on your tax bracket)",
                    "Pay taxes when filing next year",
                    "Future qualified withdrawals are tax-free"
                ],
                "note": "Best for younger investors with time for tax-free growth"
            },
            "cash_out": {
                "name": "Cash Out (Withdrawal)",
                "description": "Withdraw funds now - not recommended due to high tax cost.",
                "tax_withholding": amount * indirect_withholding,
                "penalty": amount * early_penalty,
                "total_taxes": amount * (tax_bracket + early_penalty),
                "net_amount": amount * (1 - tax_bracket - early_penalty),
                "timeline": "Immediate",
                "recommendation": "Strongly discouraged - loses 30-40% to taxes and penalties",
                "warning": f"You'll receive only ~${amount * (1 - tax_bracket - early_penalty):,.2f} from your ${amount:,.2f} balance. You lose ${amount * (tax_bracket + early_penalty):,.2f} to taxes and penalties.",
                "consequences": [
                    f"${amount * tax_bracket:,.2f} in income taxes ({int(tax_bracket * 100)}% bracket estimate)",
                    f"${amount * early_penalty:,.2f} early withdrawal penalty ({int(early_penalty * 100)}%)",
                    "Permanently reduces retirement savings",
                    "Loses years of tax-deferred compound growth"
                ],
                "alternative": "Consider a 401(k) loan if you need emergency funds"
            }
        }
        
        if rollover_type not in tax_scenarios:
            return _json(
                False,
                f"Unknown rollover type: {rollover_type}. Valid options: direct_rollover, indirect_rollover, roth_conversion, cash_out"
            )
        
        scenario = tax_scenarios[rollover_type]
        
        logger.info(
            "✅ Tax impact calculated | client=%s type=%s net=${:,.2f}",
            client_id, rollover_type, scenario["net_amount"]
        )
        
        return _json(
            True,
            f"Tax impact for {scenario['name']}",
            rollover_type=rollover_type,
            balance_amount=amount,
            **scenario
        )
    
    except Exception as error:
        logger.error(f"❌ Failed to calculate tax impact: {error}", exc_info=True)
        return _json(False, "Unable to calculate tax impact at this time.")


# ═══════════════════════════════════════════════════════════════════
# ADVISOR HANDOFF
# ═══════════════════════════════════════════════════════════════════


