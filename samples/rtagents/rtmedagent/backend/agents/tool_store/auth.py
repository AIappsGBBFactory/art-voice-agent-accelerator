from typing import Any, Dict, List, TypedDict

from utils.ml_logging import get_logger

logger = get_logger()

# Patients and their basic information
patients_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {"dob": "1987-04-12", "patient_id": "P54321", "phone": "5552971078"},
    "Bob Johnson": {"dob": "1992-11-25", "patient_id": "P98765", "phone": "5558484555"},
    "Charlie Davis": {
        "dob": "1980-01-15",
        "patient_id": "P11223",
        "phone": "5559890662",
    },
    "Diana Evans": {"dob": "1995-07-08", "patient_id": "P33445", "phone": "5554608513"},
    "Ethan Foster": {
        "dob": "1983-03-22",
        "patient_id": "P55667",
        "phone": "5558771166",
    },
    "Fiona Green": {"dob": "1998-09-10", "patient_id": "P77889", "phone": "5557489234"},
    "George Harris": {
        "dob": "1975-12-05",
        "patient_id": "P99001",
        "phone": "5558649200",
    },
    "Hannah Irving": {
        "dob": "1989-06-30",
        "patient_id": "P22334",
        "phone": "5554797595",
    },
    "Ian Jackson": {"dob": "1993-02-18", "patient_id": "P44556", "phone": "5551374879"},
    "Julia King": {"dob": "1986-08-14", "patient_id": "P66778", "phone": "5559643430"},
}


class AuthenticateArgs(TypedDict):
    first_name: str
    last_name: str
    phone_number: str


async def authenticate_user(args: AuthenticateArgs) -> Dict[str, Any]:
    first = args["first_name"].strip().title()
    last = args["last_name"].strip().title()
    phone = args["phone_number"].strip()
    full = f"{first} {last}"

    logger.info(f"🔎 Checking user: {full} with phone: {phone}")

    rec = patients_db.get(full)
    if not rec:
        logger.warning(f"❌ No record for name: {full}")
        return {
            "authenticated": False,
            "message": f"Name '{full}' not found.",
            "patient_id": None,
        }

    stored_phone = rec["phone"].replace("-", "").strip()
    phone = phone.replace("-", "").strip()

    logger.info(f"📞 Cleaned stored phone: {stored_phone}")
    logger.info(f"📞 Cleaned input phone:  {phone}")

    if stored_phone == phone:
        logger.info(f"✅ Authentication succeeded for {full}")
        return {
            "authenticated": True,
            "message": f"Authenticated {full}.",
            "patient_id": rec["patient_id"],
            "first_name": first,
            "last_name": last,
            "phone_number": phone,
        }
    else:
        logger.warning(
            f"❌ Phone mismatch for {full}: expected {stored_phone}, got {phone}"
        )
        return {
            "authenticated": False,
            "message": "Authentication failed – name or phone mismatch.",
            "patient_id": None,
        }
