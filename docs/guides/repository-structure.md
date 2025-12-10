# Repository Structure

This document provides a map of the ART Voice Agent Accelerator repository, designed for engineers who need to understand the codebase architecture, locate specific components, and contribute effectively.

## Overview

The repository follows a modular, microservice-oriented structure with clear separation of concerns:

| Directory | Purpose |
|-----------|---------|
| `apps/` | Deployable applications (backend API, frontend UI) |
| `src/` | Core business logic libraries (reusable across apps) |
| `infra/` | Infrastructure-as-Code (Bicep, Terraform) |
| `docs/` | Documentation and guides |
| `tests/` | Test suites and load testing |
| `utils/` | Cross-cutting utilities (logging, telemetry) |
| `samples/` | Example implementations and labs |
| `devops/` | CI/CD scripts and security tooling |

---

## Root Files

```
📁 art-voice-agent-accelerator/
├── 📄 .python-version           # Python version pin for uv (3.11)
├── 📄 pyproject.toml            # Python dependencies and tool config (single source of truth)
├── 📄 uv.lock                   # Lockfile for reproducible builds (managed by uv)
├── 📄 azure.yaml                # Azure Developer CLI (azd) configuration
├── 📄 docker-compose.yml        # Local development containers
├── 📄 environment.yaml          # Conda environment (alternative to uv)
├── 📄 Makefile                  # Automation commands
├── 📄 mkdocs.yml                # Documentation site configuration
├── 📄 CHANGELOG.md              # Release notes and version history
├── 📄 CONTRIBUTING.md           # Contribution guidelines
├── 📄 LICENSE                   # MIT license
└── 📄 README.md                 # Main project documentation
```

---

## Core Application Structure

### Backend (`apps/artagent/backend/`)

FastAPI-based real-time voice agent service with WebSocket support.

```
📁 apps/artagent/backend/
├── 📄 Dockerfile                # Container definition (uv-based)
├── 📄 main.py                   # FastAPI application entry point
├── 📄 README.md                 # Backend documentation
│
├── 📁 agents/                   # AI Agent definitions
│   ├── 📄 base.py               # Base agent class
│   ├── 📄 loader.py             # Agent configuration loader
│   ├── 📄 session_manager.py    # Agent session management
│   ├── 📄 _defaults.yaml        # Default agent configuration
│   ├── 📁 auth_agent/           # Authentication agent
│   ├── 📁 card_recommendation/  # Card recommendation agent
│   ├── 📁 compliance_desk/      # Compliance desk agent
│   ├── 📁 concierge/            # Concierge agent
│   ├── 📁 custom_agent/         # Custom agent template
│   ├── 📁 fraud_agent/          # Fraud detection agent
│   ├── 📁 investment_advisor/   # Investment advisor agent
│   ├── 📁 scenarios/            # Agent scenario configurations
│   └── 📁 tools/                # Agent-specific tools
│
├── 📁 api/                      # REST API endpoints
│   ├── 📄 swagger_docs.py       # OpenAPI documentation
│   └── 📁 v1/                   # API version 1 endpoints
│
├── 📁 config/                   # Configuration management
│   ├── 📄 ai_config.py          # AI service configuration
│   ├── 📄 app_config.py         # Application configuration
│   ├── 📄 app_settings.py       # Settings management
│   ├── 📄 appconfig_provider.py # Azure App Configuration provider
│   ├── 📄 connection_config.py  # Connection string management
│   ├── 📄 constants.py          # Application constants
│   ├── 📄 feature_flags.py      # Feature flag management
│   ├── 📄 infrastructure.py     # Infrastructure configuration
│   ├── 📄 security_config.py    # Security settings
│   ├── 📄 settings.py           # Main settings
│   └── 📄 voice_config.py       # Voice/speech configuration
│
├── 📁 src/                      # Backend source code
│   ├── 📄 helpers.py            # Helper utilities
│   ├── 📁 orchestration/        # Call orchestration logic
│   ├── 📁 services/             # Business logic services
│   ├── 📁 sessions/             # Session management
│   ├── 📁 utils/                # Backend utilities
│   └── 📁 ws_helpers/           # WebSocket helper utilities
│
└── 📁 voice/                    # Voice processing modules
    ├── 📁 handoffs/             # Call handoff logic
    ├── 📁 messaging/            # Messaging integrations (SMS, email)
    ├── 📁 shared/               # Shared voice utilities
    ├── 📁 speech_cascade/       # Speech cascade processing
    └── 📁 voicelive/            # Azure Voice Live SDK integration
```

### Frontend (`apps/artagent/frontend/`)

React + TypeScript SPA with Vite for the voice agent UI.

```
📁 apps/artagent/frontend/
├── 📄 Dockerfile                # Frontend container definition
├── 📄 index.html                # Main HTML template
├── 📄 package.json              # Node.js dependencies
├── 📄 package-lock.json         # Lockfile
├── 📄 vite.config.js            # Vite build configuration
├── 📄 eslint.config.js          # ESLint configuration
├── 📄 serve.json                # Static server configuration
├── 📄 .env.sample               # Environment variables template
│
├── 📁 public/                   # Static assets
└── 📁 src/                      # React source code
```

---

## Core Libraries (`src/`)

Reusable business logic shared across applications.

```
📁 src/
├── 📁 acs/                      # Azure Communication Services
├── 📁 agenticmemory/            # Agent memory management
├── 📁 aoai/                     # Azure OpenAI integration
├── 📁 blob/                     # Azure Blob Storage
├── 📁 cosmosdb/                 # Cosmos DB integration
├── 📁 enums/                    # Enumeration definitions
├── 📁 pools/                    # Connection and resource pools
├── 📁 postcall/                 # Post-call processing and analytics
├── 📁 prompts/                  # AI prompt templates
├── 📁 redis/                    # Redis integration
├── 📁 speech/                   # Speech processing (STT/TTS)
├── 📁 stateful/                 # Stateful session processing
├── 📁 tools/                    # Function calling tools
└── 📁 vad/                      # Voice Activity Detection
```

---

## Infrastructure (`infra/`)

Infrastructure-as-Code for Azure deployments.

```
📁 infra/
├── 📄 README.md                 # Infrastructure documentation
├── 📁 bicep/                    # Azure Bicep templates
│   ├── 📄 main.bicep            # Main infrastructure template
│   └── 📁 modules/              # Reusable Bicep modules
└── 📁 terraform/                # Terraform configurations
    ├── 📄 main.tf               # Main Terraform configuration
    ├── 📄 variables.tf          # Variable definitions
    ├── 📁 modules/              # Terraform modules
    └── 📁 environments/         # Environment-specific configs
```

---

## Documentation (`docs/`)

MkDocs-based documentation site.

```
📁 docs/
├── 📄 index.md                  # Documentation home
├── 📄 mkdocs.yml                # MkDocs configuration
├── 📁 agents/                   # Agent documentation
├── 📁 api/                      # API reference documentation
├── 📁 architecture/             # Architecture documentation
├── 📁 assets/                   # Documentation assets (images, CSS)
├── 📁 deployment/               # Deployment guides
├── 📁 getting-started/          # Getting started guides
├── 📁 guides/                   # Developer guides
├── 📁 industry/                 # Industry-specific use cases
├── 📁 operations/               # Operations and troubleshooting
├── 📁 samples/                  # Sample documentation
└── 📁 security/                 # Security documentation
```

---

## Tests (`tests/`)

Comprehensive test suites.

```
📁 tests/
├── 📄 conftest.py               # Pytest configuration
├── 📄 test_acs_*.py             # ACS integration tests
├── 📄 test_speech_*.py          # Speech processing tests
├── 📄 test_dtmf_*.py            # DTMF validation tests
├── 📄 test_*.py                 # Various unit/integration tests
├── 📄 apim-test.http            # API Management tests
├── 📄 backend.http              # Backend API tests
└── 📁 load/                     # Load testing
    ├── 📄 README.md             # Load testing documentation
    └── 📄 locustfile.py         # Locust load test script
```

---

## Samples (`samples/`)

Example implementations and tutorials.

```
📁 samples/
├── 📄 README.md                 # Samples overview
├── 📁 hello_world/              # Getting started examples
│   ├── 📄 01-create-your-first-rt-agent.ipynb
│   ├── 📄 02-run-test-rt-agent.ipynb
│   ├── 📄 03-create-your-first-foundry-agents.ipynb
│   ├── 📄 04-exploring-live-api.ipynb
│   └── 📄 05-create-your-first-livevoice.ipynb
├── 📁 labs/                     # Advanced labs
├── 📁 usecases/                 # Industry use cases
└── 📁 voice_live_sdk/           # Voice Live SDK examples
```

---

## DevOps (`devops/`)

CI/CD scripts and security tooling.

```
📁 devops/
├── 📄 azure-bicep.yaml          # Azure Bicep pipeline
├── 📄 .terraform-docs.yaml      # Terraform documentation config
├── 📁 scripts/                  # Deployment scripts
│   ├── 📁 azd/                  # Azure Developer CLI scripts
│   └── 📁 misc/                 # Miscellaneous scripts
└── 📁 security/                 # Security scanning
    ├── 📄 bandit_to_sarif.py    # Bandit to SARIF converter
    ├── 📄 run_bandit.py         # Bandit runner
    └── 📁 reports/              # Security reports
```

---

## Development Environment

### Dev Container (`.devcontainer/`)

VS Code dev container configuration for consistent development environments.

```
📁 .devcontainer/
├── 📄 devcontainer.json         # Dev container configuration
└── 📄 post_create.sh            # Post-creation setup script (installs uv, bicep)
```

### VS Code Settings (`.vscode/`)

VS Code workspace settings and launch configurations.

---

## Utilities (`utils/`)

Cross-cutting utilities for logging, telemetry, and authentication.

```
📁 utils/
├── 📄 azure_auth.py             # Azure authentication utilities
├── 📄 ml_logging.py             # Machine learning logging
├── 📄 pii_filter.py             # PII filtering
├── 📄 session_context.py        # Session context management
├── 📄 telemetry_config.py       # Telemetry configuration
├── 📄 telemetry_decorators.py   # Telemetry decorators
├── 📄 trace_context.py          # Distributed tracing context
├── 📁 data/                     # Data utilities
└── 📁 docstringtool/            # Documentation generation tools
```

---

## Quick Navigation for Engineers

### 🔍 Finding Components

| What you need | Where to look |
|---------------|---------------|
| API endpoints | `apps/artagent/backend/api/v1/` |
| Agent definitions | `apps/artagent/backend/agents/` |
| Configuration | `apps/artagent/backend/config/` |
| WebSocket handlers | `apps/artagent/backend/src/ws_helpers/` |
| Voice processing | `apps/artagent/backend/voice/` |
| Speech processing | `src/speech/` |
| ACS integration | `src/acs/` |
| AI/LLM logic | `src/aoai/` |
| Database models | `src/cosmosdb/` |
| Infrastructure | `infra/bicep/` or `infra/terraform/` |
| Documentation | `docs/` |
| Tests | `tests/` |

### 🚀 Getting Started Paths

1. **Backend Developer**: Start with `apps/artagent/backend/main.py`
2. **Frontend Developer**: Start with `apps/artagent/frontend/src/`
3. **AI/Agent Engineer**: Start with `apps/artagent/backend/agents/`
4. **DevOps Engineer**: Start with `infra/` and `azure.yaml`
5. **Integration Developer**: Start with `src/acs/` and `src/speech/`

### 📦 Package Management

This project uses **uv** for Python package management:

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --extra dev

# Install with docs dependencies
uv sync --extra docs --extra dev

# Run commands through uv
uv run pytest
uv run python -m uvicorn apps.artagent.backend.main:app --reload
```

### 📚 Documentation Priority

1. **Quick Start**: `docs/getting-started/local-development.md`
2. **Architecture**: `docs/architecture/`
3. **Deployment**: `docs/deployment/`
4. **API Reference**: `docs/api/`
5. **Troubleshooting**: `docs/operations/troubleshooting.md`
