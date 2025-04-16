"""
functions.py

This module implements the function-calling tools for the Healthcare Voice Agent.
Each function simulates interaction with internal structured data (represented as in-memory dictionaries),
validates inputs, retrieves matching records, and returns appropriate responses.

The structure is designed for easy replacement with real databases or services in the future.
"""

from typing import Any, Dict, Optional

# ------------------------------------------
# Simulated Internal Data ("Databases")
# ------------------------------------------

# Patients and their basic information
patients_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {"dob": "1987-04-12", "patient_id": "P54321", "phone": "555-4321"},
    "Bob Johnson": {"dob": "1992-11-25", "patient_id": "P98765", "phone": "555-8765"},
    "Charlie Davis": {"dob": "1980-01-15", "patient_id": "P11223", "phone": "555-1122"},
    "Diana Evans": {"dob": "1995-07-08", "patient_id": "P33445", "phone": "555-3344"},
    "Ethan Foster": {"dob": "1983-03-22", "patient_id": "P55667", "phone": "555-5566"},
    "Fiona Green": {"dob": "1998-09-10", "patient_id": "P77889", "phone": "555-7788"},
    "George Harris": {"dob": "1975-12-05", "patient_id": "P99001", "phone": "555-9900"},
    "Hannah Irving": {"dob": "1989-06-30", "patient_id": "P22334", "phone": "555-2233"},
    "Ian Jackson": {"dob": "1993-02-18", "patient_id": "P44556", "phone": "555-4455"},
    "Julia King": {"dob": "1986-08-14", "patient_id": "P66778", "phone": "555-6677"},
}

# Patient medications and refill info
prescriptions_db: Dict[str, Dict[str, Dict[str, str]]] = {
    "Alice Brown": {"Metformin": {"last_refill": "2024-03-01", "pharmacy": "City Pharmacy"}},
    "Bob Johnson": {"Atorvastatin": {"last_refill": "2024-02-20", "pharmacy": "Town Pharmacy"}},
    "Charlie Davis": {"Lisinopril": {"last_refill": "2024-01-15", "pharmacy": "Central Pharmacy"}},
    "Diana Evans": {"Omeprazole": {"last_refill": "2024-03-05", "pharmacy": "East Pharmacy"}},
    "Ethan Foster": {"Amlodipine": {"last_refill": "2024-02-28", "pharmacy": "West Pharmacy"}},
    "Fiona Green": {"Levothyroxine": {"last_refill": "2024-03-10", "pharmacy": "North Pharmacy"}},
    "George Harris": {"Simvastatin": {"last_refill": "2024-01-25", "pharmacy": "South Pharmacy"}},
    "Hannah Irving": {"Losartan": {"last_refill": "2024-02-15", "pharmacy": "Downtown Pharmacy"}},
    "Ian Jackson": {"Hydrochlorothiazide": {"last_refill": "2024-03-12", "pharmacy": "Uptown Pharmacy"}},
    "Julia King": {"Gabapentin": {"last_refill": "2024-03-08", "pharmacy": "Suburban Pharmacy"}},
}

# Medication information
medications_info_db: Dict[str, str] = {
    "Metformin": "Metformin is used to treat type 2 diabetes. Common side effects include nausea and diarrhea.",
    "Atorvastatin": "Atorvastatin is used to lower cholesterol. Side effects may include muscle pain and digestive issues.",
    "Lisinopril": "Lisinopril is used to treat high blood pressure. Side effects may include dizziness and dry cough.",
    "Omeprazole": "Omeprazole is used to treat acid reflux. Side effects may include headache and abdominal pain.",
    "Amlodipine": "Amlodipine is used to treat high blood pressure. Side effects may include swelling and fatigue.",
    "Levothyroxine": "Levothyroxine is used to treat hypothyroidism. Side effects may include weight loss and heat sensitivity.",
    "Simvastatin": "Simvastatin is used to lower cholesterol. Side effects may include muscle pain and liver issues.",
    "Losartan": "Losartan is used to treat high blood pressure. Side effects may include dizziness and back pain.",
    "Hydrochlorothiazide": "Hydrochlorothiazide is used to treat fluid retention. Side effects may include increased urination and dizziness.",
    "Gabapentin": "Gabapentin is used to treat nerve pain. Side effects may include drowsiness and dizziness.",
}

_fake_user_database = [
    {"first_name": "Alice", "last_name": "Brown", "phone_number": "5551234567"},
    {"first_name": "Bob", "last_name": "Johnson", "phone_number": "5559876543"},
    {"first_name": "Charlie", "last_name": "Davis", "phone_number": "5551122334"},
    {"first_name": "Diana", "last_name": "Evans", "phone_number": "5553344556"},
    {"first_name": "Ethan", "last_name": "Foster", "phone_number": "5555566778"},
    {"first_name": "Fiona", "last_name": "Green", "phone_number": "5557788990"},
    {"first_name": "George", "last_name": "Harris", "phone_number": "5559900112"},
    {"first_name": "Hannah", "last_name": "Irving", "phone_number": "5552233445"},
    {"first_name": "Ian", "last_name": "Jackson", "phone_number": "5554455667"},
    {"first_name": "Julia", "last_name": "King", "phone_number": "5556677889"},
]

# Functions
# ----------------------------------------
# New: User Authentication Tool
# ----------------------------------------

async def authenticate_user(args: Dict[str, Any]) -> str:
    """
    Authenticates a user by matching first name, last name, and phone number.
    """
    first_name = args.get("first_name", "").strip().lower()
    last_name = args.get("last_name", "").strip().lower()
    phone_number = args.get("phone_number", "").strip()

    if not (first_name and last_name and phone_number):
        return "❌ Authentication failed: missing information."

    # Simulate database search
    for record in _fake_user_database:
        if (record["first_name"].lower() == first_name and
            record["last_name"].lower() == last_name and
            record["phone_number"] == phone_number):
            return f"✅ Authentication successful for {record['first_name']} {record['last_name']}."

    return "❌ Authentication failed: user not found."


async def schedule_appointment(args: Dict[str, Any]) -> str:
    """
    Schedule or modify a healthcare appointment based on patient information.

    Parameters
    ----------
    args : dict
        A dictionary containing:
            - patient_name (str): Full name of the patient.
            - dob (str): Date of birth in 'YYYY-MM-DD' format.
            - appointment_type (str): Type of appointment (e.g., consultation, follow-up).
            - preferred_date (str, optional): Preferred appointment date in 'YYYY-MM-DD' format.
            - preferred_time (str, optional): Preferred appointment time (e.g., '10:00 AM').

    Returns
    -------
    str
        Confirmation message or error if patient not found.
    """
    patient_name = args.get("patient_name")
    dob = args.get("dob")
    appointment_type = args.get("appointment_type")
    preferred_date = args.get("preferred_date", "next available date")
    preferred_time = args.get("preferred_time", "next available time")

    patient_record = patients_db.get(patient_name)

    if not patient_record or patient_record["dob"] != dob:
        return f"❌ Unable to find patient {patient_name} with the provided date of birth. Please verify your information."

    return f"✅ Appointment for {patient_name} ({appointment_type}) scheduled on {preferred_date} at {preferred_time}."


async def refill_prescription(args: Dict[str, Any]) -> str:
    """
    Process a prescription refill request after verifying the patient's prescription history.

    Parameters
    ----------
    args : dict
        A dictionary containing:
            - patient_name (str): Full name of the patient.
            - medication_name (str): Name of the medication to refill.
            - pharmacy (str, optional): Preferred pharmacy name or location.

    Returns
    -------
    str
        Confirmation message or appropriate error.
    """
    patient_name = args.get("patient_name")
    medication_name = args.get("medication_name")
    requested_pharmacy = args.get("pharmacy")

    prescriptions = prescriptions_db.get(patient_name)
    if not prescriptions or medication_name not in prescriptions:
        return f"❌ No prescription record found for {medication_name} under {patient_name}. Please verify the medication name."

    existing_pharmacy = prescriptions[medication_name]["pharmacy"]
    pharmacy = requested_pharmacy or existing_pharmacy

    return f"✅ Prescription refill for {medication_name} submitted to {pharmacy} for {patient_name}."


async def lookup_medication_info(args: Dict[str, Any]) -> str:
    """
    Retrieve detailed information about a specific medication.

    Parameters
    ----------
    args : dict
        A dictionary containing:
            - medication_name (str): Name of the medication.

    Returns
    -------
    str
        Medication information or error if medication not found.
    """
    medication_name = args.get("medication_name")

    info = medications_info_db.get(medication_name)
    if not info:
        return f"❌ Medication {medication_name} not found in our system."

    return f"ℹ️ {medication_name}: {info}"


async def evaluate_prior_authorization(args: Dict[str, Any]) -> str:
    """
    Simulate the evaluation of a prior authorization request.

    Parameters
    ----------
    args : dict
        A dictionary containing:
            - patient_info (dict): Patient demographics and identifiers.
            - physician_info (dict): Physician specialty and contact details.
            - clinical_info (dict): Clinical diagnosis, lab results, prior treatments.
            - treatment_plan (dict): Requested treatment or medication plan.
            - policy_text (str): Insurance or payer policy text to evaluate against.

    Returns
    -------
    str
        Basic simulated evaluation result.
    """
    patient_info = args.get("patient_info", {})
    treatment_plan = args.get("treatment_plan", {})

    patient_name = patient_info.get("patient_name", "Unknown Patient")
    requested_medication = treatment_plan.get("requested_medication", "unknown medication")

    if not patient_name or not requested_medication:
        return "❌ Missing critical information for prior authorization evaluation."

    return f"✅ Prior authorization for {requested_medication} for {patient_name} has been reviewed. Further clinical validation may be required."


async def escalate_emergency(reason) -> str:
    """
    Escalate an emergency healthcare concern to a live agent.

    Parameters
    ----------
    args : dict
        A dictionary containing:
            - reason (str): Reason for the escalation (e.g., chest pain, severe symptoms).

    Returns
    -------
    str
        Acknowledgement of escalation.
    """
    return f"🚨 Emergency escalation triggered: {reason}. A human healthcare agent is now being connected."
