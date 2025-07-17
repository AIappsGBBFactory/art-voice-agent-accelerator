import datetime
import json
import re

import openai


def _strip_fence(txt: str) -> str:
    """Remove ```json … ``` fences if present."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip(), flags=re.I)


PROMPT_TEMPLATE = """
You are an AI call wrap-up assistant.
Your job is to produce a MEMORY record **as a single JSON block**.

### INPUT
- Full dialog turns (chronological):
{history}
- Session context:
{context}

### RULES
1. **summary** → Maximum 3 plain-English sentences; capture only the final outcome and key details. Do not include details about successful authentication—only mention authentication if there are multiple failures.
2. **sentiment** → "positive", "neutral", or "negative" based on the caller's mood and the agent's tone.
3. **intent** → One of: "authentication", "claim_filed", "claim_inquiry", "other".
4. **entities** → Extract if present: caller_name, policy_id, claim_id.
5. Output **one valid JSON object** with keys:
{{
  "summary": "",
  "sentiment": "",
  "intent": "",
  "entities": {{
    "caller_name": "",
    "policy_id": "",
    "claim_id": ""
  }}
}}
""".strip()


async def build_memory(history, context, openai_client):
    # Pretty-print history to avoid brace collisions
    hist_str = json.dumps(history, indent=2, ensure_ascii=False)
    ctx_str = json.dumps(context, indent=2, ensure_ascii=False)

    prompt = PROMPT_TEMPLATE.format(history=hist_str, context=ctx_str)

    resp = await openai_client.generate_chat_response(
        query=prompt, conversation_history=[], temperature=0.2
    )

    raw = resp["response"]
    try:
        memory_json = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\n---RAW---\n{raw}")

    # Add technical metadata
    memory_json.update(
        user_id=context.get("caller_name", "unknown"),
        timestamp=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
    return memory_json
