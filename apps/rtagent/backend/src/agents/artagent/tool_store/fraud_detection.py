"""
Enhanced Fraud Detection Tools for ARTAgent Financial Services

Provides comprehensive fraud detection and investigation capabilities including:
1. Transaction Analysis & Pattern Detection
2. Account Monitoring & Suspicious Activity Detection  
3. Fraud Case Management & Resolution
4. Card Replacement & Shipping with Tracking
5. Real-time Risk Assessment & Client Correlation
6. Cosmos DB Integration for all fraud data

Designed for post-authentication fraud investigation workflows using client_id from auth.
"""

import asyncio
import datetime
import os
import secrets
import string
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger("tools.fraud_detection")

# Initialize Cosmos DB managers for fraud detection
_fraud_cosmos_manager = None
_transactions_cosmos_manager = None
_card_orders_cosmos_manager = None

def get_fraud_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the fraud cases Cosmos DB manager."""
    global _fraud_cosmos_manager
    if _fraud_cosmos_manager is None:
        _fraud_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="fraud_cases"
        )
    return _fraud_cosmos_manager

def get_transactions_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the transactions Cosmos DB manager."""
    global _transactions_cosmos_manager
    if _transactions_cosmos_manager is None:
        _transactions_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="transactions"
        )
    return _transactions_cosmos_manager

def get_card_orders_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the card orders Cosmos DB manager.""" 
    global _card_orders_cosmos_manager
    if _card_orders_cosmos_manager is None:
        _card_orders_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="card_orders"
        )
    return _card_orders_cosmos_manager


# ──────────────────────────────────────────────────────────────────────────────
# TypedDict Models for Fraud Detection
# ──────────────────────────────────────────────────────────────────────────────

class AnalyzeTransactionsArgs(TypedDict):
    """Arguments for analyzing recent transactions."""
    client_id: str
    days_back: Optional[int]  # Default 30 days
    transaction_limit: Optional[int]  # Default 50 transactions

class AnalyzeTransactionsResult(TypedDict):
    """Result of transaction analysis."""
    analysis_complete: bool
    total_transactions: int
    suspicious_count: int
    fraud_indicators: List[str]
    risk_score: int  # 0-100
    recommended_action: str
    recent_transactions: List[Dict[str, Any]]

class CheckSuspiciousActivityArgs(TypedDict):
    """Arguments for suspicious activity detection."""
    client_id: str
    activity_type: Optional[str]  # 'all', 'login', 'transaction', 'profile_change'

class CheckSuspiciousActivityResult(TypedDict):
    """Result of suspicious activity check."""
    suspicious_activity_detected: bool
    risk_level: Literal["low", "medium", "high", "critical"]
    activity_summary: str
    alerts: List[Dict[str, Any]]
    recommended_actions: List[str]

class CreateFraudCaseArgs(TypedDict):
    """Arguments for creating fraud case."""
    client_id: str
    fraud_type: str
    description: str
    reported_transactions: Optional[List[str]]
    estimated_loss: Optional[float]

class CreateFraudCaseResult(TypedDict):
    """Result of fraud case creation."""
    case_created: bool
    case_number: Optional[str]
    priority_level: str
    next_steps: List[str]
    estimated_resolution_time: str
    contact_reference: str

class BlockCardArgs(TypedDict):
    """Arguments for emergency card blocking."""
    client_id: str
    card_last_4: str
    block_reason: str

class BlockCardResult(TypedDict):
    """Result of card blocking action."""
    card_blocked: bool
    confirmation_number: str
    replacement_timeline: str
    temporary_access_options: List[str]
    next_steps: List[str]

class FraudEducationArgs(TypedDict):
    """Arguments for fraud education."""
    client_id: str
    fraud_type: str  # 'phishing', 'identity_theft', 'card_skimming', 'general'

class FraudEducationResult(TypedDict):
    """Result of fraud education."""
    education_provided: bool
    prevention_tips: List[str]
    warning_signs: List[str]
    contact_info: Dict[str, str]
    follow_up_scheduled: bool

class ShipReplacementCardArgs(TypedDict):
    """Arguments for shipping replacement card."""
    client_id: str
    fraud_case_id: str
    expedited_shipping: Optional[bool]
    reason: str

class ShipReplacementCardResult(TypedDict):
    """Result of replacement card shipping."""
    card_ordered: bool
    tracking_number: Optional[str]
    estimated_delivery: Optional[str]
    message: str
    notification_sent: bool

class SendFraudCaseEmailArgs(TypedDict):
    """Arguments for sending fraud case email."""
    client_id: str
    fraud_case_id: str
    email_type: Literal["case_created", "card_blocked", "investigation_update", "resolution"]
    additional_details: Optional[str]

class SendFraudCaseEmailResult(TypedDict):
    """Result of fraud case email sending."""
    email_sent: bool
    email_address: str
    message: str
    email_subject: str
    email_contents: str
    delivery_timestamp: str


# ──────────────────────────────────────────────────────────────────────────────
# Mock Transaction Data Generator (for demo purposes)
# ──────────────────────────────────────────────────────────────────────────────

def generate_mock_transactions(client_id: str, days_back: int = 30, limit: int = 50) -> List[Dict[str, Any]]:
    """Generate realistic mock transaction data for fraud analysis."""
    
    base_transactions = {
        "james_thompson_mfg": [
            {
                "transaction_id": "TXN_001_2024102401", 
                "date": "2024-10-24T14:23:00Z",
                "amount": -45.67,
                "merchant": "Starbucks #1234",
                "location": "New York, NY",
                "category": "dining",
                "method": "chip_card",
                "status": "completed"
            },
            {
                "transaction_id": "TXN_001_2024102402",
                "date": "2024-10-24T09:15:00Z", 
                "amount": -1250.00,
                "merchant": "Best Buy #5678",
                "location": "New York, NY",
                "category": "electronics",
                "method": "contactless",
                "status": "completed"
            },
            {
                "transaction_id": "TXN_001_2024102403", 
                "date": "2024-10-23T22:47:00Z",
                "amount": -89.99,
                "merchant": "AMZN Marketplace",
                "location": "Online",
                "category": "online_purchase",
                "method": "stored_card", 
                "status": "completed"
            },
            # SUSPICIOUS TRANSACTIONS
            {
                "transaction_id": "TXN_001_2024102404",
                "date": "2024-10-23T03:22:00Z",  # Unusual time
                "amount": -2847.50,  # Large amount
                "merchant": "ATM Withdrawal",
                "location": "Las Vegas, NV",  # Different location
                "category": "cash_advance",
                "method": "atm_pin",
                "status": "completed",
                "fraud_indicators": ["unusual_time", "unusual_location", "large_amount"]
            },
            {
                "transaction_id": "TXN_001_2024102405",
                "date": "2024-10-23T03:27:00Z",  # 5 minutes later
                "amount": -2847.50,  # Same amount - suspicious
                "merchant": "ATM Withdrawal", 
                "location": "Las Vegas, NV",
                "category": "cash_advance",
                "method": "atm_pin",
                "status": "completed",
                "fraud_indicators": ["duplicate_transaction", "rapid_succession", "unusual_location"]
            },
            {
                "transaction_id": "TXN_001_2024102206",
                "date": "2024-10-22T18:33:00Z",
                "amount": -299.99,
                "merchant": "Electronics Express",
                "location": "Miami, FL",  # Different state
                "category": "electronics", 
                "method": "manual_entry",  # No chip/PIN
                "status": "completed",
                "fraud_indicators": ["unusual_location", "manual_entry", "velocity_check"]
            }
        ],
        "emily_rivera_gca": [
            {
                "transaction_id": "TXN_002_2024102401",
                "date": "2024-10-24T16:45:00Z",
                "amount": -12.50,
                "merchant": "Whole Foods Market",
                "location": "San Francisco, CA",
                "category": "grocery",
                "method": "contactless",
                "status": "completed"
            },
            {
                "transaction_id": "TXN_002_2024102402", 
                "date": "2024-10-24T08:30:00Z",
                "amount": -3.75,
                "merchant": "Blue Bottle Coffee",
                "location": "San Francisco, CA", 
                "category": "dining",
                "method": "mobile_pay",
                "status": "completed"
            }
        ]
    }
    
    return base_transactions.get(client_id, [])


# ──────────────────────────────────────────────────────────────────────────────
# Fraud Detection Tool Functions
# ──────────────────────────────────────────────────────────────────────────────

async def analyze_recent_transactions(args: AnalyzeTransactionsArgs) -> AnalyzeTransactionsResult:
    """Analyze recent transactions for fraud patterns and suspicious activity."""
    try:
        client_id = args.get("client_id", "").strip()
        days_back = args.get("days_back", 30)
        transaction_limit = args.get("transaction_limit", 50)
        
        if not client_id:
            return {
                "analysis_complete": False,
                "total_transactions": 0,
                "suspicious_count": 0,
                "fraud_indicators": ["Missing client ID"],
                "risk_score": 0,
                "recommended_action": "Unable to analyze - client ID required",
                "recent_transactions": []
            }
        
        logger.info(f"🔍 Analyzing transactions for client: {client_id} ({days_back} days)", 
                   extra={"client_id": client_id, "operation": "analyze_transactions"})
        
        # Get transaction data (using mock data for demo)
        transactions = generate_mock_transactions(client_id, days_back, transaction_limit)
        
        # Fraud pattern analysis
        fraud_indicators = []
        suspicious_transactions = []
        risk_score = 0
        
        for transaction in transactions:
            if "fraud_indicators" in transaction:
                suspicious_transactions.append(transaction)
                fraud_indicators.extend(transaction["fraud_indicators"])
                risk_score += 15  # Each suspicious transaction adds risk
        
        # Additional pattern analysis
        if len(transactions) > 0:
            # Check for velocity (rapid transactions)
            dates = [datetime.datetime.fromisoformat(t["date"].replace("Z", "")) for t in transactions]
            dates.sort()
            
            rapid_transactions = 0
            for i in range(1, len(dates)):
                time_diff = (dates[i] - dates[i-1]).total_seconds() / 60  # minutes
                if time_diff < 5:  # Less than 5 minutes apart
                    rapid_transactions += 1
            
            if rapid_transactions > 2:
                fraud_indicators.append("rapid_transaction_velocity")
                risk_score += 20
            
            # Check for unusual locations
            locations = [t.get("location", "").split(",")[1].strip() if "," in t.get("location", "") else "" for t in transactions]
            unique_states = set([loc for loc in locations if loc and len(loc) == 2])
            
            if len(unique_states) > 2:  # More than 2 states in period
                fraud_indicators.append("multiple_geographic_locations")
                risk_score += 10
            
            # Check for large amounts
            amounts = [abs(float(t.get("amount", 0))) for t in transactions]
            avg_amount = sum(amounts) / len(amounts) if amounts else 0
            large_transactions = [a for a in amounts if a > avg_amount * 3]
            
            if large_transactions:
                fraud_indicators.append("unusually_large_transactions")
                risk_score += 10
        
        # Cap risk score at 100
        risk_score = min(risk_score, 100)
        
        # Determine recommended action
        if risk_score >= 75:
            recommended_action = "IMMEDIATE ACTION: Block card and create high-priority fraud case"
        elif risk_score >= 50:
            recommended_action = "URGENT: Contact customer immediately and create fraud case"
        elif risk_score >= 25:
            recommended_action = "MONITOR: Flag for additional verification on next transaction"
        else:
            recommended_action = "NORMAL: Continue standard monitoring"
        
        logger.info(f"✅ Transaction analysis complete: {len(suspicious_transactions)} suspicious out of {len(transactions)}", 
                   extra={"client_id": client_id, "risk_score": risk_score, "suspicious_count": len(suspicious_transactions)})
        
        return {
            "analysis_complete": True,
            "total_transactions": len(transactions),
            "suspicious_count": len(suspicious_transactions),
            "fraud_indicators": list(set(fraud_indicators)),  # Remove duplicates
            "risk_score": risk_score,
            "recommended_action": recommended_action,
            "recent_transactions": transactions[-10:]  # Return last 10 for display
        }
        
    except Exception as e:
        logger.error(f"❌ Error analyzing transactions: {e}", exc_info=True)
        return {
            "analysis_complete": False,
            "total_transactions": 0,
            "suspicious_count": 0,
            "fraud_indicators": ["Analysis system error"],
            "risk_score": 0,
            "recommended_action": "Unable to complete analysis - escalate to fraud specialist",
            "recent_transactions": []
        }


async def check_suspicious_activity(args: CheckSuspiciousActivityArgs) -> CheckSuspiciousActivityResult:
    """Check for suspicious account activity patterns."""
    try:
        client_id = args.get("client_id", "").strip()
        activity_type = args.get("activity_type", "all")
        
        if not client_id:
            return {
                "suspicious_activity_detected": False,
                "risk_level": "low",
                "activity_summary": "Unable to check - client ID required",
                "alerts": [],
                "recommended_actions": ["Provide valid client ID"]
            }
        
        logger.info(f"🚨 Checking suspicious activity for client: {client_id}", 
                   extra={"client_id": client_id, "operation": "check_suspicious_activity"})
        
        # Mock suspicious activity patterns (based on client)
        alerts = []
        risk_level = "low"
        
        if client_id == "james_thompson_mfg":
            alerts = [
                {
                    "alert_id": "ALERT_001",
                    "timestamp": "2024-10-23T03:22:00Z",
                    "type": "unusual_transaction_pattern",
                    "severity": "high",
                    "description": "Multiple large ATM withdrawals in Las Vegas, NV - outside normal geographic pattern",
                    "amount": 5695.00,
                    "location": "Las Vegas, NV"
                },
                {
                    "alert_id": "ALERT_002", 
                    "timestamp": "2024-10-23T03:27:00Z",
                    "type": "duplicate_transaction",
                    "severity": "critical",
                    "description": "Identical transaction amount and location within 5 minutes",
                    "amount": 2847.50,
                    "location": "Las Vegas, NV"
                },
                {
                    "alert_id": "ALERT_003",
                    "timestamp": "2024-10-22T18:33:00Z", 
                    "type": "geographic_anomaly",
                    "severity": "medium",
                    "description": "Transaction in Miami, FL - 1,200 miles from normal activity zone",
                    "amount": 299.99,
                    "location": "Miami, FL"
                }
            ]
            risk_level = "critical"
        
        elif client_id == "emily_rivera_gca":
            # Emily has clean activity
            alerts = []
            risk_level = "low"
        
        # Determine recommended actions based on risk level
        recommended_actions = []
        if risk_level == "critical":
            recommended_actions = [
                "Immediately block all cards and payment methods",
                "Create high-priority fraud case",
                "Contact customer via verified phone number", 
                "Freeze account pending investigation",
                "Escalate to fraud investigation team"
            ]
        elif risk_level == "high":
            recommended_actions = [
                "Contact customer to verify recent transactions",
                "Place temporary hold on large transactions",
                "Create fraud case for investigation",
                "Request additional authentication for next login"
            ]
        elif risk_level == "medium":
            recommended_actions = [
                "Monitor account for additional suspicious activity",
                "Flag for manual review on next transaction",
                "Consider contacting customer if pattern continues"
            ]
        else:
            recommended_actions = [
                "Continue normal monitoring",
                "No immediate action required"
            ]
        
        activity_summary = f"Analyzed {activity_type} activity for {client_id}: {len(alerts)} alerts detected, risk level: {risk_level}"
        
        logger.info(f"🚨 Suspicious activity check complete: {len(alerts)} alerts, risk: {risk_level}", 
                   extra={"client_id": client_id, "alert_count": len(alerts), "risk_level": risk_level})
        
        return {
            "suspicious_activity_detected": len(alerts) > 0,
            "risk_level": risk_level,
            "activity_summary": activity_summary,
            "alerts": alerts,
            "recommended_actions": recommended_actions
        }
        
    except Exception as e:
        logger.error(f"❌ Error checking suspicious activity: {e}", exc_info=True)
        return {
            "suspicious_activity_detected": False,
            "risk_level": "low",
            "activity_summary": "Error occurred during activity analysis",
            "alerts": [],
            "recommended_actions": ["Escalate to technical support"]
        }


async def create_fraud_case(args: CreateFraudCaseArgs) -> CreateFraudCaseResult:
    """Create formal fraud investigation case."""
    try:
        client_id = args.get("client_id", "").strip()
        fraud_type = args.get("fraud_type", "").strip()
        description = args.get("description", "").strip()
        reported_transactions = args.get("reported_transactions", [])
        estimated_loss = args.get("estimated_loss", 0.0)
        
        if not client_id or not fraud_type or not description:
            return {
                "case_created": False,
                "case_number": None,
                "priority_level": "low",
                "next_steps": ["Provide complete fraud details"],
                "estimated_resolution_time": "N/A",
                "contact_reference": "N/A"
            }
        
        # Generate case number
        case_number = f"FRAUD-{datetime.datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
        
        # Determine priority based on estimated loss and fraud type
        if estimated_loss >= 5000 or fraud_type in ["identity_theft", "account_takeover"]:
            priority_level = "critical"
            estimated_resolution_time = "24-48 hours"
        elif estimated_loss >= 1000 or fraud_type in ["card_fraud", "unauthorized_transactions"]:
            priority_level = "high" 
            estimated_resolution_time = "3-5 business days"
        else:
            priority_level = "medium"
            estimated_resolution_time = "5-10 business days"
        
        # Create fraud case record
        case_data = {
            "_id": case_number,
            "client_id": client_id,
            "fraud_type": fraud_type,
            "description": description,
            "reported_transactions": reported_transactions,
            "estimated_loss": estimated_loss,
            "priority_level": priority_level,
            "status": "open",
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "assigned_investigator": None,
            "resolution_timeline": estimated_resolution_time,
            "case_notes": [],
            "evidence_collected": [],
            "customer_contacted": False,
            # TTL for cleanup after 2 years
            "ttl": 63072000  # 2 years in seconds
        }
        
        # Store in Cosmos DB
        try:
            fraud_cosmos = get_fraud_cosmos_manager()
            await asyncio.to_thread(
                fraud_cosmos.upsert_document,
                document=case_data,
                query={"_id": case_number}
            )
            case_created = True
            logger.info(f"✅ Fraud case created: {case_number}", 
                       extra={"client_id": client_id, "case_number": case_number, "priority": priority_level})
        except Exception as db_error:
            logger.error(f"❌ Database error creating fraud case: {db_error}")
            case_created = False
        
        # Define next steps based on priority
        next_steps = []
        if priority_level == "critical":
            next_steps = [
                "Immediate card blocking initiated",
                "Fraud investigator will contact you within 2 hours", 
                "Account freeze placed pending investigation",
                "Police report filing may be required",
                "Temporary credit issued if applicable"
            ]
        elif priority_level == "high":
            next_steps = [
                "Case assigned to fraud investigation team",
                "You will be contacted within 24 hours",
                "Disputed transactions will be provisionally credited",
                "Additional documentation may be requested",
                "New cards will be issued if needed"
            ]
        else:
            next_steps = [
                "Case logged for investigation",
                "Investigation team will review within 3 business days",
                "Monitor your account for additional suspicious activity", 
                "We may contact you for additional information",
                "Case updates will be provided via secure message"
            ]
        
        contact_reference = f"Reference your case number {case_number} in all communications"
        
        return {
            "case_created": case_created,
            "case_number": case_number,
            "priority_level": priority_level,
            "next_steps": next_steps,
            "estimated_resolution_time": estimated_resolution_time,
            "contact_reference": contact_reference
        }
        
    except Exception as e:
        logger.error(f"❌ Error creating fraud case: {e}", exc_info=True)
        return {
            "case_created": False,
            "case_number": None,
            "priority_level": "low",
            "next_steps": ["System error - escalate to supervisor"],
            "estimated_resolution_time": "N/A",
            "contact_reference": "N/A"
        }


async def block_card_emergency(args: BlockCardArgs) -> BlockCardResult:
    """Emergency card blocking for fraud prevention."""
    try:
        client_id = args.get("client_id", "").strip()
        card_last_4 = args.get("card_last_4", "").strip()
        block_reason = args.get("block_reason", "").strip()
        
        if not client_id or not card_last_4:
            return {
                "card_blocked": False,
                "confirmation_number": "",
                "replacement_timeline": "N/A",
                "temporary_access_options": [],
                "next_steps": ["Provide complete card information"]
            }
        
        logger.info(f"🚫 Emergency card block for client: {client_id}, card: ****{card_last_4}", 
                   extra={"client_id": client_id, "operation": "emergency_card_block"})
        
        # Generate confirmation number
        confirmation_number = f"BLOCK-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M')}-{secrets.token_hex(3).upper()}"
        
        # Mock card blocking (in real system, this would call banking API)
        card_blocked = True  # Assume successful blocking
        
        # Standard replacement timeline
        replacement_timeline = "New card will be expedited and arrive within 1-2 business days"
        
        # Temporary access options
        temporary_access_options = [
            "Use mobile wallet (Apple Pay, Google Pay) if previously set up",
            "Visit branch with valid ID for emergency cash withdrawal", 
            "Wire transfer available for urgent payments",
            "Online banking and bill pay remain available",
            "Contact customer service for emergency card number if traveling"
        ]
        
        # Next steps
        next_steps = [
            f"Your card ending in {card_last_4} has been immediately blocked",
            "New card is being expedited to your address on file",
            "You will receive SMS/email confirmation with tracking",
            "Update any automatic payments with new card when received",
            "Contact us if you find the card - we can unblock if appropriate"
        ]
        
        logger.info(f"✅ Card blocked successfully: {confirmation_number}", 
                   extra={"client_id": client_id, "confirmation_number": confirmation_number})
        
        return {
            "card_blocked": card_blocked,
            "confirmation_number": confirmation_number,
            "replacement_timeline": replacement_timeline,
            "temporary_access_options": temporary_access_options,
            "next_steps": next_steps
        }
        
    except Exception as e:
        logger.error(f"❌ Error blocking card: {e}", exc_info=True)
        return {
            "card_blocked": False,
            "confirmation_number": "",
            "replacement_timeline": "System error occurred",
            "temporary_access_options": [],
            "next_steps": ["Escalate to customer service immediately"]
        }


async def provide_fraud_education(args: FraudEducationArgs) -> FraudEducationResult:
    """Provide fraud prevention education and warning signs."""
    try:
        client_id = args.get("client_id", "").strip()
        fraud_type = args.get("fraud_type", "general").lower()
        
        logger.info(f"📚 Providing fraud education for: {fraud_type}", 
                   extra={"client_id": client_id, "fraud_type": fraud_type})
        
        # Education content based on fraud type
        prevention_tips = []
        warning_signs = []
        
        if fraud_type == "phishing":
            prevention_tips = [
                "Never click links in suspicious emails or texts",
                "Always verify sender by calling the official number",
                "Look for misspellings and poor grammar in messages",
                "Never provide personal info via email or text",
                "Use official websites by typing URLs directly"
            ]
            warning_signs = [
                "Urgent requests for personal information",
                "Threats of account closure or legal action",
                "Requests to 'verify' information you didn't request",
                "Generic greetings like 'Dear Customer'",
                "Suspicious email addresses or phone numbers"
            ]
        
        elif fraud_type == "identity_theft":
            prevention_tips = [
                "Monitor your credit reports regularly",
                "Use strong, unique passwords for all accounts", 
                "Enable two-factor authentication where available",
                "Shred documents containing personal information",
                "Be cautious about sharing personal info on social media"
            ]
            warning_signs = [
                "Unexpected bills or accounts you didn't open",
                "Missing mail or redirected mail",
                "Unfamiliar transactions on credit reports",
                "Calls from debt collectors about unknown debt",
                "IRS notices about unreported income"
            ]
        
        elif fraud_type == "card_skimming":
            prevention_tips = [
                "Inspect card readers before using ATMs or card terminals",
                "Cover your PIN when entering it",
                "Use contactless payments when possible",
                "Check your statements frequently",
                "Use ATMs in well-lit, secure locations"
            ]
            warning_signs = [
                "Card reader looks loose or different",
                "Unexpected difficulty inserting your card",
                "Suspicious devices attached to card readers",
                "People watching you enter your PIN",
                "Unfamiliar transactions on your account"
            ]
        
        else:  # general
            prevention_tips = [
                "Regularly monitor all financial accounts",
                "Set up account alerts for all transactions",
                "Use strong, unique passwords",
                "Never share account information over phone/email",
                "Keep software and apps updated"
            ]
            warning_signs = [
                "Unfamiliar transactions or withdrawals",
                "Missing statements or mail",
                "Unexpected account changes",
                "Calls requesting verification of account info",
                "Credit score changes without explanation"
            ]
        
        # Contact information
        contact_info = {
            "fraud_hotline": "1-800-FRAUD-HELP (1-800-372-8343)",
            "customer_service": "Available 24/7 for fraud concerns",
            "online_reporting": "Report fraud via secure message in online banking",
            "emergency_card_blocking": "Available 24/7 at 1-800-CARD-BLOCK"
        }
        
        return {
            "education_provided": True,
            "prevention_tips": prevention_tips,
            "warning_signs": warning_signs,
            "contact_info": contact_info,
            "follow_up_scheduled": False
        }
        
    except Exception as e:
        logger.error(f"❌ Error providing fraud education: {e}", exc_info=True)
        return {
            "education_provided": False,
            "prevention_tips": [],
            "warning_signs": [],
            "contact_info": {},
            "follow_up_scheduled": False
        }


async def ship_replacement_card(args: ShipReplacementCardArgs) -> ShipReplacementCardResult:
    """Ship replacement card and send notification using authenticated client data."""
    try:
        client_id = args.get("client_id", "").strip()
        fraud_case_id = args.get("fraud_case_id", "").strip()
        expedited_shipping = args.get("expedited_shipping", True)  # Default to expedited for fraud
        reason = args.get("reason", "fraud_prevention")
        
        if not client_id or not fraud_case_id:
            return {
                "card_ordered": False,
                "tracking_number": None,
                "estimated_delivery": None,
                "message": "Client ID and fraud case ID are required.",
                "notification_sent": False
            }
        
        logger.info(f"💳 Ordering replacement card for client: {client_id}", 
                   extra={"client_id": client_id, "fraud_case_id": fraud_case_id, "operation": "ship_replacement_card"})
        
        # Get client information from financial services DB
        try:
            from .financial_mfa_auth import get_financial_cosmos_manager
            financial_cosmos = get_financial_cosmos_manager()
            client_data = await asyncio.to_thread(financial_cosmos.read_document, {"_id": client_id})
            
            if not client_data:
                return {
                    "card_ordered": False,
                    "tracking_number": None,
                    "estimated_delivery": None,
                    "message": "Client information not found for card shipping.",
                    "notification_sent": False
                }
                
        except Exception as lookup_error:
            logger.error(f"❌ Error looking up client data: {lookup_error}")
            return {
                "card_ordered": False,
                "tracking_number": None,
                "estimated_delivery": None,
                "message": "Unable to retrieve shipping information. Please contact support.",
                "notification_sent": False
            }
        
        # Generate tracking number (in real system, this would come from card issuer API)
        tracking_number = f"CARD{secrets.randbelow(1000000000):09d}"
        
        # Calculate delivery date
        delivery_days = 1 if expedited_shipping else 5  # Business days
        estimated_delivery = (datetime.datetime.utcnow() + datetime.timedelta(days=delivery_days)).strftime("%B %d, %Y")
        
        # Create card order record
        card_order = {
            "_id": f"card_order_{client_id}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "client_id": client_id,
            "fraud_case_id": fraud_case_id,
            "card_type": "REPLACEMENT",
            "reason": reason,
            "shipping_method": "EXPEDITED" if expedited_shipping else "STANDARD",
            "tracking_number": tracking_number,
            "estimated_delivery": estimated_delivery,
            "shipping_address": {
                "name": client_data.get("full_name", ""),
                "email": client_data.get("contact_info", {}).get("email", ""),
                "phone": client_data.get("contact_info", {}).get("phone", "")
                # In real system, would have full address
            },
            "order_status": "PROCESSING",
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            # Store card order in Cosmos DB
            cosmos = get_card_orders_cosmos_manager()
            await asyncio.to_thread(
                cosmos.upsert_document,
                document=card_order,
                query={"_id": card_order["_id"]}
            )
            
            logger.info(f"✅ Card order created: {tracking_number}")
            
        except Exception as storage_error:
            logger.error(f"❌ Failed to store card order: {storage_error}")
            # Continue with notification even if storage fails
        
        # Send notification email
        notification_sent = False
        try:
            from src.acs import EmailService
            email_service = EmailService()
            if email_service.is_configured():
                client_name = client_data.get("full_name", "Valued Customer")
                client_email = client_data.get("contact_info", {}).get("email", "")
                
                if client_email:
                    subject = "🔒 Your Replacement Card Has Been Ordered - Financial Services"
                    
                    plain_text = f"""Dear {client_name},

Your replacement card has been ordered and will arrive soon.

Order Details:
- Tracking Number: {tracking_number}
- Estimated Delivery: {estimated_delivery}
- Shipping Method: {'Expedited (1-2 business days)' if expedited_shipping else 'Standard (3-5 business days)'}

Security Reminder:
- Your previous card has been deactivated
- Activate your new card immediately upon receipt
- Monitor your account for any suspicious activity

If you have any questions, please contact us at 1-800-SECURE-CARD.

Best regards,
Financial Services Security Team"""

                    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #d32f2f; color: white; padding: 20px; text-align: center;">
        <h1>🔒 Replacement Card Ordered</h1>
        <h2>Your Account is Now Secure</h2>
    </div>
    
    <div style="padding: 20px; background: #f9f9f9;">
        <p>Dear <strong>{client_name}</strong>,</p>
        
        <p>Your replacement card has been ordered and will arrive at your address on file.</p>
        
        <div style="background: white; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 4px solid #d32f2f;">
            <h3>📦 Order Details</h3>
            <p><strong>Tracking Number:</strong> {tracking_number}</p>
            <p><strong>Estimated Delivery:</strong> {estimated_delivery}</p>
            <p><strong>Shipping Method:</strong> {'Expedited (1-2 business days)' if expedited_shipping else 'Standard (3-5 business days)'}</p>
        </div>
        
        <div style="background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 8px; border-left: 4px solid #ffc107;">
            <h4>🛡️ Important Security Information</h4>
            <ul>
                <li>Your previous card has been <strong>immediately deactivated</strong></li>
                <li><strong>Activate your new card</strong> as soon as you receive it</li>
                <li><strong>Monitor your account</strong> regularly for any suspicious activity</li>
                <li>Contact us immediately if you notice anything unusual</li>
            </ul>
        </div>
        
        <p>If you have any questions about your replacement card or need to update your address, please contact us at <strong>1-800-SECURE-CARD</strong>.</p>
    </div>
    
    <div style="background: #333; color: white; padding: 15px; text-align: center;">
        <p>Financial Services - Protecting Your Financial Security</p>
        <p style="font-size: 12px;">Case ID: {fraud_case_id}</p>
    </div>
</body>
</html>"""

                    await email_service.send_email(
                        email_address=client_email,
                        subject=subject,
                        plain_text_body=plain_text,
                        html_body=html
                    )
                    
                    notification_sent = True
                    logger.info(f"✅ Card shipping notification sent to {client_email}")
                    
        except Exception as email_error:
            logger.error(f"❌ Failed to send card shipping notification: {email_error}")
            # Don't fail the whole operation if email fails
        
        return {
            "card_ordered": True,
            "tracking_number": tracking_number,
            "estimated_delivery": estimated_delivery,
            "message": f"Replacement card ordered successfully. Tracking: {tracking_number}. Estimated delivery: {estimated_delivery}.",
            "notification_sent": notification_sent
        }
        
    except Exception as e:
        logger.error(f"❌ Error shipping replacement card: {e}", exc_info=True, 
                    extra={"client_id": client_id, "error_type": "card_shipping_error"})
        return {
            "card_ordered": False,
            "tracking_number": None,
            "estimated_delivery": None,
            "message": "Card ordering service encountered an error. Please contact support immediately.",
            "notification_sent": False
        }
        
        # Schedule follow-up (mock)
        follow_up_scheduled = True
        
        logger.info(f"✅ Fraud education provided: {len(prevention_tips)} tips, {len(warning_signs)} warning signs", 
                   extra={"client_id": client_id, "fraud_type": fraud_type})
        
        return {
            "education_provided": True,
            "prevention_tips": prevention_tips,
            "warning_signs": warning_signs,
            "contact_info": contact_info,
            "follow_up_scheduled": follow_up_scheduled
        }
        
    except Exception as e:
        logger.error(f"❌ Error providing fraud education: {e}", exc_info=True)
        return {
            "education_provided": False,
            "prevention_tips": [],
            "warning_signs": [],
            "contact_info": {},
            "follow_up_scheduled": False
        }


# ──────────────────────────────────────────────────────────────────────────────
# FRAUD CASE EMAIL NOTIFICATION
# ──────────────────────────────────────────────────────────────────────────────

async def send_fraud_case_email(args: SendFraudCaseEmailArgs) -> SendFraudCaseEmailResult:
    """
    Send comprehensive fraud case email with all case details, similar to MFA email functionality.
    
    Args:
        args: SendFraudCaseEmailArgs containing client_id, fraud_case_id, email_type, and optional details
        
    Returns:
        SendFraudCaseEmailResult with email delivery status and contents
    """
    try:
        client_id = args["client_id"]
        fraud_case_id = args["fraud_case_id"]
        email_type = args["email_type"]
        additional_details = args.get("additional_details", "")
        
        logger.info(f"🔔 Sending fraud case email: type={email_type}, case={fraud_case_id}, client={client_id}")
        
        # Mock client data (in real system, fetch from customer profile)
        client_email = "pablosal@microsoft.com"  # This would come from client profile
        client_name = "Emily Rivera"  # This would come from client profile
        institution_name = "Global Capital Advisors"
        
        # Generate email subject based on type
        subject_map = {
            "case_created": f"Fraud Case Created - Case #{fraud_case_id}",
            "card_blocked": f"Card Security Alert - Immediate Action Taken",
            "investigation_update": f"Fraud Investigation Update - Case #{fraud_case_id}",
            "resolution": f"Fraud Case Resolution - Case #{fraud_case_id}"
        }
        
        email_subject = subject_map.get(email_type, f"Security Notification - Case #{fraud_case_id}")
        
        # Generate comprehensive email content
        email_content = f"""Dear {client_name},

This email confirms the fraud protection actions we've taken on your account today.

FRAUD CASE DETAILS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Case Number: {fraud_case_id}
• Institution: {institution_name}
• Date Created: {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}
• Priority Level: HIGH
• Status: Active Investigation

IMMEDIATE ACTIONS TAKEN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Card ending in 0023 has been BLOCKED immediately
✅ Replacement card expedited (1-2 business days delivery)
✅ Disputed transactions flagged for provisional credit
✅ Enhanced account monitoring activated
✅ Fraud case opened with investigation team

PROVISIONAL CREDITS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The following unauthorized transactions will be provisionally credited:
• Whole Foods Market: $12.50 (Oct 24, 2024)
• Blue Bottle Coffee: $3.75 (Oct 24, 2024)
Total Provisional Credit: $16.25

NEXT STEPS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Investigation team will contact you within 24 hours
2. New card will arrive within 1-2 business days with tracking
3. Update automatic payments with new card information when received
4. Monitor your account for any additional suspicious activity

REPLACEMENT CARD DELIVERY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Shipping Method: Expedited (1-2 business days)
• Tracking Number: Will be provided via SMS/Email
• Delivery Address: Your address on file
• Card Activation: Required upon receipt

TEMPORARY ACCESS OPTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
While waiting for your new card:
• Mobile wallet (Apple Pay, Google Pay) remains active if previously set up
• Online banking and bill pay available
• Visit any branch with valid ID for emergency cash withdrawal
• Contact customer service for urgent payment needs

IMPORTANT REFERENCE INFORMATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always reference your case number {fraud_case_id} in all communications.

24/7 Fraud Hotline: 1-800-555-FRAUD
Online Account: {institution_name} Mobile App or Website
Case Status: Track online using your case number

{additional_details}

We sincerely apologize for any inconvenience and appreciate your prompt reporting of this suspicious activity. Your security is our highest priority, and we're committed to resolving this matter quickly and completely.

If you have any questions or concerns, please don't hesitate to contact us immediately.

Best regards,
Fraud Protection Team
{institution_name}

This email contains confidential information. If you received this in error, please delete immediately and notify us.
"""

        # Simulate email delivery (in real system, integrate with actual email service)
        delivery_timestamp = datetime.datetime.now().isoformat()
        
        logger.info(f"✅ Fraud case email sent successfully: {email_subject} to {client_email}")
        
        return {
            "email_sent": True,
            "email_address": client_email,
            "message": f"Comprehensive fraud case email sent to {client_email}",
            "email_subject": email_subject,
            "email_contents": email_content,
            "delivery_timestamp": delivery_timestamp
        }
        
    except Exception as e:
        logger.error(f"❌ Error sending fraud case email: {e}", exc_info=True)
        return {
            "email_sent": False,
            "email_address": "",
            "message": f"Failed to send fraud case email: {str(e)}",
            "email_subject": "",
            "email_contents": "",
            "delivery_timestamp": ""
        }