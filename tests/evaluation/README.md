# Evaluation Package

Simplified evaluation framework for voice agent orchestration.

## Quick Start

### Makefile Targets (Recommended)

```bash
# Interactive CLI - browse and run scenarios
make eval

# Run a single scenario with streaming output
make eval-run SCENARIO=tests/evaluation/scenarios/session_based/banking_multi_agent.yaml

# Run all scenarios by category
make eval-smoke       # Quick validation tests
make eval-session     # Multi-turn, multi-agent flows
make eval-ab          # A/B model comparisons
```

### Python CLI (Direct)

```bash
# Interactive menu
python tests/evaluation/eval_cli.py

# Run a scenario (auto-detects single vs A/B comparison)
python tests/evaluation/run-eval-stream.py run \
    --input tests/evaluation/scenarios/session_based/banking_multi_agent.yaml

# Module-based CLI (lower-level)
python -m tests.evaluation.cli run \
    --input tests/evaluation/scenarios/session_based/banking_multi_agent.yaml

# Submit to Azure AI Foundry
python -m tests.evaluation.cli submit \
    --data runs/my_run/foundry_eval.jsonl \
    --endpoint "$AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"
```

### Pytest

```bash
# Run all evaluation tests
pytest tests/evaluation/test_scenarios.py -v

# Run specific scenario
pytest tests/evaluation/test_scenarios.py -k "banking" -v
```

## Real Voice WebSocket E2E and Performance Runs

The scenario runner above exercises the orchestrator in-process. It is useful
for deterministic tool, handoff, response, and server-side latency assertions,
but it does not measure the browser audio transport. The live driver exercises
the active `/api/v1/browser/conversation` WebSocket with production-format PCM
frames and records client-observed:

- EOS-to-first response frame
- EOS-to-first audio frame
- EOS-to-completed-turn wall time
- WebSocket connect time
- W3C trace correlation and the generated `eval_live_...` session ID

Server-only KPIs such as TTFT and TTS first-byte remain authoritative in the
`voice.turn.N.total` spans. The live driver reports these expectations as
unmeasured rather than incorrectly treating client first-audio time as TTFT.

### Local reproduction

Start the backend on port 8010 with the normal local environment, then generate
input audio once and run both browser orchestration modes:

```bash
make start_backend
make eval-live-synth
make eval-live EVAL_LIVE_URL=http://localhost:8010
```

`eval-live-synth` requires Azure Speech credentials or the configured App
Configuration bootstrap. The measured `eval-live` command uses only the cached
PCM files, so it does not include Speech synthesis time. Results are written to
`runs/live-evals/`, including one JSON file per mode and a `matrix_summary.json`
comparison. The cache and run output are intentionally ignored by Git.

Useful overrides:

```bash
make eval-live \
  EVAL_LIVE_SCENARIO=tests/evaluation/scenarios/session_based/banking_context_sharing.yaml \
  EVAL_LIVE_MODES=realtime,voice_live \
  EVAL_LIVE_REPEAT=3 \
  EVAL_LIVE_URL=http://localhost:8010
```

For a deployed endpoint, set `EVAL_LIVE_URL` to its `https://` base URL; the
driver converts it to `wss://`. Use `--require-audio-cache` (already enabled by
the Make target) to prevent an accidental measured run from synthesizing audio
on demand.

The CI workflow runs the same driver for both `realtime` (Speech Cascade) and
`voice_live`, uploads the raw JSON artifacts, and verifies the corresponding
`eval_live_` sessions in Application Insights. A live driver pass does not
replace functional assertions: the in-process scenario job remains responsible
for tools, handoffs, response constraints, and seeded demo-user behavior.

To verify a local run's server-side telemetry, copy the `session_id` from its
JSON result and run this query in the connected Application Insights resource:

```kusto
let live_session = "eval_live_realtime_latency_first_audio_<suffix>";
union isfuzzy=true dependencies, requests, traces
| where timestamp > ago(1h)
| extend p = parse_json(tostring(customDimensions))
| where tostring(p["session.id"]) == live_session
| where name startswith "voice.turn."
| project timestamp, name,
  turn_wall_ms=todouble(p["turn.wall_ms"]),
  ttft_ms=todouble(p["turn.ttft_ms"]),
  ttfb_ms=todouble(p["turn.ttfb_ms"]),
  model=tostring(p["turn.model"]),
  transport=tostring(p["turn.transport_type"])
| order by timestamp asc
```

The local JSON is the client-side truth for first response/audio and turn wall
time; this query is the server-side truth for TTFT, TTFB, model, and transport.
Keep both when diagnosing a regression instead of comparing client first audio
directly with the server-only TTS first-chunk budget.

## Package Structure

```text
tests/evaluation/
├── __init__.py              # Package exports
├── schemas/                 # Pydantic models
│   ├── config.py            # SessionAgentConfig
│   ├── events.py            # TurnEvent, ToolCall, HandoffEvent
│   ├── expectations.py      # ScenarioExpectations
│   ├── results.py           # TurnScore, RunSummary
│   └── foundry.py           # Azure AI Foundry types
├── recorder.py              # EventRecorder - captures events to JSONL
├── wrappers.py              # EvaluationOrchestratorWrapper
├── scorer.py                # MetricsScorer - computes metrics
├── validator.py             # ExpectationValidator
├── scenario_runner.py       # ScenarioRunner + ComparisonRunner
├── foundry_exporter.py      # Azure AI Foundry integration
├── conftest.py              # Pytest fixtures
├── test_scenarios.py        # Pytest test runner
├── cli/
│   └── __main__.py          # CLI (run, submit)
├── scenarios/
│   ├── scenario.schema.json # JSON Schema for YAML validation
│   ├── session_based/       # Multi-agent session scenarios
│   └── ab_tests/            # A/B comparison scenarios
└── README.md                # This file
```

## Test Scenarios

### Session-Based Scenarios

```yaml
# scenarios/session_based/banking_multi_agent.yaml
scenario_name: banking_multi_agent
session_config:
  agents: [BankingConcierge, CardRecommendation]
  start_agent: BankingConcierge
turns:
  - turn_id: turn_1
    user_input: "I'd like to check my account"
    expectations:
      tools_called: [verify_client_identity]
```

### A/B Comparison Scenarios

```yaml
# scenarios/ab_tests/fraud_detection_comparison.yaml
comparison_name: fraud_model_comparison
variants:
  - variant_id: gpt4o
    model_override: {deployment_id: gpt-4o}
  - variant_id: gpt4o_mini
    model_override: {deployment_id: gpt-4o-mini}
turns:
  - turn_id: turn_1
    user_input: "I see charges I didn't make"
```

## Key Components

| Component | Purpose |
|-----------|---------|
| `EventRecorder` | Records orchestration events to JSONL |
| `MetricsScorer` | Computes tool precision/recall, latency |
| `ExpectationValidator` | Validates events against YAML expectations |
| `ScenarioRunner` | Executes session-based scenarios |
| `ComparisonRunner` | Runs A/B comparison tests |
| `FoundryExporter` | Exports to Azure AI Foundry format |

## Import Guards

This package should **NEVER** be imported in production code.
Runtime checks prevent imports when `ENV=production`.
