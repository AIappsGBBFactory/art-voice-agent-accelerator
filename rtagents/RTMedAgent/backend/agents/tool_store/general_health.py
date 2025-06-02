import json
from rtagents.RTMedAgent.backend.agents.tool_store.functions_helper import _json
from datetime import date as _date, timedelta as _timedelta
from typing import Dict, TypedDict

class ScheduleAppointmentArgs(TypedDict, total=False):
    patient_name: str
    dob: str  # ISO format: YYYY-MM-DD
    appointment_type: str
    preferred_date: str
    preferred_time: str

general_health_qa_db = {
    "improve my sleep": "To improve sleep, maintain a consistent bedtime, avoid screens before bed, and create a restful environment. If you have ongoing problems, please consult your physician.",
    "prevent colds": "Wash your hands frequently, eat a balanced diet, and get enough sleep to help prevent common colds.",
    "lower blood pressure": "Healthy eating, regular physical activity, stress reduction, and following your doctor's advice are key for blood pressure control.",
    "increase energy": "Regular exercise, healthy diet, and adequate sleep can help boost your energy.",
    "wellness check": "An annual wellness checkup is recommended. Your provider can help with scheduling and any questions.",
}

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

async def general_health_question(args: dict) -> str:
    """
    Answers a general health/wellness question.
    Args:
        args: { "question_summary": str }
    Returns:
        JSON with answer or escalation advice.
    """
    q = args.get("question_summary", "").lower().strip()
    for k, v in general_health_qa_db.items():
        if k in q:
            return json.dumps({
                "ok": True,
                "message": v,
                "data": {"matched_topic": k}
            })
    # If not found, always respond that a provider visit is needed
    return json.dumps({
        "ok": False,
        "message": "I'm unable to answer this question. Please schedule a visit with your provider for personal medical advice.",
        "data": None
    })

