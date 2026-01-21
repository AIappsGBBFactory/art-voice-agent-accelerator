"""
Evaluation Event Schemas
=========================

Pydantic models for evaluation events - completely independent of production code.

These schemas define the structure of events captured during orchestration evaluation,
supporting both Chat Completions API and Responses API configurations.

Azure AI Foundry Integration
----------------------------
Includes schemas for exporting evaluation data to Azure AI Foundry's evaluation platform:
- FoundryEvaluatorConfig: Configure built-in evaluators (relevance, coherence, violence, etc.)
- FoundryDataRow: JSONL row format for Foundry dataset upload
- FoundryExportConfig: Export settings for Foundry-compatible output
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ============================================================================
# Azure AI Foundry Evaluator Types
# ============================================================================


class FoundryEvaluatorId(str, Enum):
    """
    Built-in Azure AI Foundry evaluator IDs.

    Reference: https://learn.microsoft.com/azure/ai-foundry/concepts/evaluation-approach-gen-ai
    """

    # Quality evaluators (require model deployment)
    RELEVANCE = "builtin.relevance"
    COHERENCE = "builtin.coherence"
    FLUENCY = "builtin.fluency"
    GROUNDEDNESS = "builtin.groundedness"
    SIMILARITY = "builtin.similarity"

    # Safety evaluators
    VIOLENCE = "builtin.violence"
    SEXUAL = "builtin.sexual"
    SELF_HARM = "builtin.self_harm"
    HATE_UNFAIRNESS = "builtin.hate_unfairness"

    # Traditional NLP metrics (no model required)
    F1_SCORE = "builtin.f1_score"
    BLEU_SCORE = "builtin.bleu_score"
    ROUGE_SCORE = "builtin.rouge_score"
    METEOR_SCORE = "builtin.meteor_score"
    GLEU_SCORE = "builtin.gleu_score"


class FoundryDataMapping(BaseModel):
    """
    Maps evaluation data fields to Foundry expected columns.

    Foundry expects specific field names; this maps from our TurnEvent fields.
    Uses ${data.field_name} syntax for dynamic mapping.
    """

    query: str = Field(
        default="${data.query}",
        description="Maps to user input/question field",
    )
    response: str = Field(
        default="${data.response}",
        description="Maps to agent response field",
    )
    context: Optional[str] = Field(
        default="${data.context}",
        description="Maps to context/evidence field (for groundedness)",
    )
    ground_truth: Optional[str] = Field(
        default="${data.ground_truth}",
        description="Maps to expected answer field (for similarity metrics)",
    )


class FoundryEvaluatorConfig(BaseModel):
    """
    Configuration for a single Foundry evaluator.

    Matches the EvaluatorConfiguration schema from azure-ai-projects SDK.
    """

    id: str = Field(
        ...,
        description="Evaluator ID (e.g., 'builtin.relevance' or custom evaluator path)",
    )
    init_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Initialization parameters (e.g., deployment_name for AI evaluators)",
    )
    data_mapping: FoundryDataMapping = Field(
        default_factory=FoundryDataMapping,
        description="Maps data fields to evaluator inputs",
    )


class FoundryDataRow(BaseModel):
    """
    Single row in Foundry-compatible JSONL dataset.

    This is the format expected by Azure AI Foundry's evaluation API.
    Each row represents one evaluation sample (typically one conversation turn).
    """

    # Core fields (always present)
    query: str = Field(..., description="User input/question")
    response: str = Field(..., description="Agent/model response")

    # Optional context fields
    context: Optional[str] = Field(
        None,
        description="Retrieved context or evidence (for RAG/groundedness evaluation)",
    )
    ground_truth: Optional[str] = Field(
        None,
        description="Expected/reference answer (for similarity metrics)",
    )

    # Metadata (preserved but not used by evaluators)
    turn_id: Optional[str] = Field(None, description="Turn identifier for tracing")
    session_id: Optional[str] = Field(None, description="Session identifier")
    agent_name: Optional[str] = Field(None, description="Agent that generated response")
    model_used: Optional[str] = Field(None, description="Model deployment used")
    scenario_name: Optional[str] = Field(None, description="Evaluation scenario name")

    # Additional metrics from our system (useful for correlation)
    e2e_ms: Optional[float] = Field(None, description="End-to-end latency")
    tools_called: Optional[List[str]] = Field(None, description="Tools invoked")
    tools_expected: Optional[List[str]] = Field(None, description="Expected tools from scenario YAML")


class FoundryExportConfig(BaseModel):
    """
    Configuration for exporting evaluation results to Foundry format.

    Specified in evaluation YAML under 'foundry_export' key.
    """

    enabled: bool = Field(default=False, description="Enable Foundry export")
    evaluators: List[FoundryEvaluatorConfig] = Field(
        default_factory=list,
        description="Evaluators to configure for Foundry evaluation",
    )
    output_filename: str = Field(
        default="foundry_eval.jsonl",
        description="Output filename for Foundry JSONL",
    )
    include_metadata: bool = Field(
        default=True,
        description="Include turn metadata in export (turn_id, agent, etc.)",
    )
    context_source: Literal["evidence", "conversation", "none"] = Field(
        default="evidence",
        description="Source for context field: 'evidence' (tool results), 'conversation' (history), or 'none'",
    )
    ground_truth_field: Optional[str] = Field(
        None,
        description="YAML field path for ground truth (e.g., 'expectations.expected_response')",
    )


# ============================================================================
# Original Evaluation Schemas
# ============================================================================


class ToolCall(BaseModel):
    """Record of a single tool invocation during a turn."""

    name: str = Field(..., description="Tool name (e.g., 'analyze_recent_transactions')")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    start_ts: float = Field(..., description="Start timestamp (seconds since epoch)")
    end_ts: float = Field(..., description="End timestamp (seconds since epoch)")
    duration_ms: float = Field(..., description="Duration in milliseconds")
    status: str = Field(default="success", description="'success' or 'error'")
    result_summary: Optional[str] = Field(
        None, description="First 200 chars of result (for debugging)"
    )
    result_hash: str = Field(..., description="SHA256 hash of result (for deduplication)")


class EvidenceBlob(BaseModel):
    """Evidence source for groundedness checking."""

    source: str = Field(..., description="Source identifier: 'tool:<tool_name>' or 'context:<key>'")
    content_hash: str = Field(..., description="SHA256 hash of content")
    content_excerpt: str = Field(..., description="First 200 chars of content")


class HandoffEvent(BaseModel):
    """Record of an agent handoff."""

    source_agent: str = Field(..., description="Agent that initiated handoff")
    target_agent: str = Field(..., description="Agent receiving handoff")
    tool_name: Optional[str] = Field(None, description="Handoff tool used (if applicable)")
    handoff_type: str = Field(
        default="discrete", description="'discrete' (tool-based) or 'announced' (greeting-based)"
    )
    context: Optional[str] = Field(None, description="Handoff context/reason")
    timestamp: float = Field(..., description="Handoff timestamp")


class EvalModelConfig(BaseModel):
    """Model configuration used for the turn - handles both API types."""

    model_name: str = Field(..., description="Deployment ID (e.g., 'gpt-4o', 'o1-preview')")
    model_family: Optional[str] = Field(
        None, description="Model family: 'gpt-4', 'gpt-5', 'o1', 'o3', 'o4'"
    )
    endpoint_used: str = Field(..., description="'chat' (Chat Completions) or 'responses'")

    # Chat Completions API parameters
    temperature: Optional[float] = Field(None, description="Temperature (Chat API only)")
    top_p: Optional[float] = Field(None, description="Top-p sampling (Chat API only)")
    max_tokens: Optional[int] = Field(None, description="Max tokens (Chat API)")

    # Responses API parameters
    max_completion_tokens: Optional[int] = Field(
        None, description="Max completion tokens (Responses API)"
    )
    verbosity: Optional[int] = Field(
        None, description="Verbosity level: 0=minimal, 1=standard, 2=detailed (Responses API)"
    )
    reasoning_effort: Optional[str] = Field(
        None, description="Reasoning effort: 'low', 'medium', 'high' (o1/o3/o4 only)"
    )
    include_reasoning: Optional[bool] = Field(
        None, description="Include reasoning tokens in response (o1/o3/o4 only)"
    )

    # Newer sampling params (GPT-5+)
    min_p: Optional[float] = Field(None, description="Minimum probability threshold")
    typical_p: Optional[float] = Field(None, description="Typical sampling")


class TurnEvent(BaseModel):
    """Complete record of a single conversation turn."""

    # Identifiers
    session_id: str = Field(..., description="Session/run identifier")
    turn_id: str = Field(..., description="Unique turn identifier")
    scenario_name: Optional[str] = Field(None, description="Scenario name (if from test suite)")

    # Timing
    user_end_ts: float = Field(..., description="User input end timestamp")
    agent_first_output_ts: Optional[float] = Field(
        None, description="First token from agent (TTFT)"
    )
    agent_last_output_ts: float = Field(..., description="Last output timestamp")
    e2e_ms: float = Field(..., description="End-to-end turn time (milliseconds)")
    ttft_ms: Optional[float] = Field(None, description="Time to first token (milliseconds)")

    # Agent state
    agent_name: str = Field(..., description="Active agent for this turn")
    previous_agent: Optional[str] = Field(None, description="Previous agent (if handoff occurred)")

    # Content
    user_text: str = Field(..., description="User input text")
    response_text: str = Field(..., description="Agent response text")
    response_tokens: Optional[int] = Field(None, description="Response token count")
    input_tokens: Optional[int] = Field(None, description="Input token count")
    reasoning_tokens: Optional[int] = Field(
        None, description="Reasoning tokens (o1/o3/o4 with include_reasoning=true)"
    )

    # Tool calls
    tool_calls: List[ToolCall] = Field(default_factory=list, description="Tools called this turn")

    # Evidence (for groundedness checking)
    evidence_blobs: List[EvidenceBlob] = Field(
        default_factory=list, description="Evidence sources for grounding validation"
    )

    # Handoff (if occurred)
    handoff: Optional[HandoffEvent] = Field(None, description="Handoff event (if occurred)")

    # Model configuration
    eval_model_config: EvalModelConfig = Field(..., description="Model configuration used")

    # Metadata
    commit_sha: Optional[str] = Field(None, description="Git commit SHA (for versioning)")
    error: Optional[str] = Field(None, description="Error message (if turn failed)")


class ScenarioExpectations(BaseModel):
    """
    Expected behavior for a scenario turn (used for validation).

    Supported Attributes
    --------------------
    Tools:
        tools_called: List[str]
            Required tools that MUST be called (recall check).
            Test fails if any are missing.

        tools_optional: List[str]
            Optional tools (won't fail if missing, but won't hurt if called).

        tools_forbidden: List[str]
            Tools that MUST NOT be called (negative test).
            Test fails if any are called.

    Handoffs:
        handoff: Dict[str, str]
            Expected handoff: {"to_agent": "AgentName"}.
            Test fails if handoff doesn't happen to correct agent.

        no_handoff: bool
            If true, asserts NO handoff should occur this turn.

    Response Constraints:
        response_constraints: Dict[str, Any]
            max_tokens: int - Max response tokens (verbosity check)
            must_include: List[str] - Substrings that MUST appear in response
            must_not_include: List[str] - Substrings that MUST NOT appear
            must_ask_for: List[str] - Questions/prompts that should appear

    Grounding:
        grounding_required: List[str]
            Human-readable descriptions of facts that must be grounded.

        min_grounded_ratio: float
            Minimum grounded span ratio (0.0-1.0, default: 0.0).

    Performance:
        max_latency_ms: int
            Maximum allowed E2E latency in milliseconds.

    Example YAML
    ------------
    ```yaml
    turns:
      - turn_id: turn_1
        user_input: "Check my account balance"
        expectations:
          tools_called:
            - verify_client_identity
            - get_account_balance
          tools_forbidden:
            - transfer_funds
          handoff:
            to_agent: AccountAgent
          response_constraints:
            max_tokens: 100
            must_include:
              - "balance"
              - "$"
            must_not_include:
              - "error"
          min_grounded_ratio: 0.7
          max_latency_ms: 5000
    ```
    """

    # Tool expectations
    tools_called: List[str] = Field(
        default_factory=list,
        description="Required tool names that MUST be called (recall check)",
    )
    tools_optional: List[str] = Field(
        default_factory=list,
        description="Optional tools (won't fail if missing)",
    )
    tools_forbidden: List[str] = Field(
        default_factory=list,
        description="Tools that MUST NOT be called",
    )

    # Handoff expectations
    handoff: Optional[Dict[str, str]] = Field(
        None,
        description="Expected handoff: {'to_agent': 'AgentName'}",
    )
    no_handoff: bool = Field(
        default=False,
        description="Assert that NO handoff occurs this turn",
    )

    # Response constraints
    response_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="Response constraints: max_tokens, must_include, must_not_include, must_ask_for",
    )

    # Grounding expectations
    grounding_required: List[str] = Field(
        default_factory=list,
        description="Human-readable grounding requirements",
    )
    min_grounded_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum grounded span ratio (0.0-1.0)",
    )

    # Performance expectations
    max_latency_ms: Optional[int] = Field(
        None,
        description="Maximum allowed E2E latency in milliseconds",
    )


class TurnScore(BaseModel):
    """Computed scores for a single turn."""

    turn_id: str
    tool_precision: float = Field(..., description="Precision: executed_expected / executed_total")
    tool_recall: float = Field(..., description="Recall: executed_expected / expected_total")
    tool_efficiency: float = Field(
        ..., description="Efficiency: 1 - (redundant_calls / total_calls)"
    )
    grounded_span_ratio: float = Field(
        ..., description="Ratio of factual spans found in evidence"
    )
    unsupported_claim_count: int = Field(..., description="Count of spans NOT found in evidence")
    e2e_ms: float = Field(..., description="End-to-end latency (milliseconds)")
    ttft_ms: Optional[float] = Field(None, description="Time to first token (milliseconds)")
    verbosity_score: float = Field(..., description="Verbosity score (0-1, 1=within budget)")
    verbosity_tokens: int = Field(..., description="Actual response tokens")
    verbosity_budget: int = Field(..., description="Token budget used")


class PerTurnSummary(BaseModel):
    """Summary of a single turn for reporting."""

    turn_id: str
    agent_name: str
    model_used: str = Field(..., description="Model deployment actually used")
    e2e_ms: float
    tools_expected: List[str] = Field(default_factory=list, description="Expected tools from YAML")
    tools_called: List[str] = Field(default_factory=list, description="Actually called tools")
    tool_precision: float
    tool_recall: float
    grounded_span_ratio: float
    response_length: int = Field(..., description="Character count of response")
    error: Optional[str] = None


class RunSummary(BaseModel):
    """Aggregated metrics for a complete evaluation run."""

    run_id: str
    scenario_name: str
    agent_name: str
    total_turns: int
    eval_model_config: EvalModelConfig

    # Per-turn details for transparency
    per_turn_metrics: List[PerTurnSummary] = Field(
        default_factory=list, description="Per-turn breakdown for debugging"
    )

    # Aggregated metrics
    tool_metrics: Dict[str, Any] = Field(
        ...,
        description="Tool call metrics: total_calls, precision, recall, efficiency, redundant_calls",
    )
    latency_metrics: Dict[str, float] = Field(
        ..., description="Latency metrics: e2e_p50_ms, e2e_p95_ms, ttft_p50_ms, etc."
    )
    groundedness_metrics: Dict[str, float] = Field(
        ...,
        description="Groundedness metrics: avg_grounded_span_ratio, avg_unsupported_claims",
    )
    verbosity_metrics: Dict[str, Any] = Field(
        ..., description="Verbosity metrics: avg_response_tokens, budget_violations, etc."
    )
    handoff_metrics: Optional[Dict[str, Any]] = Field(
        None, description="Handoff metrics: total_handoffs, correct_handoffs, accuracy"
    )
    cost_analysis: Dict[str, Any] = Field(
        ...,
        description="Cost analysis: total tokens, estimated cost, breakdown by model",
    )

    # Metadata
    commit_sha: Optional[str] = None
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    pass_fail: Optional[bool] = Field(
        None, description="Overall pass/fail (if thresholds applied)"
    )


__all__ = [
    # Foundry integration
    "FoundryEvaluatorId",
    "FoundryDataMapping",
    "FoundryEvaluatorConfig",
    "FoundryDataRow",
    "FoundryExportConfig",
    # Original schemas
    "ToolCall",
    "EvidenceBlob",
    "HandoffEvent",
    "EvalModelConfig",
    "TurnEvent",
    "ScenarioExpectations",
    "TurnScore",
    "PerTurnSummary",
    "RunSummary",
]
