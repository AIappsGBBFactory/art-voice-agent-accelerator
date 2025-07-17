import inspect
import json
import time

from fastapi import WebSocket

from utils.ml_logging import get_logger

logger = get_logger("route_turn")

AGENT_CATEGORIES = [
    "Medication",
    "Billing",
    "Demographics",
    "Referrals",
    "General Healthcare",
    "Non-Healthcare",
    "Scheduling",
    "Translation",
]

INTENT_TO_AGENT = {
    "Medication": "MedicationAgent",
    "Billing": "BillingAgent",
    "Demographics": "DemographicsAgent",
    "Referrals": "ReferralsAgent",
    "General Healthcare": "GeneralHealthcareAgent",
    "Non-Healthcare": "NonHealthcareAgent",
    "Scheduling": "SchedulingAgent",
    "Translation": "TranslateAgent",
}


async def route_turn(cm, transcript: str, ws: WebSocket, *, is_acs: bool) -> None:
    """
    Orchestrates a user utterance: authentication, intent classification,
    and routing to the correct agent. Persists state after each step.
    Tracks latency and ensures slot/tool output persistence in context.
    """
    redis_mgr = ws.app.state.redis
    latency_tool = ws.state.lt

    if not cm.get_context("authenticated", False):
        latency_tool.start("processing")
        auth_agent = getattr(ws.app.state, "auth_agent", None)
        result = await auth_agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("processing", redis_mgr)
        if result and result.get("authenticated"):
            cm.update_context("authenticated", True)
            phone_number = result.get("phone_number")
            patient_dob = result.get("patient_dob")
            patient_id = result.get("patient_id")
            first_name = result.get("first_name")
            last_name = result.get("last_name")
            patient_name = (
                f"{first_name} {last_name}" if first_name and last_name else None
            )
            cm.update_context("phone_number", phone_number)
            cm.update_context("patient_dob", patient_dob)
            cm.update_context("patient_id", patient_id)
            cm.update_context("patient_name", patient_name)
            cm.update_slots(result.get("slots", {}))
            logger.info(f"Session {cm.session_id} authenticated successfully.")

    elif not cm.get_context("active_agent"):
        intent_classifier_agent = getattr(ws.app.state, "intent_classifier_agent", None)
        messages = [
            {
                "role": "system",
                "content": intent_classifier_agent.pm.get_prompt(
                    "intent_classifier_agent.jinja"
                ),
            },
            {"role": "user", "content": transcript},
        ]
        latency_tool.start("processing_intent")
        response = ws.app.state.azureopenai_client.chat.completions.create(
            messages=messages,
            max_completion_tokens=intent_classifier_agent.max_tokens,
            temperature=intent_classifier_agent.temperature,
            top_p=intent_classifier_agent.top_p,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            model=intent_classifier_agent.model_id,
        )
        intent_result = response.choices[0].message.content.strip()
        try:
            logger.info(f"Intent classifier result: {intent_result}")
            intent_json = json.loads(intent_result)
            intent_category = intent_json.get("category")
            intent = intent_json.get("intent")
            slots = intent_json.get("slots", {})
            cm.update_context("intent", intent)
            cm.update_slots(slots)
            if not intent_category:
                raise ValueError("No category in classifier response.")
        except Exception as e:
            logger.error(f"Intent classifier error: {e}. Raw: {intent_result}")
            intent_category = "Non-Healthcare"
            intent = None
            slots = {}
        agent_key = INTENT_TO_AGENT.get(intent_category)
        agent = getattr(ws.app.state, agent_key, None)
        if not agent:
            logger.error(
                f"Agent '{agent_key}' not found! Fallback to NonHealthcareAgent."
            )
            agent = getattr(ws.app.state, "NonHealthcareAgent", None)
        cm.update_context("active_agent", agent_key)

        latency_tool.start(f"processing_{agent_key}")
        result = await agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop(f"processing_{agent_key}", redis_mgr)

        if isinstance(result, dict) and result.get("finalize", False):
            cm.update_context("active_agent", None)
            logger.info(f"Agent '{agent_key}' finalized session, rerouting next turn.")

        # If agent produces any tool outputs, persist them (context snapshot)
        if isinstance(result, dict):
            tool_name = result.get("tool_name")
            tool_output = result.get("tool_output")
            if tool_name and tool_output:
                cm.persist_tool_output(tool_name, tool_output)
    else:
        agent_key = cm.get_context("active_agent")
        agent = getattr(ws.app.state, agent_key, None)
        if not agent:
            logger.error(
                f"Agent '{agent_key}' not found! Fallback to NonHealthcareAgent."
            )
            agent = getattr(ws.app.state, "NonHealthcareAgent", None)
        latency_tool.start(f"processing_{agent_key}")
        # Run the agent turn (may call backend tools, produce outputs)
        result = await agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop(f"processing_{agent_key}", redis_mgr)

        if isinstance(result, dict) and result.get("finalize", True):
            cm.update_context("active_agent", None)
            handoffs = cm.get_context("handoff_history", [])
            handoffs.append(
                {
                    "from_agent": agent_key,
                    "at": time.time(),
                    "reason": result.get("handoff_reason", "unspecified"),
                }
            )
            cm.update_context("handoff_history", handoffs)
            logger.info(f"Agent '{agent_key}' finalized session, rerouting next turn.")

        if isinstance(result, dict):
            tool_name = result.get("tool_name")
            tool_output = result.get("tool_output")
            if tool_name and tool_output:
                cm.persist_tool_output(tool_name, tool_output)

    # Always persist conversation state to Redis after each turn
    cm.persist_to_redis(redis_mgr)
