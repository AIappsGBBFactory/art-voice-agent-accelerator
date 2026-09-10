# 🚀 GitHub Actions Deployment Automation

This directory contains GitHub Actions workflows for automated deployment of your Real-Time Audio Agent application to Azure using Azure Developer CLI (AZD).

## 🎯 Workflows

| Workflow | File | Description |
|----------|------|-------------|
| **Deploy to Azure** | [`deploy-azd-complete.yml`](./deploy-azd-complete.yml) | Main deployment workflow - use this one |
| **Deploy Documentation** | [`docs.yml`](./docs.yml) | Deploys static HTML docs to GitHub Pages |
| **Test AZD Hooks** | [`test-azd-hooks.yml`](./test-azd-hooks.yml) | Tests preprovision/postprovision hooks across platforms |
| **Live Evals (Staging)** | [`live-evals-staging.yml`](./live-evals-staging.yml) | Strict scenario and voice E2E gates after staging application deployment |
| **_template-deploy-azd** | [`_template-deploy-azd.yml`](./_template-deploy-azd.yml) | ⚠️ Internal template - do not run directly |

## Staging live evaluations

After a successful staging `up` or `deploy`, the finalizer dispatches live
evaluations with `--ref staging`. Dispatch uses the job's `GITHUB_TOKEN` with
`actions: write`, not `GH_PAT`, and an API rejection fails the dispatch step.
Provision-only runs, teardown and PR previews do not dispatch evaluations.

The deployed backend URL, Container App name and resource group are passed as
workflow inputs. They take precedence over saved environment variables, so an
expired variable-persistence PAT cannot leave the readiness gate or WebSocket
driver targeting stale backend coordinates. Readiness polls the mounted
`/api/v1/health` endpoint. A manual staging dispatch can supply the same inputs
or use the saved environment variables.

`GH_PAT` is still used separately to persist environment variables. A `401 Bad
credentials` error there requires an operator to replace that secret; the job
token does not acquire environment-variable administration permissions. Other
Azure endpoint/authentication variables must remain configured correctly.

If a failed live-eval run says `Branch "main" is not allowed to deploy to staging`
and has no executed steps, inspect the workflow on the **default branch**.
GitHub reads `workflow_run` triggers from that branch, not the triggering staging
commit. An older default-branch copy must also have its obsolete `workflow_run`
trigger removed; updating staging alone does not retire it. Do not loosen the
staging environment protection or rerun the rejected main-branch job. Use a
staging `workflow_dispatch` run instead.

Live evaluations access Azure services and the decline scenario can send email.
The offline workflow regressions run their actual shell steps with stubbed
`gh`, `az` and `curl` commands:

```bash
AZURE_APPCONFIG_ENDPOINT='' pytest tests/test_live_eval_workflow.py
```

Headless scenarios run the streaming Cascade path with the production
`MemoManager` in explicit local-only mode. The retired evaluation
`MockMemoManager`/history/core-memory copies are not an alternate state contract.
Inline scenario definitions use `ScenarioConfig.from_dict`, including handoff
conditions, generic identity requirements and agent defaults. The recorder
forwards TTS callback metadata unchanged; its first-chunk timing measures
text-to-TTS dispatch, not synthesized audio arriving at a client. The separate
WebSocket jobs measure actual audio arrival. Recorded pipeline errors fail
functional validation even if a scenario has no other content assertions.
Native token counters are cumulative for an agent session. The recorder uses
per-turn deltas and captures source usage before a handoff resets the counters,
so later replies do not inherit earlier token charges or false verbosity
failures. Native counters and returned results are unchanged. Cost estimates
still use the final agent's model configuration for each turn; they are not a
per-model billing ledger for mixed-model handoffs. The email scenario explicitly
asks for the exact destination address while retaining its recipient assertions.
The banking test fixture explicitly applies its request-only conditions to both
declared routing forms and asks for the recalled decline code without supplying
the answer. This clarifies that fixture's policy; it does not change production
generic-routing permissions or remove the no-handoff/context assertions.
Headless sessions now warm and reuse their actual async OpenAI client, rather
than warming an unrelated synchronous client and opening a new transport each
turn. Owned clients and session overrides are cleaned up on completion or
cancellation; caller-provided clients remain borrowed. History is read for the
current agent after a handoff, not permanently for the session's starting agent.

The WebSocket driver waits for the native browser readiness event and greeting
quiescence, then observes replies concurrently with paced input. Its EOS anchor
is the end of user PCM, before endpointing silence. `turn_wall_ms` ends at the
last response frame, excluding the observer's quiet wait; it still includes
audio delivery and is not the headless model-processing metric. Typed transcript
snapshots replace prior content, deltas append, and final-turn envelopes close
their stream. Control/user messages cannot complete an unanswered turn. Missing
responses, timeouts and mid-turn closes stop the scenario instead of sending a
new utterance over unresolved output. No latency budgets are increased.
The wire driver selects the deployed industry scenario; it does not install
inline `session_config` or model overrides. Those functional/configuration
expectations are exercised by the headless suite. Voice jobs are audio and
latency smoke tests of the deployed configuration, not proof of inline routing.
Completion still uses a bounded quiet-window heuristic: audio frames have no
response identity, and an unusually delayed greeting or silent gap between
responses can limit attribution. Inspect server traces for ambiguous runs.

The blocking unit gate also covers async OpenAI invocation, Azure-host identity
detection, and deferred VoiceLive memory sync. Four legacy ACS authentication
expectations remain in `.github/quarantined-tests.txt`: implementing a different
credential priority or SMS managed identity needs an explicit behavior decision,
not a test-only assertion change.
The backend job installs `redis-server` so the isolated authoring-persistence
regressions run rather than being skipped on runners without the executable.

The frontend gate also runs the Quick Tune Playwright suite with Firefox after
the unit tests and production build. These tests cover draft/Apply boundaries,
prompt context insertion, tool and voice catalogs, per-mode Foundry resources,
scenario graph editing, and responsive layouts against mocked APIs. Failure
screenshots and first-failure traces are uploaded as `authoring-browser-results`;
automatic retries remain disabled. Real HTTP/Redis
registration tests are opt-in and are not enabled in this browser CI job.

## 🚀 Quick Start

### Deploy Everything
1. Go to **Actions** → **Deploy to Azure**
2. Click **Run workflow**
3. Select environment (`dev`/`staging`/`prod`) and action (`up`)

### Available Actions
| Action | Description |
|--------|-------------|
| `up` | Provision infrastructure + deploy application (default) |
| `provision` | Infrastructure only (Terraform) |
| `deploy` | Application only (requires existing infrastructure) |
| `down` | Destroy all resources |

## 🏗️ Workflow Architecture

The template workflow is organized into clean, separate jobs:

```
┌──────────────────────────────────────────────────────────────┐
│                    Deploy to Azure                           │
│                 (deploy-azd-complete.yml)                    │
└──────────────────────┬───────────────────────────────────────┘
                       │ calls
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              _template-deploy-azd.yml                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────┐    ┌─────────────┐    ┌──────────┐             │
│  │  Setup  │───▶│   Execute   │───▶│ Finalize │             │
│  │   🔐    │    │ 🏗️📦🚀💥   │    │    📋    │             │
│  └─────────┘    └─────────────┘    └──────────┘             │
│       │                                                      │
│       │ (PRs only)                                          │
│       ▼                                                      │
│  ┌─────────┐                                                │
│  │ Preview │                                                │
│  │   📋    │                                                │
│  └─────────┘                                                │
└──────────────────────────────────────────────────────────────┘
```

### Jobs

| Job | Description |
|-----|-------------|
| **Setup** | Azure authentication (OIDC or Service Principal) |
| **Preview** | Runs `azd provision --preview` for PRs |
| **Execute** | Runs the selected azd command (`provision`/`deploy`/`up`/`down`) |
| **Finalize** | Updates GitHub environment variables, generates summary |

## 🔐 Authentication

### OIDC (Recommended)
Configure federated credentials in Azure AD:
```
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

### Service Principal (Fallback)
```
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

## ⚙️ Environment Variables

After deployment, these variables are automatically set on the GitHub environment:

| Variable | Description |
|----------|-------------|
| `AZURE_APPCONFIG_ENDPOINT` | Azure App Configuration endpoint |
| `AZURE_APPCONFIG_LABEL` | Configuration label for the environment |

These are used on subsequent deployments to maintain consistency.

## 🌍 Environments

| Environment | Trigger | Purpose |
|-------------|---------|---------|
| `dev` | Push to `main` | Development and testing |
| `staging` | Manual | Pre-production validation |
| `prod` | Manual | Production |

## 📋 Triggers

- **Push to `main`**: Auto-deploys to `dev`
- **Pull Request**: Preview infrastructure changes
- **Manual**: Run any action on any environment

## 🧪 Test AZD Hooks Workflow

The `test-azd-hooks.yml` workflow validates the AZD preprovision and postprovision hooks across multiple platforms.

### What It Tests

| Test | Description |
|------|-------------|
| **Lint** | ShellCheck analysis of all shell scripts |
| **Syntax Validation** | Bash syntax checking (`bash -n`) |
| **Logging Functions** | Verifies unified logging utilities work |
| **Location Resolution** | Tests tfvars-based location resolution |
| **Backend Configuration** | Tests Terraform backend.tf generation |
| **Regional Availability** | Validates Azure service availability checks |

### Platforms Tested

| Platform | Runner | Shell |
|----------|--------|-------|
| 🐧 Linux | `ubuntu-latest` | Bash |
| 🍎 macOS | `macos-latest` | Bash |
| 🪟 Windows | `windows-latest` | Git Bash |

### Triggers

- Push to `main` or `staging` (when hook scripts change)
- Pull requests (when hook scripts change)
- Manual dispatch with optional debug mode

### Running Locally

```bash
# Validate script syntax
bash -n devops/scripts/azd/preprovision.sh
bash -n devops/scripts/azd/postprovision.sh

# Run preflight checks
cd devops/scripts/azd/helpers
source preflight-checks.sh
run_preflight_checks

# Test with local state (no Azure required)
export LOCAL_STATE=true
export AZURE_ENV_NAME=local-test
export AZURE_LOCATION=eastus2
bash devops/scripts/azd/preprovision.sh terraform
```

## 🔗 Related Documentation

- [Azure Developer CLI Guide](../../docs/deployment/azd-guide.md)
- [Infrastructure Overview](../../docs/architecture/)
- [Troubleshooting](../../docs/operations/)

## 🛠️ Local Development

```bash
# Deploy everything
azd up --environment dev

# Infrastructure only
azd provision --environment dev

# Application only
azd deploy --environment dev

# Destroy resources
azd down --environment dev
```

### Prerequisites
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Terraform](https://terraform.io/downloads)
- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
- Docker for container builds
