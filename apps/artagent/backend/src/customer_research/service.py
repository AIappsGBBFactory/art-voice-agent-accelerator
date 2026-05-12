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
- Each use case needs 2-5 agents (always include a Concierge/entry-point agent).
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
- Create 2-6 mock tools per use case that represent real operations \
  (e.g. check_order_status, lookup_patient_record).
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
- Include a handoff_condition describing when the source agent should trigger it.
- Set type to "discrete" for all handoffs — the transfer happens silently \
  without the source agent announcing it.

### Template Variables
- Always include: company_name, industry

### Naming Conventions
- Agent names: PascalCase (e.g. OrderSupport, BillingAgent)
- Tool names: snake_case (e.g. check_order_status)
- Handoff tools: handoff_{agent_name_snake_case} (e.g. handoff_order_support)

Be creative and realistic. The use cases should feel like genuine solutions \
for the specific company, not generic templates.
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


async def research_customer(company_name: str) -> ResearchResult:
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

    logger.info("Researching customer | company=%s deployment=%s", company_name, deployment)

    try:
        response = await _call_openai(client, deployment, company_name)

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


def _call_openai_sync(client, deployment: str, company_name: str):
    """Synchronous OpenAI call — to be run via asyncio.to_thread."""
    return client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Research the company '{company_name}' and propose voice-agent use cases."
                ),
            },
        ],
        response_format=_RESPONSE_SCHEMA,
        temperature=0.7,
        max_tokens=8192,
    )


async def _call_openai(client, deployment: str, company_name: str):
    """Run the synchronous OpenAI call off the event loop."""
    import asyncio

    return await asyncio.to_thread(_call_openai_sync, client, deployment, company_name)
