"""
Customer Research Service
=========================

Uses Azure OpenAI to research a company and generate voice-agent use-case
proposals that can be directly built into ART sessions.
"""

from __future__ import annotations

import json
import os
from typing import Any

from apps.artagent.backend.src.customer_research.models import (
    ResearchResult,
)
from utils.ml_logging import get_logger

logger = get_logger("customer_research.service")

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are an expert solution architect specialising in AI-powered voice agent \
systems for enterprise customers. Given a company name, you will:

1. Research the company — what they do, their industry, their customers, and \
   common customer-service or internal operations pain points.
2. Propose exactly 3 realistic voice-agent use cases that a multi-agent voice system \
   could solve for this company.

For EACH use case you MUST produce a complete, self-contained specification:

### Agents
- Each use case needs at least 3 agents: 1 Concierge/entry-point agent and \
  at least 2 specialist agents. You may include up to 5 agents total.
- **IMPORTANT**: Every specialist agent MUST have at least 2 functional tools \
  assigned to it. Do not create specialist agents with 0 or 1 tools — each \
  specialist must be capable of performing meaningful work through tool calls.
- Every agent needs a clear role, a greeting, and a detailed system prompt \
  (at least 4-5 sentences describing behaviour, tone, and boundaries).
- Agents should have tools listed by name — ONLY list business/functional tools \
  here (e.g. check_order_status). Do NOT list handoff tools in the agent tools \
  array — handoff routing is injected automatically.
- **CRITICAL — Handoff behaviour in prompts**: Do NOT reference specific \
  agent names for handoffs inside agent prompts. Handoff routing instructions \
  (which agents to transfer to and when) are injected automatically at runtime. \
  Instead, agent prompts should include ONLY these generic handoff instructions:
  - For the concierge: "When the customer's request falls under a specialist's \
    expertise, transfer them immediately using the handoff_to_agent tool. \
    Do NOT announce or narrate the transfer. Do NOT say 'Let me transfer you'. \
    Simply call the tool silently — the target agent will continue seamlessly."
  - For specialists: "When the customer's request is outside your scope, \
    silently hand off back using handoff_to_agent. Do NOT announce the transfer."
- Do NOT mention specific agent names (like 'FlightStatusAgent') in the prompt \
  text. The system will inject the correct handoff targets at runtime.

### Tools
- Create enough mock tools so that every specialist agent has at least 2 tools. \
  Typically 4-8 tools per use case (e.g. check_order_status, lookup_patient_record).
- Each tool must have a name (snake_case), description, parameters as a list \
  of objects with name/type/description fields, and a mock_response as a \
  JSON-encoded string (e.g. "{{\\"status\\": \\"active\\", \\"balance\\": 1500.00}}").
- **IMPORTANT**: Do NOT create handoff tools here — handoffs are defined \
  separately in the handoffs list. Only create functional/business tools.
- Each agent's tools list must ONLY reference tools defined in the top-level \
  tools array. Do NOT reference tools that are not defined.

### Handoffs
- Define directed edges between agents.
- The tool name for handoffs should follow the pattern: handoff_{agent_name_snake_case}
- Every specialist agent should have a route back to the concierge.
- Every specialist agent should have at least one route to another specialist (not including itself) — this allows for more complex routing and prevents isolated agents.
- Include a handoff_condition describing when the source agent should trigger it.
- Set type to "discrete" for all handoffs — the transfer happens silently \
  without the source agent announcing it.

### Template Variables
- Always include: company_name, industry

### Value Proposition (for each use case)
- value_proposition: A compelling 2-3 sentence summary of the business value. \
  Include concrete impact areas (cost reduction, CSAT improvement, handle-time \
  reduction, etc.).
- pain_points: A list of 3-5 specific customer/business pain points addressed
- seller_pitch: A 3-4 sentence elevator pitch a seller could use to propose this
- estimated_monthly_callers: Estimate the number of callers per month this use case \
  would handle, based on the company's size, industry, and publicly available \
  information (e.g. a large airline might have 500,000+ monthly customer service \
  calls; a mid-size retailer might have 50,000-100,000). Use realistic industry \
  benchmarks.
- avg_cost_per_contact: The average cost per customer contact in USD for this \
  industry. Use known industry benchmarks (e.g. airlines $5-8, banking $4-6, \
  telecom $6-10, insurance $8-12, healthcare $10-15). Pick a specific number.
- estimated_annual_savings: A string describing the estimated annual cost savings \
  from automating this use case (e.g. "$4.2M annually by deflecting 60% of \
  500K monthly calls at $7 per contact"). Show the math briefly.
- roi_summary: A 2-3 sentence ROI narrative tying volume, cost-per-contact, \
  deflection rate, and savings together into a compelling business case.
- conversation_examples: 2-3 example conversation flows, each as an object with:
  - title: A short descriptive title (e.g. "Flight Rebooking After Cancellation")
  - flow: The customer's initial prompt/request that kicks off this conversation \
    flow. This is what the customer would say first (e.g. "Hi, my flight LH401 \
    was just cancelled and I need to get to Frankfurt by tomorrow morning.").
  - demo_script: A step-by-step demo walkthrough (6-10 steps) specific to THIS \
    conversation flow. Each step should show the customer's message AND the \
    agent's expected action or response, formatted as a numbered list. Example:
    "1. Customer says: 'Hi, my flight was cancelled and I need to rebook.'
     2. Concierge silently hands off to BookingAgent.
     3. BookingAgent calls lookup_flight(flight_number='LH401') and says: \
        'I can see your flight LH401 was cancelled. Let me find alternatives.'
     4. Customer says: 'I need to arrive by 9 AM tomorrow.'
     5. BookingAgent calls search_available_flights(...) and says: \
        'I found LH405 departing at 6:00 AM arriving at 8:45 AM. Shall I book it?'
     6. Customer says: 'Yes, please book it.'
     7. BookingAgent calls rebook_flight(...) and says: 'Done! Your new booking \
        is confirmed on LH405.'"
    The demo script MUST show tool calls being made by agents where relevant, \
    and MUST show handoffs between agents when they occur.

### Naming Conventions
- Agent names: PascalCase (e.g. OrderSupport, BillingAgent)
- Tool names: snake_case (e.g. check_order_status)
- Handoff tools: handoff_{agent_name_snake_case} (e.g. handoff_order_support)

Be creative and realistic. The use cases should feel like genuine and solving complex problems for the specific company, not generic templates. The demo scripts should give a few examples that trigger different agents within the conversation.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# JSON SCHEMA for structured output
# ═══════════════════════════════════════════════════════════════════════════════

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "research_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "company_summary": {"type": "string"},
                "industry": {"type": "string"},
                "use_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "icon": {"type": "string"},
                            "industry": {"type": "string"},
                            "start_agent": {"type": "string"},
                            "template_vars": {
                                "type": "object",
                                "properties": {
                                    "company_name": {"type": "string"},
                                    "industry": {"type": "string"},
                                },
                                "required": ["company_name", "industry"],
                                "additionalProperties": False,
                            },
                            "agents": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "greeting": {"type": "string"},
                                        "return_greeting": {"type": "string"},
                                        "prompt": {"type": "string"},
                                        "tools": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "handoff_trigger": {"type": "string"},
                                    },
                                    "required": [
                                        "name",
                                        "description",
                                        "greeting",
                                        "return_greeting",
                                        "prompt",
                                        "tools",
                                        "handoff_trigger",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "tools": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "parameters": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "type": {"type": "string"},
                                                    "description": {"type": "string"},
                                                },
                                                "required": ["name", "type", "description"],
                                                "additionalProperties": False,
                                            },
                                        },
                                        "required_params": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "mock_response": {
                                            "type": "string",
                                        },
                                    },
                                    "required": [
                                        "name",
                                        "description",
                                        "parameters",
                                        "required_params",
                                        "mock_response",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "handoffs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "from_agent": {"type": "string"},
                                        "to_agent": {"type": "string"},
                                        "tool": {"type": "string"},
                                        "type": {"type": "string"},
                                        "handoff_condition": {"type": "string"},
                                    },
                                    "required": [
                                        "from_agent",
                                        "to_agent",
                                        "tool",
                                        "type",
                                        "handoff_condition",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "value_proposition": {"type": "string"},
                            "pain_points": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "seller_pitch": {"type": "string"},
                            "estimated_monthly_callers": {"type": "integer"},
                            "avg_cost_per_contact": {"type": "number"},
                            "estimated_annual_savings": {"type": "string"},
                            "roi_summary": {"type": "string"},
                            "conversation_examples": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "flow": {"type": "string"},
                                        "demo_script": {"type": "string"},
                                    },
                                    "required": ["title", "flow", "demo_script"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "name",
                            "description",
                            "icon",
                            "industry",
                            "start_agent",
                            "template_vars",
                            "agents",
                            "tools",
                            "handoffs",
                            "value_proposition",
                            "pain_points",
                            "seller_pitch",
                            "estimated_monthly_callers",
                            "avg_cost_per_contact",
                            "estimated_annual_savings",
                            "roi_summary",
                            "conversation_examples",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["company_name", "company_summary", "industry", "use_cases"],
            "additionalProperties": False,
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


async def research_customer(
    company_name: str,
    *,
    industry: str = "",
    use_case_hint: str = "",
) -> ResearchResult:
    """
    Research a company and generate voice-agent use-case proposals.

    Uses Azure OpenAI with structured outputs to guarantee valid JSON.

    Args:
        company_name: The company/brand to research.

    Returns:
        ResearchResult with company info and 3 use-case specs.

    Raises:
        RuntimeError: If the Azure OpenAI call fails.
    """
    from src.aoai.client import get_client

    client = get_client()
    if not client:
        raise RuntimeError("Azure OpenAI client is not available. Check configuration.")

    deployment = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_ID") or "gpt-4o"
    )

    logger.info(
        "Researching customer | company=%s industry=%s use_case_hint=%s deployment=%s",
        company_name,
        industry,
        use_case_hint,
        deployment,
    )

    try:
        response = await _call_openai(
            client,
            deployment,
            company_name,
            industry=industry,
            use_case_hint=use_case_hint,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        result = ResearchResult.model_validate(data)

        logger.info(
            "Research complete | company=%s use_cases=%d",
            result.company_name,
            len(result.use_cases),
        )
        return result

    except Exception as exc:
        logger.error("Customer research failed | company=%s error=%s", company_name, exc)
        raise RuntimeError(f"Customer research failed: {exc}") from exc


def _call_openai_sync(
    client,
    deployment: str,
    company_name: str,
    *,
    industry: str = "",
    use_case_hint: str = "",
):
    """Synchronous OpenAI call — to be run via asyncio.to_thread."""
    user_content = f"Research the company '{company_name}' and propose voice-agent use cases."
    if industry:
        user_content += f"\n\nThe company operates in the {industry} industry."
    if use_case_hint:
        user_content += (
            f"\n\nThe user has a specific use case in mind: {use_case_hint}. "
            "Generate exactly 1 use case based on this description, with complete "
            "agents, tools, handoffs, and all supporting data."
        )
    else:
        user_content += (
            "\n\nYou MUST generate exactly 3 distinct use cases. "
            "Do not generate fewer than 3."
        )

    return client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=_RESPONSE_SCHEMA,
        temperature=0.7,
        max_tokens=16384,
    )


async def _call_openai(
    client,
    deployment: str,
    company_name: str,
    *,
    industry: str = "",
    use_case_hint: str = "",
):
    """Run the synchronous OpenAI call off the event loop."""
    import asyncio

    return await asyncio.to_thread(
        _call_openai_sync,
        client,
        deployment,
        company_name,
        industry=industry,
        use_case_hint=use_case_hint,
    )
