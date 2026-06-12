"""
Customer Research Models
========================

Pydantic models for the customer research and use-case builder pipeline.
These models define the structured output schema that Azure OpenAI returns
and that the builder service consumes to create agents, tools, and scenarios.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════════
# TOOL SPEC
# ═══════════════════════════════════════════════════════════════════════════════


class ToolParameterProperty(BaseModel):
    """A single parameter property for a tool."""

    name: str = Field(description="Parameter name")
    type: str = Field(description="JSON Schema type (string, integer, number, boolean)")
    description: str = Field(default="", description="Parameter description")


class ToolSpec(BaseModel):
    """Specification for a mock tool to be registered at runtime."""

    name: str = Field(description="Tool function name (snake_case, e.g. check_account_balance)")
    description: str = Field(description="What this tool does — shown to the LLM")
    parameters: list[ToolParameterProperty] = Field(
        default_factory=list,
        description="Tool parameters as a list",
    )
    required_params: list[str] = Field(
        default_factory=list,
        description="Which parameters are required",
    )
    mock_response: str = Field(
        default="{}",
        description="Static JSON response string the mock tool returns",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT SPEC
# ═══════════════════════════════════════════════════════════════════════════════


class AgentSpec(BaseModel):
    """Specification for creating a session-scoped agent."""

    name: str = Field(description="Agent display name (PascalCase, e.g. FraudAgent)")
    description: str = Field(description="One-line description of the agent's role")
    greeting: str = Field(description="What the agent says when a caller is first connected")
    return_greeting: str = Field(
        default="Welcome back. How else can I help?",
        description="What the agent says when a caller returns",
    )
    prompt: str = Field(description="Full system prompt for the agent (plain text, no Jinja)")
    tools: list[str] = Field(default_factory=list, description="Tool names this agent can use")
    handoff_trigger: str = Field(
        default="",
        description="Tool name that routes TO this agent (e.g. handoff_fraud_agent)",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF SPEC
# ═══════════════════════════════════════════════════════════════════════════════


class ConversationExample(BaseModel):
    """A single example conversation flow with its demo script."""

    title: str = Field(description="Short title for this conversation flow")
    flow: str = Field(
        description="Example conversation transcript (Customer: ... / Agent: ...)",
    )
    demo_script: str = Field(
        description="Step-by-step demo walkthrough for this specific flow",
    )


class HandoffSpec(BaseModel):
    """A directed edge in the agent handoff graph."""

    from_agent: str = Field(description="Source agent name")
    to_agent: str = Field(description="Target agent name")
    tool: str = Field(description="Handoff tool name that triggers this route")
    type: str = Field(default="discrete", description="'announced' or 'discrete'")
    handoff_condition: str = Field(
        default="",
        description="When the source agent should trigger this handoff",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# USE CASE SPEC
# ═══════════════════════════════════════════════════════════════════════════════


class UseCaseSpec(BaseModel):
    """Complete specification for a voice-agent use case that can be built."""

    name: str = Field(description="Use case title (e.g. 'Customer Support Triage')")
    description: str = Field(description="2-3 sentence description of what this use case does")
    icon: str = Field(default="🎯", description="Emoji icon for the scenario")
    industry: str = Field(description="Industry vertical (e.g. Banking, Healthcare, Retail)")
    agents: list[AgentSpec] = Field(description="Agents to create")
    tools: list[ToolSpec] = Field(description="Mock tools to register")
    handoffs: list[HandoffSpec] = Field(description="Handoff graph edges")
    start_agent: str = Field(description="Name of the entry-point agent")
    template_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Global template variables (e.g. company_name, industry)",
    )
    value_proposition: str = Field(
        default="",
        description="Summary of the business value this use case delivers",
    )
    pain_points: list[str] = Field(
        default_factory=list,
        description="Customer pain points this use case addresses",
    )
    seller_pitch: str = Field(
        default="",
        description="Elevator pitch a seller could use to propose this scenario",
    )
    estimated_monthly_callers: int = Field(
        default=0,
        description="Estimated number of callers per month based on business size",
    )
    avg_cost_per_contact: float = Field(
        default=0.0,
        description="Average cost per contact in USD for this industry",
    )
    estimated_annual_savings: str = Field(
        default="",
        description="Estimated annual cost savings from automation",
    )
    roi_summary: str = Field(
        default="",
        description="Brief ROI narrative tying volume, cost, and savings together",
    )
    conversation_examples: list[ConversationExample] = Field(
        default_factory=list,
        description="Example conversation flows with demo scripts",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RESEARCH RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class ResearchResult(BaseModel):
    """Output from the customer research service."""

    company_name: str = Field(description="Researched company name")
    company_summary: str = Field(description="Brief overview of the company")
    industry: str = Field(description="Primary industry")
    use_cases: list[UseCaseSpec] = Field(description="Proposed voice-agent use cases")


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class BuildResult(BaseModel):
    """Result of building a use case into a session."""

    session_id: str
    scenario_name: str
    agents_created: list[str]
    tools_created: list[str]
    status: str = "success"
