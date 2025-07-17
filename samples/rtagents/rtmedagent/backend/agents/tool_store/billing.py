import json

from utils.ml_logging import get_logger

logger = get_logger()

billing_db = [
    {
        "patient_id": "P54321",
        "claim_number": "CLM1001",
        "invoice_date": "2024-03-05",
        "amount_due": "120.00",
        "status": "Denied",
        "reason": "Service not covered",
        "last_payment": "2024-02-01",
    },
    {
        "patient_id": "P98765",
        "claim_number": "CLM1002",
        "invoice_date": "2024-03-12",
        "amount_due": "75.50",
        "status": "Approved",
        "reason": "",
        "last_payment": "2024-03-01",
    },
    {
        "patient_id": "P11223",
        "claim_number": "CLM1003",
        "invoice_date": "2024-02-18",
        "amount_due": "0.00",
        "status": "Paid",
        "reason": "",
        "last_payment": "2024-02-20",
    },
]


async def insurance_billing_question(args: dict) -> str:
    """
    Simulates answering a billing or insurance question.
    Args:
        args: {
            "patient_id": str,
            "question_summary": str,
            "claim_number": Optional[str],
            "invoice_date": Optional[str]
        }
    Returns:
        JSON with billing/insurance info or status.
    """
    patient_id = args.get("patient_id")
    claim_number = args.get("claim_number")
    invoice_date = args.get("invoice_date")
    summary = args.get("question_summary", "").lower().strip()

    # Filter by patient
    patient_claims = [b for b in billing_db if b["patient_id"] == patient_id]
    if not patient_claims:
        return json.dumps(
            {
                "ok": False,
                "message": f"No billing records found for patient_id {patient_id}.",
                "data": None,
            }
        )

    if claim_number:
        for record in patient_claims:
            if record["claim_number"] == claim_number:
                return json.dumps(
                    {
                        "ok": True,
                        "message": f"Claim {claim_number} status: {record['status']}.",
                        "data": record,
                    }
                )

    if invoice_date:
        for record in patient_claims:
            if record["invoice_date"] == invoice_date:
                return json.dumps(
                    {
                        "ok": True,
                        "message": f"Invoice on {invoice_date}: amount due ${record['amount_due']}.",
                        "data": record,
                    }
                )

    if "denied" in summary:
        denied_claims = [r for r in patient_claims if r["status"] == "Denied"]
        if denied_claims:
            record = denied_claims[0]
            return json.dumps(
                {
                    "ok": True,
                    "message": f"Your claim {record['claim_number']} was denied: {record['reason']}.",
                    "data": record,
                }
            )
        else:
            return json.dumps(
                {"ok": True, "message": "No denied claims found.", "data": None}
            )

    if "balance" in summary or "owe" in summary:
        outstanding = [r for r in patient_claims if float(r["amount_due"]) > 0]
        if outstanding:
            due = outstanding[0]
            return json.dumps(
                {
                    "ok": True,
                    "message": f"Your current balance is ${due['amount_due']} for invoice dated {due['invoice_date']}.",
                    "data": due,
                }
            )
        else:
            return json.dumps(
                {
                    "ok": True,
                    "message": "You have no outstanding balances.",
                    "data": None,
                }
            )

    return json.dumps(
        {
            "ok": False,
            "message": "Sorry, I couldn't find billing details for your request.",
            "data": None,
        }
    )
