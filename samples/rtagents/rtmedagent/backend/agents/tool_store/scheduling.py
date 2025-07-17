import random
from datetime import date as _date
from datetime import timedelta as _timedelta
from typing import Any, Dict, List, Optional, TypedDict

from rtagents.RTMedAgent.backend.agents.tool_store.functions_helper import _json

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

appointments_db: Dict[str, List[Dict[str, Any]]] = {
    "Alice Brown": [
        {
            "appt_id": "A001",
            "date": "2024-07-02",
            "time": "09:30",
            "type": "annual_physical",
            "provider": "Dr. Smith",
            "status": "confirmed",
        },
        {
            "appt_id": "A002",
            "date": "2024-08-15",
            "time": "15:00",
            "type": "follow_up",
            "provider": "Dr. Smith",
            "status": "confirmed",
        },
    ],
    "Bob Johnson": [
        {
            "appt_id": "B100",
            "date": "2024-07-12",
            "time": "14:30",
            "type": "specialist_consult",
            "provider": "Dr. Patel",
            "status": "confirmed",
        },
        {
            "appt_id": "B101",
            "date": "2024-06-01",
            "time": "11:00",
            "type": "lab_results_review",
            "provider": "Dr. Lee",
            "status": "completed",
        },
    ],
    "Charlie Davis": [
        {
            "appt_id": "C200",
            "date": "2024-06-30",
            "time": "08:00",
            "type": "annual_physical",
            "provider": "Dr. Smith",
            "status": "cancelled",
        },
        {
            "appt_id": "C201",
            "date": "2024-07-30",
            "time": "10:15",
            "type": "immunization",
            "provider": "Nurse Williams",
            "status": "confirmed",
        },
    ],
    "Diana Evans": [
        {
            "appt_id": "D300",
            "date": "2024-07-25",
            "time": "16:00",
            "type": "telemedicine",
            "provider": "Dr. Nguyen",
            "status": "rescheduled",
        }
    ],
}


class ScheduleAppointmentArgs(TypedDict, total=False):
    patient_name: str
    dob: str  # YYYY-MM-DD
    appointment_type: str  # e.g. check-up, follow-up, annual physical, etc.
    preferred_date: str  # YYYY-MM-DD
    preferred_time: str  # HH:MM
    provider: Optional[str]


class ChangeAppointmentArgs(TypedDict, total=False):
    patient_name: str
    appt_id: str
    new_date: str
    new_time: str


class CancelAppointmentArgs(TypedDict, total=False):
    patient_name: str
    appt_id: str


class GetUpcomingAppointmentsArgs(TypedDict):
    patient_name: str


def _generate_appt_id() -> str:
    # Simple appointment ID generator
    return "A" + str(random.randint(100, 999))


async def schedule_appointment(args: ScheduleAppointmentArgs) -> str:
    name = args.get("patient_name", "")
    dob = args.get("dob", "")
    if not name or not dob:
        return _json(False, "Missing patient name or date of birth.")
    patient = patients_db.get(name)
    if not patient or patient["dob"] != dob:
        return _json(False, "Patient not found or DOB mismatch.")

    appt_type = args.get("appointment_type", "routine_checkup")
    date_str = args.get("preferred_date", str(_date.today() + _timedelta(days=5)))
    time_str = args.get("preferred_time", "09:00")
    provider = args.get("provider", "Dr. Smith")

    appt_id = _generate_appt_id()
    entry = {
        "appt_id": appt_id,
        "date": date_str,
        "time": time_str,
        "type": appt_type,
        "provider": provider,
        "status": "confirmed",
    }
    appointments_db.setdefault(name, []).append(entry)
    return _json(
        True,
        f"Appointment scheduled with {provider} on {date_str} at {time_str}.",
        appt_id=appt_id,
        date=date_str,
        time=time_str,
        provider=provider,
        appointment_type=appt_type,
    )


async def change_appointment(args: ChangeAppointmentArgs) -> str:
    name = args.get("patient_name", "")
    appt_id = args.get("appt_id", "")
    if not name or not appt_id:
        return _json(False, "Missing patient name or appointment ID.")

    appts = appointments_db.get(name, [])
    appt = next((a for a in appts if a["appt_id"] == appt_id), None)
    if not appt:
        return _json(False, f"Appointment ID {appt_id} not found for {name}.")

    new_date = args.get("new_date", appt["date"])
    new_time = args.get("new_time", appt["time"])
    appt["date"] = new_date
    appt["time"] = new_time
    appt["status"] = "rescheduled"
    return _json(
        True,
        f"Appointment {appt_id} rescheduled to {new_date} at {new_time}.",
        appt_id=appt_id,
        date=new_date,
        time=new_time,
        provider=appt.get("provider"),
        appointment_type=appt.get("type"),
    )


async def cancel_appointment(args: CancelAppointmentArgs) -> str:
    name = args.get("patient_name", "")
    appt_id = args.get("appt_id", "")
    if not name or not appt_id:
        return _json(False, "Missing patient name or appointment ID.")

    appts = appointments_db.get(name, [])
    idx = next((i for i, a in enumerate(appts) if a["appt_id"] == appt_id), None)
    if idx is None:
        return _json(False, f"Appointment ID {appt_id} not found for {name}.")

    cancelled = appts.pop(idx)
    return _json(
        True,
        f"Appointment {appt_id} with {cancelled['provider']} on {cancelled['date']} at {cancelled['time']} cancelled.",
        appt_id=appt_id,
        date=cancelled["date"],
        time=cancelled["time"],
        provider=cancelled["provider"],
        appointment_type=cancelled["type"],
    )


async def get_upcoming_appointments(args: GetUpcomingAppointmentsArgs) -> str:
    name = args.get("patient_name", "")
    if not name:
        return _json(False, "Missing patient name.")
    appts = appointments_db.get(name, [])
    if not appts:
        return _json(False, f"No upcoming appointments found for {name}.")
    upcoming = [a for a in appts if a["status"] in ("confirmed", "rescheduled")]
    return _json(True, f"Upcoming appointments for {name}.", appointments=upcoming)
