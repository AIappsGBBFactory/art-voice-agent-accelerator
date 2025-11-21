# Banking Agent Testing Guide

## 🚀 Quick Start Testing

### 1. Environment Setup
Ensure these variables are set in `.env`:
```bash
AGENT_NAME=Erica
INSTITUTION_NAME=Bank of America

# Required for Cosmos DB integration (when implementing)
COSMOS_FINANCIAL_DATABASE=banking_services_db
COSMOS_FINANCIAL_USERS_CONTAINER=users
AZURE_COSMOS_DATABASE_NAME_RAG=financial_services_db

# Required for Azure AI Search RAG (when implementing)
AZURE_AI_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_AI_SEARCH_API_KEY=your-key
```

---

## 🎯 Test Scenarios

### **Scenario 1: Basic Profile Load & Account Query**
**Flow:** EricaConcierge → Profile → Balance

**Test Steps:**
1. Start call
2. Complete authentication
3. Say: "What's my checking account balance?"

**Expected Tool Calls:**
```
1. verify_client_identity(phone_number="...")
2. get_user_profile(client_id="12345")
3. get_account_summary(client_id="12345")
```

**Expected Response:**
"Your checking account ending in 1234 has a balance of $2,450.67."

---

### **Scenario 2: Card Recommendation Handoff**
**Flow:** EricaConcierge → handoff → CardRecommendation

**Test Steps:**
1. Authenticated user asks: "I want to reduce my credit card fees"
2. Agent should detect intent and handoff

**Expected Tool Calls:**
```
1. handoff_card_recommendation(
     client_id="12345",
     customer_goal="reduce fees",
     spending_preferences="...",
     current_cards="Cash Rewards ending in 9012"
   )
```

**Expected Agent Switch:**
```
Active Agent: EricaConcierge → CardRecommendation
Context passed: {client_id, customer_goal, spending_preferences}
```

**CardRecommendation Agent Actions:**
```
1. search_card_products(preferences="low fees", ...)
2. get_card_details(product_id="premium-rewards-001", query="What are the fees?")
```

---

### **Scenario 3: Retirement Rollover Inquiry**
**Flow:** EricaConcierge → handoff → InvestmentAdvisor

**Test Steps:**
1. User says: "I just changed jobs and have a 401k at my old company"
2. Agent detects retirement topic

**Expected Tool Calls:**
```
1. handoff_investment_advisor(
     client_id="12345",
     topic="401k rollover",
     employment_change="Changed jobs recently",
     retirement_question="What should I do with old 401k?"
   )
```

**InvestmentAdvisor Agent Actions:**
```
1. get_retirement_accounts(client_id="12345")
2. search_rollover_guidance(query="60 day rollover deadline", account_type="401k")
```

**Expected Response:**
"You have 60 days from distribution to roll over your $45,000 401(k) from Fidelity. I recommend a direct trustee-to-trustee transfer to avoid the 20% tax withholding."

---

### **Scenario 4: Return to Concierge**
**Flow:** CardRecommendation → handoff → EricaConcierge

**Test Steps:**
1. After card recommendation is complete
2. User asks: "What about my savings account?"

**Expected Tool Calls:**
```
1. handoff_erica_concierge(
     client_id="12345",
     previous_topic="card recommendation",
     resolution_summary="Recommended Premium Rewards card"
   )
```

**Expected Agent Switch:**
```
Active Agent: CardRecommendation → EricaConcierge
Context: Previous topic completed
```

**EricaConcierge Response:**
"I've noted your interest in the Premium Rewards card. Now, let me check your savings account..."

---

## 🔍 Tool Testing (Manual)

### Test Individual Tools

#### 1. Profile Retrieval
```python
from banking_tools import get_user_profile
result = await get_user_profile({"client_id": "test-123"})
print(result)
# Expected: {success: True, profile: {name, tier, goals, alerts}}
```

#### 2. Account Summary
```python
from banking_tools import get_account_summary
result = await get_account_summary({"client_id": "test-123"})
print(result)
# Expected: {success: True, summary: {checking, savings, credit_cards}}
```

#### 3. Card Search
```python
from banking_tools import search_card_products
result = await search_card_products({
    "customer_profile": "Platinum tier",
    "preferences": "travel rewards",
    "spending_categories": ["travel", "dining"]
})
print(result)
# Expected: {success: True, products: [{product_id, name, rewards_rate, ...}]}
```

#### 4. Handoff Test
```python
from banking_handoffs import handoff_card_recommendation
result = await handoff_card_recommendation({
    "client_id": "test-123",
    "customer_goal": "better rewards"
})
print(result)
# Expected: {handoff: True, target_agent: "CardRecommendation", ...}
```

---

## 🐛 Debugging Tips

### Check Tool Registration
```python
from financial_tools import TOOL_SCHEMAS, TOOL_EXECUTORS
print(list(TOOL_SCHEMAS.keys()))
# Should include: get_user_profile, get_account_summary, handoff_card_recommendation, etc.

print(list(TOOL_EXECUTORS.keys()))
# Should match TOOL_SCHEMAS
```

### Check Handoff Map
```python
from registry import HANDOFF_MAP
print(HANDOFF_MAP)
# Should include:
# "handoff_card_recommendation": "CardRecommendation"
# "handoff_investment_advisor": "InvestmentAdvisor"
# "handoff_erica_concierge": "EricaConcierge"
```

### Verify Agent Loading
```python
from registry import load_registry
agents = load_registry("agents")
print(list(agents.keys()))
# Should include: EricaConcierge, CardRecommendation, InvestmentAdvisor
```

### Check Tool Execution
```python
from financial_tools import execute_tool
result = await execute_tool("get_user_profile", {"client_id": "test-123"})
print(result)
# Should return mock profile data
```

---

## 📊 Expected Logs

### Tool Execution Logs
```
[banking_tools] 📋 Fetching user profile | client_id=12345
[banking_tools] 💰 Fetching account summary | client_id=12345
[banking_tools] 💳 Searching card products | profile=Platinum prefs=travel rewards
[banking_handoffs] 💳 Handoff to Card Recommendation Agent | client=12345 goal=reduce fees
```

### Orchestrator Logs
```
[Orchestrator] Starting with agent: EricaConcierge
[Agent Switch] EricaConcierge → CardRecommendation | Context: {client_id, customer_goal} | First visit: True
[Active Agent] CardRecommendation is now active
```

### Tool Registry Logs
```
[voicelive.tools.financial] Registered tool: get_user_profile
[voicelive.tools.financial] Registered tool: handoff_card_recommendation (handoff=True)
```

---

## ⚠️ Common Issues & Fixes

### Issue 1: "Tool 'get_user_profile' is not registered"
**Fix:** Check that `banking_tools.py` is imported in `financial_tools.py` and `tool_registry.py`

### Issue 2: Agent handoff doesn't switch
**Fix:** Verify `HANDOFF_MAP` includes the tool name and agent name matches YAML `agent.name`

### Issue 3: Tool returns error
**Fix:** Check function signature matches schema, and arguments are properly typed

### Issue 4: Agent not found in registry
**Fix:** Ensure YAML file is in `agents/` folder and `agent.name` is correct

### Issue 5: Mock data instead of real data
**Fix:** This is expected! Implement Cosmos DB/AI Search integration to replace mock data

---

## 🎬 Demo Script

### **Alex's Fee Dispute Scenario**

**Narrator:** "Let's see how Erica helps Alex reduce his credit card fees."

**User (Alex):** "Hi, I'm paying too much in fees on my credit card."

**Erica:** "I can help with that! Let me check your account... [calls get_user_profile, get_account_summary]"

**Erica:** "I see you have the Cash Rewards card with a balance of $450. I notice you spend a lot on travel and dining. Let me connect you with our card specialist who can find you a better option."

**[Handoff to CardRecommendation Agent]**

**CardRecommendation:** "Hi Alex, I can help recommend the right card. Based on your Platinum tier and travel spending, I found the Premium Rewards card with 2% cash back on everything and 3% on travel and dining. It has a $95 annual fee, but you'll earn that back with your spending. Plus, you qualify for a 0% balance transfer for 15 months to eliminate your current fees. Would you like me to explain more?"

**User:** "Yes, tell me about the balance transfer."

**CardRecommendation:** [calls get_card_details(product_id="premium-rewards-001", query="balance transfer details")]

**CardRecommendation:** "With the Premium Rewards card, you can transfer your $450 balance with 0% APR for 15 months and no balance transfer fee for the first 60 days. This means you'll save the interest you're currently paying and have over a year to pay it off interest-free."

---

**That's it! Banking agents are ready for testing.** 🎉
