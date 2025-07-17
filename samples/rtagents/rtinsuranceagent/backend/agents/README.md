# RTInsuranceAgent – Agent Architecture & Orchestration

## 🧭 Agent Initialization Flow

<br>

**Agent Configuration Loading**

<br>

```mermaid
flowchart TD
    A1[Load YAML Config]
    A2[Validate YAML]
    A3[Set Agent Metadata]
    A4[Load Model Params]
    A5[Get Prompt Path]
    A6[PromptManager Loads Template]
    A7[Build Tools List]
    A8[Attach Tools to Agent]
    A9[Agent Ready]
    A10[Create Conversation Manager]

    A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A9
    A4 --> A7 --> A8 --> A9
    A9 --> A10

    classDef main fill:#f5f7fa,stroke:#6366f1,stroke-width:2px,color:#222,font-size:16px;
    class A1,A2,A3,A4,A5,A6,A7,A8,A9,A10 main;
```

<br>

## 🚀 How to Create a Single Agent

To add a new domain agent in RTInsuranceAgent, follow these steps:

### 1. Define Agent Configuration
Create a YAML config file (e.g., `agent.yaml`) specifying:
- **Agent metadata** (name, org, description)
- **Model parameters** (deployment, temperature, etc.)
- **Prompt template path**
- **List of tools** this agent can access

### 2. Initialize the Agent
- Backend code loads and validates the YAML
- Sets up agent properties, model params, and links prompt/tool managers

### 3. Attach Tools and Prompts
- Ensure each agent is connected to only the tools and prompts defined in its config

### 4. Start a User Session
- When a session begins, instantiate the agent and create a `MemoManager` for tracking history and context

### 5. Handle User Prompts
- On receiving a prompt, append it to history, process with the agent (which attaches the correct model, prompt, and tools), then persist the state for continuity

#### Example `agent.yaml`
```yaml
name: MedicationAgent
organization: RTMed
description: Handles medication-related queries
model:
  deployment_id: gpt-4
  temperature: 0.2
prompts:
  path: prompts/medication_prompt.txt
tools:
  - medication_lookup
  - drug_interaction_checker
```

## 🕹️ Agent Orchestration & Routing Flow

**Agent Routing**

<br>

```mermaid
flowchart TD
    S1[User Question]
    S2{Authenticated?}
    S3[Authentication Agent]
    S4[Intent Classifier]
    S5[Medication Agent]
    S6[Billing Agent]
    S7[Demographics Agent]
    S8[Referrals Agent]
    S9[General Healthcare Agent]
    S10[Non-Healthcare Agent]
    S11[Fallback Agent]

    S1 --> S2
    S2 -- No --> S3 --> S2
    S2 -- Yes --> S4
    S4 -- Medication --> S5
    S4 -- Billing --> S6
    S4 -- Demographics --> S7
    S4 -- Referrals --> S8
    S4 -- General Healthcare --> S9
    S4 -- Non-Healthcare --> S10
    S4 -- Unknown/Other --> S11

    classDef main fill:#f5f7fa,stroke:#6366f1,stroke-width:2px,color:#222,font-size:16px;
    class S1,S2,S3,S4,S5,S6,S7,S8,S9,S10,S11 main;
```
<br>

**Tool/Knowledge Enforcement and Response**

<br>

```mermaid
flowchart TD
    T1[Domain Agent]
    T2[Use Tool/Knowledge Only]
    T3[Respond to User]
    T4[Escalate or End]

    T1 --> T2 --> T3 --> T4

    classDef main fill:#f5f7fa,stroke:#6366f1,stroke-width:2px,color:#222,font-size:16px;
    class T1,T2,T3,T4 main;
```

**Agent Responds to User Prompt**

<br>

```mermaid
flowchart TD
    B1[User Prompt Received]
    B2[Append to History]
    B3[Process Response]
    B4[Build Model Call]
    B5[Attach Prompt]
    B6[Attach Tools]
    B7[Call LLM API]
    B8[Dispatch to Tool]
    B9[Return LLM Response]
    B10[Return Tool Result]
    B11[Store Reply]
    B12[Persist State]

    B1 --> B2 --> B3 --> B4 --> B7
    B3 --> B5 --> B7
    B3 --> B6 --> B7
    B7 -- Tool Call --> B8 --> B10 --> B11 --> B12
    B7 -- No Tool --> B9 --> B11
    B11 --> B12

    classDef main fill:#f5f7fa,stroke:#6366f1,stroke-width:2px,color:#222,font-size:16px;
    class B1,B2,B3,B4,B5,B6,B7,B8,B9,B10,B11,B12 main;
```


---

## ⚙️ How the Flow Works

1. **User Message**  
   A user sends a question/utterance to the system.
2. **Authentication Check**  
   If not authenticated, the Authentication Agent prompts for identity and credentials.
3. **Intent Classification**  
   Once authenticated, the Intent Classifier agent determines the category (e.g., Medication, Billing, etc.).
4. **Domain Agent Routing**  
   The classified request is routed to the correct domain agent for that task.
5. **Tool/Knowledge Enforcement**  
   Each domain agent can only respond using approved tools or enterprise knowledge—never open-ended LLM knowledge.
6. **Response or Escalation**  
   The agent replies to the user or, if unable, escalates to a fallback (e.g., a human agent or “Sorry, I can’t answer that” message).

---

## 🏆 Key Best Practices

- **Strict intent mapping:** Always classify before routing to a domain agent
- **No hallucination:** Domain agents must use only tool-based or knowledge-backed answers (not general LLM knowledge)
- **Modularity:** Agents and tools are configured via YAML for easy updates and auditability
- **Persistence:** Conversation state and context are tracked for every session, allowing safe multi-turn dialog

---

> This is the foundation for a safe, auditable, and enterprise-grade agent orchestration platform in healthcare or any other regulated industry.

---

*Let us know if you want a third diagram for error handling, audit logging, or a sequence diagram for step-by-step processing!*