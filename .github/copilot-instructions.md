# GitHub Copilot Instructions for Real-Time Azure Voice Agentic App

## General Development Philosophy
- Prioritize readability and simplicity over cleverness.
- Follow the principle of "less is more"—avoid unnecessary abstraction.
- Write modular code with clear separation between infrastructure, backend logic, and frontend UX.

---

## FastAPI + Uvicorn Backend (Python 3.11)

### Patterns to Encourage
- Use `async def` endpoints and WebSocket handlers.
- Use `pydantic.BaseModel` for all request and response schemas.
- Use dependency injection (`Depends`) for session, auth, or Redis clients.
- Use environment variables or `.env` for all secrets and config.
- Log structured JSON with correlation ID, callConnectionId, etc.

### Patterns to Avoid
- No blocking I/O (e.g., `requests` or `open()`).
- Avoid long chains of decorators or dynamic magic.
- No large global state—use scoped dependency containers (e.g., Redis, session store).

---

## Vite + React Frontend

### Patterns to Encourage
- Use hooks like `useEffect`, `useState`, and `useRef` to manage live transcript state.
- Use TailwindCSS for styling—keep styles inline or colocated with components.
- Use SWR or native `fetch` for calling backend APIs—keep it simple.
- Prefer pure functional components over class components.
- Stream transcript and audio via WebSocket. Maintain `connectionId` per session.

### Patterns to Avoid
- No Redux or global state management unless truly necessary.
- No jQuery or low-level DOM mutation.
- Avoid over-styling or deeply nested component trees.

---

## Azure Bicep IaC

### Patterns to Encourage
- Use parameterized modules for reusable infrastructure (e.g., `privateEndpoint.bicep`, `redis.bicep`).
- Store secrets in Key Vault and access via managed identity only.
- Define subnets with explicit delegation and minimal address ranges.
- Set `dependsOn` explicitly when deploying resources with known sequence dependencies.
- Use `azd` conventions for directory structure and naming (`infra/`, `src/`, etc.).

### Patterns to Avoid
- Avoid massive monolithic Bicep files.
- Avoid hardcoding values—use `param` with defaults or environment overrides.

---

## Deployment & azd

- Always use `azd up` to ensure full end-to-end provisioning (infra + code).
- Use `azd env` for managing environment-specific secrets.
- Enable diagnostics and log analytics on all services.
- Configure minimal CORS: allow origin of frontend, `allowCredentials: true`, `maxAge: 86400`.

---

## Real-Time Communication / Voice Agent Context

- For ACS + WebSocket, ensure low-latency STT/TTS loop is preserved.
- Use Redis for ephemeral state (session, transcript, interruptions).
- Segment logic for `eventgrid`, `speech`, `llm`, `tts`, and `logger` into micromodules.
- Use fallback defaults for TTS/STT in case of partial outage.
- Retry gracefully on STT or transcription errors.

---

## Prompt Examples to Try with Copilot
```
## Frontend

“Create a React hook that manages transcript state from a WebSocket stream”

## Backend

“Define an async FastAPI endpoint that uses Azure Identity to get a secret from Key Vault”

## Bicep

“Write a Bicep module to create a private endpoint for Azure OpenAI and link it to the private DNS zone”

## Infra as Code

“Create a subnet with Microsoft.Web/serverFarms delegation and minimal CIDR”
```

---

## Copilot Usage Tips

- Use natural language comments above functions to guide Copilot suggestions.
- Name functions and variables with intent (`handleTranscriptChunk`, `saveToBlob`, `generateTTS`).
- Break large files into folders like `/handlers`, `/models`, `/infra/modules`.

---

## Folder Conventions (suggested)
```
/
├── infra/
│   ├── main.bicep
│   ├── modules/
│   │   ├── apim.bicep
│   │   ├── containerapp.bicep
│   │   ├── private-endpoint.bicep
│   │   └── redis.bicep
│
├── src/
│   ├── acs/
│   ├── redis/
│   ├── aoai/
│   ├── blob/
│   ├── cosmosdb/
│   ├── eventgrid/
│   └── speech/
│
├── rtagents/
│   ├── healthclaim/
│   │   ├── frontend/       # Vite + React
│   │   │   ├── .env        # Frontend environment variables
│   │   │   └── App.jsx
│   │   └── backend/        # FastAPI + Uvicorn
│   │       ├── main.py
│   │       ├── routers/
│   │       └── utils/
│   ├── benefitslookup/
│   │   ├── frontend/
│   │   └── backend/
│   └── billinginquiry/
│       ├── frontend/
│       └── backend/
│
├── .env                     # Backend environment variables
└── azure.yaml
```