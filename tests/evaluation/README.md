# Evaluation Package

Model-to-model evaluation framework for voice agent orchestration.

## Quick Links

📚 **[Full Documentation](../../docs/testing/model-evaluation.md)** - Complete guide with examples

## Quick Start

### 1. Record Events

```python
from tests.evaluation import (
    EventRecorder,
    EvaluationOrchestratorWrapper
)
from pathlib import Path

# Wrap your orchestrator
recorder = EventRecorder(run_id="test_001", output_dir=Path("runs"))
eval_orch = EvaluationOrchestratorWrapper(your_orchestrator, recorder)

# Use normally - recording happens automatically
await eval_orch.process_turn(context)
```

### 2. Score Events (Unified CLI)

```bash
# Score existing events
python -m tests.evaluation.cli score \
    --input runs/test_001_events.jsonl \
    --output runs/test_001_scores

# Run a scenario
python -m tests.evaluation.cli scenario \
    --input tests/eval_scenarios/fraud_basic.yaml

# Run A/B comparison
python -m tests.evaluation.cli compare \
    --input tests/eval_scenarios/ab_tests/fraud_detection_comparison.yaml
```

## Package Structure

```text
evaluation/
├── __init__.py              # Package exports + import guards
├── schemas.py               # Pydantic models (TurnEvent, etc.)
├── recorder.py              # EventRecorder
├── wrappers.py              # EvaluationOrchestratorWrapper
├── scorer.py                # MetricsScorer
├── validator.py             # Expectation validation
├── scenario_runner.py       # ScenarioRunner + ComparisonRunner
├── foundry_exporter.py      # Azure AI Foundry integration
├── cli/
│   └── __main__.py          # Unified CLI (score, scenario, compare, submit)
├── README.md                # This file
└── scenarios/               # YAML test scenarios
```

## Key Principles

✅ **Zero production changes** - Wrapper pattern, no code modifications
✅ **API-aware** - Handles Chat Completions and Responses API
✅ **Import guards** - Prevents accidental production imports
✅ **One-way imports** - eval → production (never reverse)

## Validation

Run automated tests:

```bash
# All tests
python apps/artagent/backend/evaluation/validate_phases.py

# Specific phase
python apps/artagent/backend/evaluation/validate_phases.py --phase 1
```

## Components

### Core (Phases 1-2)

- **EventRecorder**: Records orchestration events to JSONL
- **EvaluationOrchestratorWrapper**: Wraps orchestrator via composition
- **MetricsScorer**: Computes 6 categories of metrics + comparisons

### Scenario Running (Phase 3)

- **ScenarioRunner**: Executes YAML scenarios
- **ComparisonRunner**: Runs A/B tests
- **MockMemoManager**: Minimal test mocks
- **Mock Orchestrator**: Scenario runner uses a built-in mock that simulates tool calls listed in `expectations.tools_called`; no production orchestrator required
- **Unified CLI**: Single entry point with subcommands

## Scenario Types

### 1. Template-Based Scenarios (scenario_template)

Reference a pre-defined scenario from scenariostore:

```yaml
scenario_name: my_banking_test
scenario_template: banking  # References scenariostore/banking/orchestration.yaml
turns:
  - turn_id: turn_1
    user_input: "Check my balance"
    expectations:
      tools_called: [get_account_balance]
```

### 2. Session-Based Scenarios (session_config)

Define agent list, handoffs, and routing directly in the YAML - like the backend's
orchestrator.yml but for evaluations. This is useful when you want to:

- Test with all discovered agents or a custom subset
- Define ad-hoc handoff routing without modifying scenariostore
- Run evaluations with different agent combinations

```yaml
scenario_name: multi_agent_test
session_config:
  # Agent selection: "all" or list of names
  agents:
    - BankingConcierge
    - CardRecommendation
    - InvestmentAdvisor

  # Or use patterns to filter agents
  # agent_patterns: ["^Banking.*", "^Card.*"]

  # Exclude specific agents
  # exclude_agents: [TestAgent]

  # Starting agent
  start_agent: BankingConcierge

  # Explicit handoff routing
  handoffs:
    - from: BankingConcierge
      to: CardRecommendation
      tool: handoff_card_recommendation
      type: discrete
      handoff_condition: |
        Transfer when customer asks about credit cards.

  # Enable dynamic routing via handoff_to_agent
  generic_handoff:
    enabled: true
    allowed_targets: []  # Empty = all agents

turns:
  - turn_id: turn_1
    user_input: "Tell me about credit cards"
    expectations:
      tools_called: [handoff_to_agent]
      handoff:
        to_agent: CardRecommendation
```

### 3. A/B Comparison Scenarios

Compare models or configurations across variants:

```yaml
comparison_name: gpt4o_vs_o3_mini
scenario_template: banking
variants:
  - variant_id: gpt4o
    agent_overrides:
      - agent: BankingConcierge
        model_override: {deployment_id: gpt-4o}
  - variant_id: o3_mini
    agent_overrides:
      - agent: BankingConcierge
        model_override: {deployment_id: o3-mini}
turns:
  - turn_id: turn_1
    user_input: "Check my balance"
```

See `scenarios/session_based/` for complete examples.

## Documentation

For complete documentation including:
- Architecture overview
- API reference
- Usage examples
- Metrics definitions
- Troubleshooting

See: **[docs/testing/model-evaluation.md](../../../../docs/testing/model-evaluation.md)**

## Import Guards

This package should **NEVER** be imported in production code:

❌ Production paths (forbidden):

- `apps/artagent/backend/voice/`
- `apps/artagent/backend/api/`
- `apps/artagent/backend/registries/`

✅ Allowed paths:

- Test files
- Evaluation scripts
- CI jobs

Runtime checks prevent production imports when `ENV=production`.
