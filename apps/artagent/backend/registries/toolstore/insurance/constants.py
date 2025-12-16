"""
Insurance Constants - Shared Data for Insurance Tools
======================================================

Centralized constants, mock data, and configuration for insurance tooling.
All fictional company names use the "Contoso" pattern with "Insurance" suffix.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


# ═══════════════════════════════════════════════════════════════════════════════
# CONTACT INFORMATION
# ═══════════════════════════════════════════════════════════════════════════════

SUBRO_FAX_NUMBER = "(888) 781-6947"
SUBRO_PHONE_NUMBER = "(855) 405-8645"


# ═══════════════════════════════════════════════════════════════════════════════
# FICTIONAL CLAIMANT CARRIER COMPANIES
# ═══════════════════════════════════════════════════════════════════════════════
# These are fictional insurance company names for demo/testing purposes.
# All names follow the pattern: [Name] Insurance

KNOWN_CC_COMPANIES: Set[str] = {
    "contoso insurance",
    "fabrikam insurance",
    "adventure works insurance",
    "northwind insurance",
    "tailspin insurance",
    "woodgrove insurance",
    "litware insurance",
    "proseware insurance",
    "fourthcoffee insurance",
    "wideworldimporters insurance",
    "alpineski insurance",
    "blueyonder insurance",
    "cohovineyard insurance",
    "margie insurance",
    "treyresearch insurance",
    "adatum insurance",
    "munson insurance",
    "lucerne insurance",
    "relecloud insurance",
    "wingtip insurance",
}

# Display-friendly list of CC company names (capitalized)
CC_COMPANY_DISPLAY_NAMES: List[str] = [
    "Contoso Insurance",
    "Fabrikam Insurance",
    "Adventure Works Insurance",
    "Northwind Insurance",
    "Tailspin Insurance",
    "Woodgrove Insurance",
    "Litware Insurance",
    "Proseware Insurance",
    "Fourth Coffee Insurance",
    "Wide World Importers Insurance",
    "Alpine Ski Insurance",
    "Blue Yonder Insurance",
    "Coho Vineyard Insurance",
    "Margie Insurance",
    "Trey Research Insurance",
    "Adatum Insurance",
    "Munson Insurance",
    "Lucerne Insurance",
    "Relecloud Insurance",
    "Wingtip Insurance",
]


# ═══════════════════════════════════════════════════════════════════════════════
# RUSH CRITERIA - Conditions that qualify for ISRUSH diary
# ═══════════════════════════════════════════════════════════════════════════════

RUSH_CRITERIA: Dict[str, bool] = {
    "attorney_represented": True,
    "demand_over_limits": True,
    "statute_of_limitations_near": True,  # < 60 days
    "prior_demands_unanswered": True,
    "escalation_request": True,
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS CODES
# ═══════════════════════════════════════════════════════════════════════════════

COVERAGE_STATUS_CODES = {
    "confirmed": "Coverage has been confirmed",
    "pending": "Coverage verification is pending",
    "denied": "Coverage has been denied",
    "cvq": "Coverage question under review",
}

LIABILITY_STATUS_CODES = {
    "pending": "Liability decision is pending",
    "accepted": "Liability has been accepted",
    "denied": "Liability has been denied",
    "not_applicable": "Liability not applicable (no coverage)",
}

DEMAND_STATUS_CODES = {
    "not_received": "No demand received",
    "received": "Demand received, pending assignment",
    "assigned": "Demand assigned to handler",
    "under_review": "Demand under review",
    "paid": "Demand has been paid",
    "denied_no_coverage": "Demand denied - no coverage",
    "denied_no_liability": "Demand denied - no liability",
}


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK DATA - Claims with subrogation info
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_CLAIMS: Dict[str, Dict[str, Any]] = {
    "CLM-2024-001234": {
        "claim_number": "CLM-2024-001234",
        "insured_name": "John Smith",
        "loss_date": "2024-10-15",
        "claimant_carrier": "Contoso Insurance",
        "claimant_name": "Jane Doe",
        "status": "open",
        "coverage_status": "confirmed",
        "cvq_status": None,  # No coverage question
        "liability_decision": "pending",
        "liability_range_low": None,
        "liability_range_high": None,
        "pd_limits": 50000,
        "pd_payments": [],
        "subro_demand": {
            "received": True,
            "received_date": "2024-11-20",
            "amount": 12500.00,
            "assigned_to": "Sarah Johnson",
            "assigned_date": "2024-11-22",
            "status": "under_review",
        },
        "feature_owners": {
            "PD": "Sarah Johnson",
            "BI": "Mike Thompson",
            "SUBRO": "Sarah Johnson",
        },
    },
    "CLM-2024-005678": {
        "claim_number": "CLM-2024-005678",
        "insured_name": "Robert Williams",
        "loss_date": "2024-09-01",
        "claimant_carrier": "Fabrikam Insurance",
        "claimant_name": "Emily Chen",
        "status": "open",
        "coverage_status": "confirmed",
        "cvq_status": None,
        "liability_decision": "accepted",
        "liability_range_low": 80,
        "liability_range_high": 100,
        "pd_limits": 100000,
        "pd_payments": [
            {"date": "2024-10-15", "amount": 8500.00, "payee": "Fabrikam Insurance"},
        ],
        "subro_demand": {
            "received": True,
            "received_date": "2024-09-15",
            "amount": 8500.00,
            "assigned_to": "David Brown",
            "assigned_date": "2024-09-16",
            "status": "paid",
        },
        "feature_owners": {
            "PD": "David Brown",
            "BI": None,
            "SUBRO": "David Brown",
        },
    },
    "CLM-2024-009012": {
        "claim_number": "CLM-2024-009012",
        "insured_name": "Maria Garcia",
        "loss_date": "2024-11-28",
        "claimant_carrier": "Northwind Insurance",
        "claimant_name": "Tom Wilson",
        "status": "open",
        "coverage_status": "pending",
        "cvq_status": "coverage_verification_pending",
        "liability_decision": "pending",
        "liability_range_low": None,
        "liability_range_high": None,
        "pd_limits": 25000,
        "pd_payments": [],
        "subro_demand": {
            "received": False,
            "received_date": None,
            "amount": None,
            "assigned_to": None,
            "assigned_date": None,
            "status": "not_received",
        },
        "feature_owners": {
            "PD": "Jennifer Lee",
            "BI": None,
            "SUBRO": None,
        },
    },
    "CLM-2024-003456": {
        "claim_number": "CLM-2024-003456",
        "insured_name": "Kevin O'Brien",
        "loss_date": "2024-08-10",
        "claimant_carrier": "Tailspin Insurance",
        "claimant_name": "Susan Martinez",
        "status": "open",
        "coverage_status": "denied",
        "cvq_status": "policy_lapsed",
        "liability_decision": "not_applicable",
        "liability_range_low": None,
        "liability_range_high": None,
        "pd_limits": 0,
        "pd_payments": [],
        "subro_demand": {
            "received": True,
            "received_date": "2024-09-01",
            "amount": 15000.00,
            "assigned_to": None,
            "assigned_date": None,
            "status": "denied_no_coverage",
        },
        "feature_owners": {
            "PD": None,
            "BI": None,
            "SUBRO": None,
        },
    },
}
