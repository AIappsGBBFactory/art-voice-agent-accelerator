<!-- markdownlint-disable MD033 MD041 -->

# **ARTVoice Accelerator Framework**

**TL;DR**: Ship real-time voice agents on Azure— single hyperscale platform, omnichannel (ACS telephony included), code‑first, and modular by default.

<img src="utils/images/ARTAGENT.png" align="right" height="220" alt="ARTAgent Logo" />

You own the agentic design; this repo handles the end-to-end voice plumbing. We keep a clean separation of concerns—telephony (ACS), app middleware, AI inference loop (STT → LLM → TTS), and orchestration—so you can swap parts without starting from zero. We know, shipping voice agents is more than “voice-to-voice.” You need predictable latency budgets, media handoffs, error paths, channel fan-out, barge-in, noise cancellation, and more. This framework gives you the e2e working spine so you can focus on what differentiates you— your tools, agentic design, and orchestration logic (multi-agent ready).

<details closed>
<summary><h4>The what and why of this accelerator</h4></summary>

## **What you get**

- **Omnichannel, including first-class telephony**. Azure Communication Services (ACS) integration for PSTN, SIP transfer, IVR/DTMF routing, and number provisioning—extendable for contact centers and custom IVR trees.

- **Transport that scales**. FastAPI + WebSockets for true bidirectional streaming; runs locally and scales out in Kubernetes. We include simple classes to wire your UI WebSocket client or loop back into ACS—the plumbing is done.

- **Model freedom**. Use GPT-family or your provider of choice behind a slim adapter; swap models without touching the transport.

- **Clear seams for customization**. Replace code, switch STT/TTS providers, add tool routers, or inject domain policies—without tearing down the whole app.

### **Choose your voice inference pipeline (voice‑to‑voice):**

- **Build from scratch (maximum control).** Use our AI inference layer and patterns to wire STT → LLM → TTS with your preferred Azure services and assessments. Own the event loop, intercept any step, and tailor latency/quality trade-offs for your use case. Ideal for on‑prem/hybrid, strict compliance, or deep customization.

- **Managed path (ship fast, enterprise‑ready).** Leverage the latest addition to the Azure AI family—Azure Voice Live API (preview)—for voice-to-voice media, and connect to Azure AI Foundry Agents for built-in tool/function calling. Keep your hooks; let Azure AI Foundry handle the media layer, scaling, noise suppression, and barge-in.

- **Bring your own voice‑to‑voice model.** Drop in your model behind(e.g., latest gpt‑realtime or equivalent). Transport/orchestration (including ACS telephony) stays the same—no app changes.

*The question of the century: Is it production-ready?*

“Production” means different things, but our intent is clear: this is an accelerator—it gets you ~80% of the way with battle-tested plumbing. You bring the last mile: hardening, infrastructure policies, security posture, SRE/DevOps, and your enterprise release process.

We ship the scaffolding to make that last mile fast: structured logging, metrics/tracing hooks, and a load-testing harness so you can profile end-to-end latency and concurrency, then tune or harden as needed to reach your target volume.

</details>

## **Demo, Demo, Demo..**



## **The How (Architecture)**

Pick one of three ways to run the voice inference layer—the rest of the framework (transport, orchestration, ACS telephony, UI wiring) stays the same. Choose based on control vs. speed vs. portability.

<details>
<summary><strong>Build the AI voice pipeline from scratch (maximum control)</strong></summary>
<br>
<img src="utils/images/ARTAgentarch.png" alt="ARTAgent Arch" />

- **Own the event loop**: STT → LLM/Tools → TTS, with granular hooks.
- **Swap services per stage**: Azure Speech, Azure OpenAI, etc.
- **Tune for your SLOs**: latency budgets, custom VAD, barge-in, domain policies.
- **Deep integration**: ACS telephony, Event Hubs, Cosmos DB, FastAPI/WebSockets, Kubernetes, observability, custom memory/tool stores.
- **Best for**: on-prem/hybrid, strict compliance, or heavy customization.

</details>

<details>
<summary><strong>Use Azure Voice Live API + Azure AI Foundry Agents (ship fast)</strong></summary>
<br>

> [!NOTE]
> WIP/Preview: Azure Voice Live API is in preview; behavior and APIs may change.

<br>

<img src="utils/images/LIVEVOICEApi.png" alt="LIVEVOICEApi" />

 - **Enterprise Managed voice-to-voice**: barge-in, noise suppression, elastic scale.
 - **Agent runtime**: connect to Azure AI Foundry Agents for built-in tool/function calling and orchestration.
 - **Built-ins**: tool store, guardrails/evals, threads/memory patterns, APIM gateway options.
 - **Keep your hooks**: reduce ops surface and move faster to pilot/production.

 **Key differences vs. from-scratch**

 - Media layer and agent runtime are managed (less infra to own).
 - Faster “happy-path” to omnichannel via ACS, while still supporting your policies and extensions.
 - Great fit when you want speed, scale and consistency without giving up critical integration points.

</details>

<details>
<summary><strong>Bring your own voice-to-voice model (e.g., gpt-realtime) — coming soon</strong></summary>

> [!NOTE]
> Coming soon: This adapter path is under active development.

- Plug a BYO voice-to-voice model behind a slim adapter; no changes to transport/orchestration.
- ACS telephony path remains intact.


</details>

## **Getting started**

> [!TIP]
> Pick the path that fits your goal. Local is fastest for iteration; azd is fastest for a full Azure footprint.

- Deploy to Azure in one command: see the section below “Deploy and Customize the Demo App… (azd)”
- Deploy with Terraform + Makefile: see `docs/DeploymentGuide.md`
- Run locally (recommended for dev): see Quickstart — Local Development → `docs/quickstart-local-development.md`

### **Understand the Repository map (high‑level)**

- `apps/rtagent/`
	- `backend/` — FastAPI + WebSockets voice pipeline
	- `frontend/` — Vite + React demo client
	- `scripts/` — Helper launchers (backend, frontend, tunnel)
- `src/` — Core libraries (ACS, Speech, AOAI, Redis, Cosmos, VAD, tools, prompts, etc.)
- `infra/`
	- `bicep/` — Azure Bicep modules
	- `terraform/` — Terraform modules
- `docs/` — Guides and references (architecture, getting started, troubleshooting)
- `tests/` — Pytest suite
- `utils/` — Logging/telemetry helpers and images

> [!NOTE]
> Need a deeper map (up to 5 levels) and exact local run steps? See `docs/repo-structure.md`.

### **Deploy and Customize the Demo App Using the ARTAgent Framework**

> [!IMPORTANT]
> Prerequisites for azd deployment:
> - Azure Developer CLI installed and logged in (`azd auth login`)
> - Active subscription selected in Azure CLI (`az account show`)
> - Repo contains `azure.yaml` (root) and infra under `infra/` (this repo does)
> - Sufficient permissions to create resource groups and resources
>
> Already have infra? You can skip azd and run locally using the Quickstart — see `docs/quickstart-local-development.md`.

Provision the complete Azure stack—including **App Gateway**, **Container Apps**, **Cosmos DB**, **Redis Cache**, **Azure OpenAI**, **Speech Services**, **Key Vault**, **Application Insights**, **Log Analytics**, **Azure Communication Services**, **Event Grid**, and **Storage Account**—with a single command:

```bash
azd auth login
azd up   # ~15 min for complete infra and code deployment
```

For a detailed deployment walkthrough, see [`docs/DeploymentGuide.md`](docs/DeploymentGuide.md).

## **Contributing**
PRs & issues welcome—see `CONTRIBUTING.md` before pushing.

## **License & Disclaimer**
Released under MIT. This sample is **not** an official Microsoft product—validate compliance (HIPAA, PCI, GDPR, etc.) before production use.

<br>

> [!IMPORTANT]  
> This software is provided for demonstration purposes only. It is not intended to be relied upon for any production workload. The creators of this software make no representations or warranties of any kind, express or implied, about the completeness, accuracy, reliability, suitability, or availability of the software or related content. Any reliance placed on such information is strictly at your own risk.