"""
Transfer Agency Constants - Static Data for Transfer Agency Tools
Contains FX rates, fee structures, and other constants that don't require database storage
"""

from typing import Dict, Any
from datetime import datetime, date

# Current FX Rates (Updated daily in production)
CURRENT_FX_RATES = {
    "USD_EUR": 1.0725,
    "USD_GBP": 0.8150, 
    "USD_CHF": 0.9050,
    "USD_CAD": 1.3450,
    "USD_JPY": 149.25,
    "USD_AUD": 1.5280,
    "EUR_GBP": 0.7598,
    "EUR_CHF": 0.8437,
    "last_updated": "2025-10-27T09:00:00Z"
}

# Processing Fees by Settlement Speed
PROCESSING_FEES = {
    "standard": 50.0,      # 2-3 business days
    "expedited": 250.0,    # same-day settlement
    "priority": 150.0      # next-day settlement
}

# Tax Withholding Rates by Country
TAX_WITHHOLDING_RATES = {
    "US": {
        "dividend_tax": 0.15,   # 15% dividend withholding
        "capital_gains": 0.20,  # 20% capital gains for institutions
        "foreign_tax_credit": True
    },
    "EU": {
        "dividend_tax": 0.10,   # 10% under tax treaty
        "capital_gains": 0.15,
        "foreign_tax_credit": True
    },
    "UK": {
        "dividend_tax": 0.05,   # 5% under tax treaty
        "capital_gains": 0.10,
        "foreign_tax_credit": True
    },
    "default": {
        "dividend_tax": 0.30,   # 30% standard withholding
        "capital_gains": 0.30,
        "foreign_tax_credit": False
    }
}

# Compliance Check Thresholds (Days)
COMPLIANCE_THRESHOLDS = {
    "aml_expiry_warning": 30,      # Warn 30 days before AML expires
    "aml_expiry_critical": 5,      # Critical alert 5 days before
    "fatca_review_interval": 365,  # Annual FATCA review
    "w8ben_expiry_warning": 60,    # Warn 60 days before W-8BEN expires
    "kyc_review_interval": 730     # KYC review every 2 years
}

# Specialist Queues and Wait Times
SPECIALIST_QUEUES = {
    "compliance": {
        "expedited": {
            "queue_name": "Expedited Compliance Review",
            "wait_time": "2-3 minutes",
            "sla": 180  # 3 minutes in seconds
        },
        "high": {
            "queue_name": "Priority Compliance Review", 
            "wait_time": "5-7 minutes",
            "sla": 420  # 7 minutes in seconds
        },
        "normal": {
            "queue_name": "Standard Compliance Review",
            "wait_time": "10-15 minutes", 
            "sla": 900  # 15 minutes in seconds
        }
    },
    "trading": {
        "institutional": {
            "queue_name": "Institutional Trading Desk",
            "wait_time": "1-2 minutes",
            "sla": 120  # 2 minutes in seconds
        },
        "complex": {
            "queue_name": "Complex Derivatives Desk",
            "wait_time": "3-5 minutes",
            "sla": 300  # 5 minutes in seconds
        },
        "standard": {
            "queue_name": "Standard Trading Desk", 
            "wait_time": "2-4 minutes",
            "sla": 240  # 4 minutes in seconds
        }
    }
}

# Risk Profile Classifications
RISK_PROFILES = {
    "institutional": {
        "max_transaction_limit": 50000000,   # $50M
        "requires_dual_auth": True,
        "compliance_review_frequency": 365,  # Annual
        "enhanced_monitoring": True
    },
    "high_net_worth": {
        "max_transaction_limit": 10000000,   # $10M
        "requires_dual_auth": True,
        "compliance_review_frequency": 365,
        "enhanced_monitoring": True
    },
    "standard": {
        "max_transaction_limit": 1000000,    # $1M
        "requires_dual_auth": False,
        "compliance_review_frequency": 730,  # Biennial
        "enhanced_monitoring": False
    },
    "restricted": {
        "max_transaction_limit": 100000,     # $100K
        "requires_dual_auth": True,
        "compliance_review_frequency": 180,  # Quarterly
        "enhanced_monitoring": True
    }
}

# Supported Currencies for Settlement
SUPPORTED_CURRENCIES = {
    "USD": {"name": "US Dollar", "symbol": "$", "decimals": 2},
    "EUR": {"name": "Euro", "symbol": "€", "decimals": 2},
    "GBP": {"name": "British Pound", "symbol": "£", "decimals": 2},
    "CHF": {"name": "Swiss Franc", "symbol": "CHF", "decimals": 2},
    "CAD": {"name": "Canadian Dollar", "symbol": "C$", "decimals": 2},
    "JPY": {"name": "Japanese Yen", "symbol": "¥", "decimals": 0},
    "AUD": {"name": "Australian Dollar", "symbol": "A$", "decimals": 2}
}

# Dividend Payment Frequencies
DIVIDEND_FREQUENCIES = {
    "quarterly": {"payments_per_year": 4, "description": "Quarterly dividends"},
    "monthly": {"payments_per_year": 12, "description": "Monthly dividends"},
    "semi_annual": {"payments_per_year": 2, "description": "Semi-annual dividends"},
    "annual": {"payments_per_year": 1, "description": "Annual dividends"},
    "irregular": {"payments_per_year": 0, "description": "Irregular or no dividends"}
}

# Market Hours by Exchange
MARKET_HOURS = {
    "NYSE": {
        "open": "09:30",
        "close": "16:00", 
        "timezone": "America/New_York",
        "trading_days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
    },
    "NASDAQ": {
        "open": "09:30",
        "close": "16:00",
        "timezone": "America/New_York", 
        "trading_days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
    },
    "LSE": {
        "open": "08:00",
        "close": "16:30",
        "timezone": "Europe/London",
        "trading_days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
    }
}

# Settlement Instructions Templates
SETTLEMENT_TEMPLATES = {
    "USD_WIRE": {
        "method": "wire_transfer",
        "currency": "USD",
        "standard_instructions": "JPM Chase Bank, ABA: 021000021, Account: Client Custodial Account",
        "expedited_fee": 25.0
    },
    "EUR_SEPA": {
        "method": "sepa_transfer", 
        "currency": "EUR",
        "standard_instructions": "Deutsche Bank AG, SWIFT: DEUTDEFF, IBAN: Client Account",
        "expedited_fee": 15.0
    },
    "GBP_FASTER": {
        "method": "faster_payments",
        "currency": "GBP", 
        "standard_instructions": "Barclays Bank PLC, Sort Code: 20-00-00, Account: Client Account",
        "expedited_fee": 10.0
    }
}

def get_fx_rate(from_currency: str, to_currency: str) -> float:
    """Get current FX rate between currencies"""
    if from_currency == to_currency:
        return 1.0
    
    # Try direct rate
    rate_key = f"{from_currency}_{to_currency}"
    if rate_key in CURRENT_FX_RATES:
        return CURRENT_FX_RATES[rate_key]
    
    # Try inverse rate
    inverse_key = f"{to_currency}_{from_currency}"
    if inverse_key in CURRENT_FX_RATES:
        return 1.0 / CURRENT_FX_RATES[inverse_key]
    
    # Default to 1.0 if no rate found
    return 1.0

def get_processing_fee(settlement_speed: str) -> float:
    """Get processing fee for settlement speed"""
    return PROCESSING_FEES.get(settlement_speed.lower(), PROCESSING_FEES["standard"])

def get_tax_rate(client_country: str, tax_type: str) -> float:
    """Get tax withholding rate for client country and tax type"""
    country_rates = TAX_WITHHOLDING_RATES.get(client_country.upper(), TAX_WITHHOLDING_RATES["default"])
    return country_rates.get(tax_type, 0.0)

def is_compliance_expiring(expiry_date_str: str, threshold_days: int = 30) -> bool:
    """Check if compliance document is expiring within threshold"""
    try:
        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
        today = date.today()
        days_until_expiry = (expiry_date - today).days
        return days_until_expiry <= threshold_days
    except (ValueError, TypeError):
        return True  # Assume expiring if date parsing fails

def get_specialist_queue_info(queue_type: str, complexity: str) -> Dict[str, Any]:
    """Get specialist queue information"""
    queue_info = SPECIALIST_QUEUES.get(queue_type, {}).get(complexity, {})
    return queue_info if queue_info else SPECIALIST_QUEUES[queue_type]["normal"]

def format_currency_amount(amount: float, currency: str) -> str:
    """Format amount with appropriate currency symbol and decimals"""
    currency_info = SUPPORTED_CURRENCIES.get(currency, {"symbol": "", "decimals": 2})
    decimals = currency_info["decimals"]
    symbol = currency_info["symbol"]
    
    if decimals == 0:
        return f"{symbol}{amount:,.0f}"
    else:
        return f"{symbol}{amount:,.{decimals}f}"

# Version and metadata
CONSTANTS_VERSION = "1.0.0"
LAST_UPDATED = "2025-10-27T10:00:00Z"

# Debug information
DEBUG_INFO = {
    "total_fx_pairs": len(CURRENT_FX_RATES) - 1,  # Exclude last_updated
    "supported_currencies": len(SUPPORTED_CURRENCIES),
    "risk_profiles": len(RISK_PROFILES), 
    "specialist_queues": sum(len(queues) for queues in SPECIALIST_QUEUES.values()),
    "version": CONSTANTS_VERSION
}

if __name__ == "__main__":
    print("🏛️ Transfer Agency Constants Loaded")
    print(f"📊 {DEBUG_INFO['total_fx_pairs']} FX pairs available")
    print(f"💱 {DEBUG_INFO['supported_currencies']} currencies supported") 
    print(f"🎯 {DEBUG_INFO['risk_profiles']} risk profiles configured")
    print(f"📞 {DEBUG_INFO['specialist_queues']} specialist queues available")
    print(f"🔄 Version: {CONSTANTS_VERSION}")