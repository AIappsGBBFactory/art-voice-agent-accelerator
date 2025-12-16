# Insurance Scenario - Multi-Agent Voice System

## Business Overview

This scenario demonstrates a **multi-agent insurance voice system** that handles both **B2B** and **B2C** callers through intelligent routing and specialized agents.

### Business Value

| Capability | Business Impact |
|------------|-----------------|
| **24/7 Automated Service** | Reduce call center costs, handle overflow |
| **B2B Subrogation Hotline** | Faster inter-company claim resolution |
| **Policy Self-Service** | Customers get instant answers without hold times |
| **FNOL Intake** | Structured claim collection, fewer errors |
| **Intelligent Routing** | Right agent for the right caller type |

## Agent Architecture

```
                    ┌───────────────┐
                    │   AuthAgent   │  ← Entry Point (Authentication Gate)
                    └───────┬───────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
   ┌───────────┐      ┌───────────┐      ┌───────────┐
   │  Policy   │ ◄──► │   FNOL    │      │   Subro   │
   │  Advisor  │      │   Agent   │      │   Agent   │
   └───────────┘      └───────────┘      └───────────┘
        │                  │                  │
        └────── B2C ───────┘                  │
         (Policyholders)               B2B (CC Reps)
```

### Agent Roles

| Agent | Caller Type | Purpose |
|-------|-------------|---------|
| **AuthAgent** | All | Greet, identify caller type, authenticate, route |
| **PolicyAdvisor** | B2C | Answer policy questions, coverage inquiries |
| **FNOLAgent** | B2C | File new insurance claims (accidents, losses) |
| **SubroAgent** | B2B | Handle inter-company subrogation inquiries |

## 🎯 Test Scenarios

### Scenario A: B2B Subrogation Demand Status

> **Persona**: Sarah from Progressive Insurance calling about a claim where her customer was hit by our insured.

#### Setup
1. Create demo profile: `scenario=insurance`, `role=cc_rep`
2. Note the claim number (e.g., `CLM-2025-119709`)

#### Script

| Turn | Caller Says | Agent Does | Tool Triggered |
|------|-------------|------------|----------------|
| 1 | "Hi, I'm calling about claim CLM-2025-119709" | Asks for company and name | — |
| 2 | "Progressive Insurance, Sarah Johnson" | Verifies CC access | `verify_cc_caller` ✓ |
| 3 | — | Hands off to SubroAgent | `handoff_subro_agent` |
| 4 | "What's the status of our demand?" | Retrieves demand info | `get_subro_demand_status` ✓ |
| 5 | "Has liability been determined?" | Checks liability | `get_liability_decision` ✓ |
| 6 | "What are the policy limits?" | Discloses if liability > 0 | `get_pd_policy_limits` ✓ |
| 7 | "Any payments made?" | Checks payments | `get_pd_payments` ✓ |
| 8 | "Thanks, that's all" | Documents call | `append_claim_note` ✓ |

#### Business Rules Tested
- ✅ CC company must match claim's claimant_carrier
- ✅ Policy limits only disclosed after liability acceptance
- ✅ All interactions documented for audit trail

### Scenario B: B2B Rush Escalation Request

> **Persona**: Mike from Allstate calling about an attorney-represented claim that needs expediting.

#### Script

| Turn | Caller Says | Agent Does | Tool Triggered |
|------|-------------|------------|----------------|
| 1 | "Claim CLM-2025-860979, Allstate, Mike Davis" | Verifies | `verify_cc_caller` ✓ |
| 2 | "I need this expedited - claimant has an attorney" | Evaluates rush criteria | `evaluate_rush_criteria` ✓ |
| 3 | — | Creates rush diary | `create_isrush_diary` ✓ |
| 4 | — | Documents escalation | `append_claim_note` ✓ |

#### Rush Criteria (any triggers ISRUSH)
- 🔴 Attorney represented
- 🔴 Demand over policy limits
- 🔴 Statute of limitations within 60 days
- 🔴 Prior unanswered demands
- 🔴 Explicit escalation request

### Scenario C: B2C Policy Coverage Inquiry

> **Persona**: Alice, a policyholder, calling to check if she has roadside assistance.

#### Setup
1. Create demo profile: `scenario=insurance`, `role=policyholder`
2. Note the SSN4 (e.g., `1234`)

#### Script

| Turn | Caller Says | Agent Does | Tool Triggered |
|------|-------------|------------|----------------|
| 1 | "Hi, I need to check my coverage" | Asks for name + SSN4 | — |
| 2 | "Alice Brown, last four 1234" | Verifies identity | `verify_client_identity` ✓ |
| 3 | "Do I have roadside assistance?" | Searches policy | `search_policy_info` ✓ |
| 4 | "What's my deductible for collision?" | Queries deductible | `search_policy_info` ✓ |
| 5 | "What cars are on my policy?" | Lists vehicles | `search_policy_info` ✓ |

#### Business Rules Tested
- ✅ Must authenticate before accessing policy data
- ✅ Natural language policy queries supported
- ✅ Returns data specific to caller's policies

### Scenario D: B2C First Notice of Loss (FNOL)

> **Persona**: Bob, a policyholder, calling to report a car accident.

#### Script

| Turn | Caller Says | Agent Does | Tool Triggered |
|------|-------------|------------|----------------|
| 1 | "I was in an accident and need to file a claim" | Verifies identity first | `verify_client_identity` ✓ |
| 2 | — | Routes to FNOLAgent | Handoff |
| 3-12 | [Collects all 10 FNOL fields] | Guides through intake | — |
| 13 | [Confirms all details] | Records the claim | `record_fnol` ✓ |

#### FNOL Fields Collected
1. Driver identification
2. Vehicle details (year, make, model)
3. Number of vehicles involved
4. Incident description
5. Loss date/time
6. Loss location
7. Vehicle drivable status
8. Passengers
9. Injury assessment
10. Trip purpose

### Scenario E: Multi-Claim Inquiry (B2B)

> **Persona**: CC rep checking on multiple claims in one call.

#### Script

| Turn | Caller Says | Agent Does | Tool Triggered |
|------|-------------|------------|----------------|
| 1 | "Claim CLM-2025-119709, Contoso, John" | Verifies first claim | `verify_cc_caller` ✓ |
| 2 | [Gets info on first claim] | Retrieves data | `get_subro_demand_status` ✓ |
| 3 | "I have another claim: CLM-2025-860979" | Re-verifies for second | `verify_cc_caller` ✓ |
| 4 | [Gets info on second claim] | Retrieves data | `get_claim_summary` ✓ |

#### Business Rules Tested
- ✅ Each claim requires separate verification
- ✅ CC company must match for each claim

## 🔧 Tools Reference

### Authentication Tools (auth.py)

| Tool | Scenario | Purpose |
|------|----------|---------|
| `verify_cc_caller` | B2B | Verify CC rep by claim + company match |
| `verify_client_identity` | B2C | Verify policyholder by name + SSN4 |

### Subrogation Tools (subro.py)

| Tool | Returns |
|------|---------|
| `get_claim_summary` | Parties, loss date, status |
| `get_subro_demand_status` | Demand amount, handler, status |
| `get_liability_decision` | Accepted/denied, percentage |
| `get_coverage_status` | Confirmed, pending, CVQ |
| `get_pd_policy_limits` | PD limits (if liability > 0) |
| `get_pd_payments` | Payment history, totals |
| `evaluate_rush_criteria` | Qualifies for ISRUSH? |
| `create_isrush_diary` | Rush diary entry |
| `append_claim_note` | Document the call |
| `resolve_feature_owner` | Handler for PD/BI/SUBRO |
| `get_subro_contact_info` | Fax/phone numbers |

### Policy Tools (policy.py)

| Tool | Returns |
|------|---------|
| `search_policy_info` | Natural language query results |
| `get_policy_limits` | Coverage limits by type |
| `get_policy_deductibles` | Deductible amounts |
| `list_user_policies` | All policies for user |
| `list_user_claims` | All claims for user |

### FNOL Tools (fnol.py)

| Tool | Returns |
|------|---------|
| `record_fnol` | Claim ID, confirmation |
| `handoff_to_general_info_agent` | Route non-claim inquiries |


## 📊 System Capabilities Summary

| Capability | How It's Demonstrated |
|------------|----------------------|
| **Multi-Agent Orchestration** | AuthAgent → SubroAgent/PolicyAdvisor/FNOLAgent |
| **B2B Authentication** | Claim ownership + company verification |
| **B2C Authentication** | Name + SSN4 verification |
| **Real-Time Data Access** | Live Cosmos DB queries during calls |
| **Business Rule Enforcement** | Liability required before limits disclosure |
| **Escalation Workflows** | ISRUSH criteria evaluation + diary creation |
| **Audit Trail** | Automatic call documentation |
| **Natural Language Queries** | Policy questions without structured input |
| **Structured Data Collection** | FNOL 10-field intake process |
