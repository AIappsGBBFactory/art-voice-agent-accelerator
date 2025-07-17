from datetime import date as _date
from typing import Any, Dict, List, Optional, TypedDict

from rtagents.RTMedAgent.backend.agents.tool_store.functions_helper import _json

# Simulated referral store: patient_name -> list of referrals
referrals_db: Dict[str, List[Dict[str, Any]]] = {
    "Alice Brown": [
        {
            "referral_id": "R001",
            "date_requested": "2024-06-10",
            "specialty": "Dermatology",
            "provider": "Dr. Kelly",
            "location": "Downtown Clinic",
            "status": "pending",
            "reason": "Rash evaluation",
            "insurance_details": "Blue Cross PPO",
            "urgency": "routine",
        }
    ],
    "Bob Johnson": [
        {
            "referral_id": "R002",
            "date_requested": "2024-07-01",
            "specialty": "Cardiology",
            "provider": "Dr. Lee",
            "location": "Cardio Center",
            "status": "approved",
            "reason": "Heart murmur",
            "insurance_details": "Aetna",
            "urgency": "urgent",
        }
    ],
    "Charlie Davis": [
        {
            "referral_id": "R003",
            "date_requested": "2024-07-12",
            "specialty": "Orthopedics",
            "provider": "Dr. Patel",
            "location": "West Side Ortho",
            "status": "scheduled",
            "reason": "Knee pain",
            "insurance_details": "United Healthcare",
            "urgency": "routine",
        }
    ],
}

specialist_directory: List[Dict[str, Any]] = [
    {
        "specialty": "Dermatology",
        "provider": "Dr. Kelly",
        "location": "Downtown Clinic",
        "accepting_new_patients": True,
    },
    {
        "specialty": "Cardiology",
        "provider": "Dr. Lee",
        "location": "Cardio Center",
        "accepting_new_patients": False,
    },
    {
        "specialty": "Orthopedics",
        "provider": "Dr. Patel",
        "location": "West Side Ortho",
        "accepting_new_patients": True,
    },
    {
        "specialty": "Endocrinology",
        "provider": "Dr. Smith",
        "location": "North Clinic",
        "accepting_new_patients": True,
    },
]


class RequestReferralArgs(TypedDict, total=False):
    patient_name: str
    specialty: str
    reason_for_referral: str
    provider_preference: Optional[str]
    preferred_location: Optional[str]
    urgency: Optional[str]
    insurance_details: Optional[str]


class CheckReferralStatusArgs(TypedDict):
    patient_name: str
    status_query: str  # referral ID, specialty, or provider


class GetSpecialistListArgs(TypedDict, total=False):
    specialty: Optional[str]
    location: Optional[str]


class EscalateEmergencyArgs(TypedDict):
    reason: str


async def request_referral(args: RequestReferralArgs) -> str:
    # Simulate storing the referral and returning confirmation
    patient = args["patient_name"]
    referral_id = f"R{len(referrals_db.get(patient, []))+1:03d}"
    record = {
        "referral_id": referral_id,
        "date_requested": str(_date.today()),
        "specialty": args.get("specialty"),
        "provider": args.get("provider_preference") or "To be assigned",
        "location": args.get("preferred_location") or "Any",
        "status": "pending",
        "reason": args.get("reason_for_referral"),
        "insurance_details": args.get("insurance_details"),
        "urgency": args.get("urgency", "routine"),
    }
    referrals_db.setdefault(patient, []).append(record)
    return _json(
        True,
        f"Referral to {record['specialty']} created with ID {referral_id}.",
        referral=record,
    )


async def get_specialist_list(args: GetSpecialistListArgs) -> str:
    results = [
        s
        for s in specialist_directory
        if (
            not args.get("specialty")
            or s["specialty"].lower() == args["specialty"].lower()
        )
        and (
            not args.get("location")
            or s["location"].lower() == args["location"].lower()
        )
    ]
    if not results:
        return _json(False, "No matching specialists found.")
    return _json(True, "Specialist(s) found.", specialists=results)


async def check_referral_status(args: CheckReferralStatusArgs) -> str:
    patient = args["patient_name"]
    query = args["status_query"].lower()
    for ref in referrals_db.get(patient, []):
        if (
            query in ref.get("referral_id", "").lower()
            or query in ref.get("specialty", "").lower()
            or query in ref.get("provider", "").lower()
        ):
            return _json(True, "Referral status found.", referral=ref)
    return _json(False, "No matching referral found.")
