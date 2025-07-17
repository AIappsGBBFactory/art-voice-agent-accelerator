import json
from datetime import date as _date
from datetime import timedelta as _timedelta
from difflib import SequenceMatcher
from typing import Dict, TypedDict

from rtagents.RTMedAgent.backend.agents.tool_store.functions_helper import _json


class GeneralHealthQuestionArgs(TypedDict):
    question_summary: str


general_health_qa_db = {
    "improve my sleep": "To improve sleep, maintain a consistent bedtime, avoid screens before bed, and create a restful environment. If you have ongoing problems, please consult your physician.",
    "prevent colds": "Wash your hands frequently, eat a balanced diet, and get enough sleep to help prevent common colds.",
    "lower blood pressure": "Healthy eating, regular physical activity, stress reduction, and following your doctor's advice are key for blood pressure control.",
    "increase energy": "Regular exercise, healthy diet, and adequate sleep can help boost your energy.",
    "wellness check": "An annual wellness checkup is recommended. Your provider can help with scheduling and any questions.",
}


def _fuzzy_match(query: str, choices: Dict[str, str], threshold: float = 0.7):
    best_score = 0
    best_key = None
    for k in choices:
        score = SequenceMatcher(None, k, query).ratio()
        if score > best_score:
            best_score = score
            best_key = k
    if best_score >= threshold:
        return best_key
    return None


async def general_health_question(args: GeneralHealthQuestionArgs) -> str:
    """
    Answers a general health/wellness question.
    Args:
        args: { "question_summary": str }
    Returns:
        JSON with answer or escalation advice.
    """
    q = args.get("question_summary", "").lower().strip()
    match = _fuzzy_match(q, general_health_qa_db, threshold=0.7)
    if match:
        return json.dumps(
            {
                "ok": True,
                "message": general_health_qa_db[match],
                "data": {"matched_topic": match},
            }
        )
    # If not found, always respond that a provider visit is needed
    return json.dumps(
        {
            "ok": False,
            "message": "I'm unable to answer this question. Please schedule a visit with your provider for personal medical advice.",
            "data": None,
        }
    )
