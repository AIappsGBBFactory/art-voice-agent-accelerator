"""
Transfer Agency Tools - Mock Implementation
Handles DRIP liquidation, compliance checks, and institutional servicing
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from enum import Enum
import json

class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    EXPIRING_SOON = "expiring_soon" 
    NON_COMPLIANT = "non_compliant"
    REQUIRES_REVIEW = "requires_review"

class SettlementSpeed(str, Enum):
    STANDARD = "standard"  # 2-3 business days
    EXPEDITED = "expedited"  # same-day

class FXRateLock(str, Enum):
    NOW = "lock_now"
    MARKET_CLOSE = "market_close"

# Database Integration
import sys
import os

# Add the parent directory to the path to import CosmosDB manager
sys.path.append(os.path.join(os.path.dirname(__file__), '../../..'))

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from .transfer_agency_constants import (
    CURRENT_FX_RATES, PROCESSING_FEES, TAX_WITHHOLDING_RATES,
    SPECIALIST_QUEUES, get_fx_rate, get_processing_fee, get_tax_rate,
    get_specialist_queue_info, format_currency_amount
)

def get_ta_collection_manager(collection_name: str) -> CosmosDBMongoCoreManager:
    """
    Get a manager for transfer agency collections.
    Uses COSMOS_FINANCIAL_DATABASE environment variable for institution-specific databases.
    Defaults to 'financial_services_db' if not set.
    """
    database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
    return CosmosDBMongoCoreManager(
        database_name=database_name,
        collection_name=collection_name
    )

class GetClientDataArgs(BaseModel):
    """Get client institutional data and account details"""
    client_code: str

class GetClientDataResult(BaseModel):
    """Client data result"""
    success: bool
    client_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

def get_client_data(args: GetClientDataArgs) -> GetClientDataResult:
    """Retrieve client institutional data and account details from database"""
    try:
        ta_client_manager = get_ta_collection_manager("transfer_agency_clients")
        
        # Query by client_code
        client_data = ta_client_manager.read_document({"client_code": args.client_code})
        
        if not client_data:
            return GetClientDataResult(
                success=False,
                error_message=f"Client code {args.client_code} not found"
            )
        
        # Transform database format to expected format for compatibility
        transformed_data = {
            "client_id": client_data.get("client_code"),
            "institution_name": client_data.get("institution_name"),
            "contact_name": client_data.get("contact_name"),
            "account_currency": client_data.get("account_currency"),
            "custodial_account": client_data.get("custodial_account"),
            "aml_expiry": client_data.get("aml_expiry"),
            "fatca_status": client_data.get("fatca_status"),
            "w8ben_expiry": client_data.get("w8ben_expiry"),
            "risk_profile": client_data.get("risk_profile"),
            "dual_auth_approver": client_data.get("dual_auth_approver"),
            "email": client_data.get("email")
        }
        
        return GetClientDataResult(
            success=True,
            client_data=transformed_data
        )
    except Exception as e:
        return GetClientDataResult(
            success=False,
            error_message=f"Error retrieving client data: {str(e)}"
        )

class GetDripPositionsArgs(BaseModel):
    """Get client's DRIP positions"""
    client_code: str

class GetDripPositionsResult(BaseModel):
    """DRIP positions result"""
    success: bool
    positions: Optional[Dict[str, Any]] = None
    total_value: Optional[float] = None
    error_message: Optional[str] = None

def get_drip_positions(args: GetDripPositionsArgs) -> GetDripPositionsResult:
    """Get client's current DRIP positions and valuations from database"""
    try:
        drip_manager = get_ta_collection_manager("drip_positions")
        
        # Query by client_code
        drip_positions = drip_manager.query_documents({"client_code": args.client_code})
        
        if not drip_positions:
            return GetDripPositionsResult(
                success=False,
                error_message=f"No DRIP positions found for client {args.client_code}"
            )
        
        # Transform database format to expected format (symbol as key)
        positions = {}
        total_value = 0
        
        for pos in drip_positions:
            symbol = pos.get("symbol")
            positions[symbol] = {
                "symbol": pos.get("symbol"),
                "company_name": pos.get("company_name"),
                "shares": pos.get("shares"),
                "cost_basis_per_share": pos.get("cost_basis_per_share"),
                "last_dividend": pos.get("last_dividend"),
                "dividend_date": pos.get("dividend_date"),
                "current_price": pos.get("current_price"),
                "market_value": pos.get("market_value")
            }
            total_value += pos.get("market_value", 0)
        
        return GetDripPositionsResult(
            success=True,
            positions=positions,
            total_value=total_value
        )
    except Exception as e:
        return GetDripPositionsResult(
            success=False,
            error_message=f"Error retrieving DRIP positions: {str(e)}"
        )

class CheckComplianceArgs(BaseModel):
    """Check client compliance status"""
    client_code: str

class CheckComplianceResult(BaseModel):
    """Compliance check result"""
    success: bool
    aml_status: Optional[ComplianceStatus] = None
    fatca_status: Optional[ComplianceStatus] = None
    aml_days_remaining: Optional[int] = None
    requires_review: bool = False
    error_message: Optional[str] = None

def check_compliance_status(args: CheckComplianceArgs) -> CheckComplianceResult:
    """Check AML and FATCA compliance status from database"""
    try:
        compliance_manager = get_ta_collection_manager("compliance_records")
        
        # Get current year compliance record
        from datetime import datetime, date
        current_year = datetime.now().year
        
        compliance_data = compliance_manager.read_document({
            "client_code": args.client_code,
            "compliance_year": current_year
        })
        
        if not compliance_data:
            return CheckComplianceResult(
                success=False,
                error_message=f"No compliance record found for client {args.client_code} in {current_year}"
            )
        
        # Calculate AML days remaining
        aml_expiry = datetime.strptime(compliance_data["aml_expiry"], "%Y-%m-%d").date()
        today = date.today()
        days_remaining = (aml_expiry - today).days
        
        # Get AML status from database
        aml_status_str = compliance_data.get("aml_status", "compliant")
        
        # Map database status to enum
        status_map = {
            "compliant": ComplianceStatus.COMPLIANT,
            "expiring_soon": ComplianceStatus.EXPIRING_SOON,
            "non_compliant": ComplianceStatus.NON_COMPLIANT,
            "requires_review": ComplianceStatus.REQUIRES_REVIEW
        }
        
        aml_status = status_map.get(aml_status_str, ComplianceStatus.COMPLIANT)
        
        # FATCA status from database
        fatca_status_str = compliance_data.get("fatca_status", "compliant")
        fatca_status = status_map.get(fatca_status_str, ComplianceStatus.COMPLIANT)
        
        requires_review = (
            compliance_data.get("requires_review", False) or
            aml_status != ComplianceStatus.COMPLIANT or
            compliance_data.get("risk_assessment") == "high_risk"
        )
        
        return CheckComplianceResult(
            success=True,
            aml_status=aml_status,
            fatca_status=fatca_status,
            aml_days_remaining=days_remaining,
            requires_review=requires_review
        )
    except Exception as e:
        return CheckComplianceResult(
            success=False,
            error_message=f"Error checking compliance: {str(e)}"
        )

class CalculateTradeArgs(BaseModel):
    """Calculate trade proceeds and fees"""
    client_code: str
    symbol: str
    shares: Optional[float] = None  # If None, liquidate all
    settlement_speed: SettlementSpeed = SettlementSpeed.STANDARD

class CalculateTradeResult(BaseModel):
    """Trade calculation result"""
    success: bool
    symbol: Optional[str] = None
    shares_to_liquidate: Optional[float] = None
    gross_proceeds: Optional[float] = None
    processing_fee: Optional[float] = None
    tax_withholding: Optional[float] = None
    net_proceeds_usd: Optional[float] = None
    net_proceeds_client_currency: Optional[float] = None
    fx_rate: Optional[float] = None
    error_message: Optional[str] = None

def calculate_liquidation_proceeds(args: CalculateTradeArgs) -> CalculateTradeResult:
    """Calculate liquidation proceeds, fees, and taxes using database data"""
    try:
        # Get position data from database
        drip_manager = get_ta_collection_manager("drip_positions")
        position_data = drip_manager.read_document({
            "client_code": args.client_code,
            "symbol": args.symbol
        })
        
        if not position_data:
            return CalculateTradeResult(
                success=False,
                error_message=f"No {args.symbol} position found for client {args.client_code}"
            )
        
        # Calculate shares to liquidate
        shares_to_liquidate = args.shares or position_data["shares"]
        if shares_to_liquidate > position_data["shares"]:
            return CalculateTradeResult(
                success=False,
                error_message=f"Cannot liquidate {shares_to_liquidate} shares, only {position_data['shares']} available"
            )
        
        # Calculate gross proceeds
        current_price = position_data["current_price"]
        gross_proceeds = shares_to_liquidate * current_price
        
        # Calculate fees using constants
        processing_fee = get_processing_fee(args.settlement_speed.value)
        
        # Calculate tax withholding using constants
        dividend_income = shares_to_liquidate * (position_data.get("last_dividend", 0) or 0)
        tax_rate = get_tax_rate("US", "dividend_tax")  # Default to US rates
        tax_withholding = dividend_income * tax_rate
        
        # Calculate net USD proceeds
        net_proceeds_usd = gross_proceeds - processing_fee - tax_withholding
        
        # Get client currency from transfer agency client data
        ta_client_manager = get_ta_collection_manager("transfer_agency_clients")
        client_data = ta_client_manager.read_document({"client_code": args.client_code})
        client_currency = client_data.get("account_currency", "USD") if client_data else "USD"
        
        # Calculate FX conversion
        if client_currency == "USD":
            fx_rate = 1.0
            net_proceeds_client_currency = net_proceeds_usd
        else:
            fx_rate = get_fx_rate("USD", client_currency)
            net_proceeds_client_currency = net_proceeds_usd * fx_rate
        
        return CalculateTradeResult(
            success=True,
            symbol=args.symbol,
            shares_to_liquidate=shares_to_liquidate,
            gross_proceeds=gross_proceeds,
            processing_fee=processing_fee,
            tax_withholding=tax_withholding,
            net_proceeds_usd=net_proceeds_usd,
            net_proceeds_client_currency=net_proceeds_client_currency,
            fx_rate=fx_rate
        )
    except Exception as e:
        return CalculateTradeResult(
            success=False,
            error_message=f"Error calculating liquidation: {str(e)}"
        )

class HandoffComplianceArgs(BaseModel):
    """Hand off to compliance specialist"""
    client_code: str
    client_name: str
    compliance_issue: str
    urgency: str = "normal"  # normal, high, expedited

def handoff_to_compliance(args: HandoffComplianceArgs) -> Dict[str, Any]:
    """Hand off client to compliance specialist for AML/FATCA review using queue constants"""
    try:
        # Generate handoff ID
        import uuid
        handoff_id = f"COMP-{uuid.uuid4().hex[:8].upper()}"
        
        # Get queue information from constants
        queue_info = get_specialist_queue_info("compliance", args.urgency)
        queue_name = queue_info.get("queue_name", "Standard Compliance Review")
        wait_time = queue_info.get("wait_time", "10-15 minutes")
        
        message = f"Transferring {args.client_name} to {queue_name} for {args.compliance_issue}. Handoff ID: {handoff_id}"
        
        # Return orchestrator-compatible handoff format
        return {
            "success": True,
            "message": message,
            "handoff": "Compliance",
            "target_agent": "Compliance",
            "handoff_id": handoff_id,
            "specialist_queue": queue_name,
            "estimated_wait": wait_time,
            "client_name": args.client_name,
            "compliance_issue": args.compliance_issue,
            "urgency": args.urgency
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error creating compliance handoff: {str(e)}",
            "handoff_id": "",
            "specialist_queue": "",
            "estimated_wait": ""
        }

class HandoffTradingArgs(BaseModel):
    """Hand off to trading specialist"""
    client_code: str
    client_name: str
    trade_details: Dict[str, Any]
    complexity: str = "standard"  # standard, complex, institutional

def handoff_to_trading(args: HandoffTradingArgs) -> Dict[str, Any]:
    """Hand off client to trading specialist for execution using queue constants"""
    try:
        # Generate handoff ID
        import uuid
        handoff_id = f"TRADE-{uuid.uuid4().hex[:8].upper()}"
        
        # Get queue information from constants
        queue_info = get_specialist_queue_info("trading", args.complexity)
        queue_name = queue_info.get("queue_name", "Standard Trading Desk")
        wait_time = queue_info.get("wait_time", "2-4 minutes")
        
        message = f"Transferring {args.client_name} to {queue_name} for trade execution. Handoff ID: {handoff_id}"
        
        # Return orchestrator-compatible handoff format
        return {
            "success": True,
            "message": message,
            "handoff": "Trading",
            "target_agent": "Trading", 
            "handoff_id": handoff_id,
            "specialist_queue": queue_name,
            "estimated_wait": wait_time,
            "client_code": args.client_code,
            "client_name": args.client_name,
            "trade_details": args.trade_details,
            "complexity": args.complexity
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error creating trading handoff: {str(e)}",
            "handoff_id": "",
            "specialist_queue": "",
            "estimated_wait": ""
        }