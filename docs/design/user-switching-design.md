# 🎯 User Switching & Profile Management Design
## ARTAgent Retail Edition - Frontend/Backend Integration

---

## ✅ IMPLEMENTATION COMPLETE

**Status**: ✅ **FULLY IMPLEMENTED** (Nov 1, 2025)

**What was built**:
1. ✅ Backend API endpoints (`/api/v1/customers`, `/api/v1/customer/{user_id}`)
2. ✅ Frontend UserSwitcher component with Apple-style design
3. ✅ Session management with user context
4. ✅ WebSocket integration with `user_id` parameter
5. ✅ Auto-load first user on app mount

---

## 📋 EXECUTIVE SUMMARY

**Goal**: Implement seamless user switching in the frontend that:
1. Fetches real user data from Cosmos DB (3 synthetic users from notebook 12)
2. Creates new session on each user switch (isolated conversations)
3. Passes user context to voice agent prompts for personalization
4. Uses clean, Apple-style UI matching existing design system

**Final Design**: User switcher positioned in **top-right corner** above the main ARTAgent chat box

**Three Users Available**:
- **Sarah Johnson** (Member, 28, Seattle) - Athletic, sustainable brands
- **Michael Chen** (Platinum, 35, SF) - Business casual, high-value
- **Emma Rodriguez** (Gold, 42, Austin) - Boho style, colorful

---

## 🏗️ ARCHITECTURE DESIGN

### 1. **Backend API Endpoint** (New)

**Endpoint**: `GET /api/v1/customers`

**Purpose**: Return list of available customers for switching

**Response**:
```json
{
  "status": "success",
  "customers": [
    {
      "user_id": "sarah_johnson",
      "full_name": "Sarah Johnson",
      "loyalty_tier": "Member",
      "location": "Seattle, WA",
      "avatar_emoji": "🏃‍♀️",
      "style_summary": "Athletic & Eco-Conscious"
    },
    {
      "user_id": "michael_chen",
      "full_name": "Michael Chen",
      "loyalty_tier": "Platinum",
      "location": "San Francisco, CA",
      "avatar_emoji": "💼",
      "style_summary": "Business Professional"
    },
    {
      "user_id": "emma_rodriguez",
      "full_name": "Emma Rodriguez",
      "loyalty_tier": "Gold",
      "location": "Austin, TX",
      "avatar_emoji": "🌸",
      "style_summary": "Boho & Colorful"
    }
  ]
}
```

**Endpoint**: `GET /api/v1/customer/{user_id}`

**Purpose**: Fetch full customer profile for selected user

**Response**:
```json
{
  "status": "success",
  "customer": {
    "user_id": "sarah_johnson",
    "full_name": "Sarah Johnson",
    "age": 28,
    "location": {
      "city": "Seattle",
      "state": "WA",
      "climate": "mild_rainy"
    },
    "loyalty_tier": "Member",
    "loyalty_points": 2400,
    "preferences": {
      "style": ["athletic", "casual", "sustainable"],
      "colors": ["forest_green", "navy", "black"],
      "brands": ["Patagonia", "Lululemon", "Nike"]
    },
    "shopping_patterns": {
      "avg_monthly_spend": 280,
      "favorite_categories": ["Activewear", "Running Shoes"]
    },
    "conversation_memory": {
      "recent_queries": ["yoga pants size 8", "running shoes for rain"],
      "known_context": [
        "Training for a half marathon",
        "Prefers sustainable brands"
      ]
    }
  }
}
```

---

### 2. **Frontend State Management**

**New State Variables** (add to App.jsx):
```javascript
// User management state
const [currentUser, setCurrentUser] = useState(null);
const [availableUsers, setAvailableUsers] = useState([]);
const [userMenuOpen, setUserMenuOpen] = useState(false);
const [isLoadingUser, setIsLoadingUser] = useState(false);
```

**Data Flow**:
```
1. App Mount → Fetch `/api/v1/customers` → Store in `availableUsers`
2. Auto-select first user (Sarah Johnson) as default
3. Fetch full profile → `/api/v1/customer/sarah_johnson` → Store in `currentUser`
4. User clicks switch button → Show dropdown menu
5. User selects different user → Create new session + fetch new profile
6. WebSocket connection includes `user_id` in query params
```

---

### 3. **UI Component Design**

#### **Location**: Header (next to ARTAgent title)

**Visual Style**:
```
┌─────────────────────────────────────────────────────┐
│  👤 Sarah Johnson (Member) ▼                        │
│  ARTAgent - Retail Shopping Assistant               │
└─────────────────────────────────────────────────────┘
```

**Dropdown Menu** (when clicked):
```
┌──────────────────────────────────────┐
│ 🏃‍♀️ Sarah Johnson                    │
│    Member • Seattle, WA            │
│    Athletic & Eco-Conscious        │
├──────────────────────────────────────┤
│ 💼 Michael Chen               [✓]  │
│    Platinum • San Francisco, CA    │
│    Business Professional           │
├──────────────────────────────────────┤
│ 🌸 Emma Rodriguez                   │
│    Gold • Austin, TX               │
│    Boho & Colorful                 │
└──────────────────────────────────────┘
```

**Design Specs**:
- **Colors**: Match existing blue gradient theme (#dbeafe, #e0f2fe)
- **Font**: Segoe UI, 13px for name, 11px for details
- **Border**: 1px solid #bae6fd with border-radius 12px
- **Shadow**: 0 4px 12px rgba(56, 189, 248, 0.15)
- **Hover**: Subtle scale(1.02) + deeper shadow
- **Transition**: All 200ms ease

---

### 4. **Session Management Strategy**

**Current Behavior**:
```javascript
// Existing session logic in App.jsx
const sessionId = getOrCreateSessionId(); // Persists in sessionStorage
```

**New Behavior** (on user switch):
```javascript
const handleUserSwitch = async (newUserId) => {
  // 1. Create NEW session (isolated conversation)
  const newSessionId = createNewSessionId();
  
  // 2. Fetch new user profile
  const userData = await fetchUserProfile(newUserId);
  
  // 3. Close existing WebSocket (if any)
  if (ws.current) {
    ws.current.close();
  }
  
  // 4. Clear chat history
  setMessages([]);
  
  // 5. Update state
  setCurrentUser(userData);
  setSessionId(newSessionId);
  
  // 6. Reconnect WebSocket with new user context
  connectWebSocket(newSessionId, newUserId);
};
```

**WebSocket Connection Update**:
```javascript
// Current:
const wsUrl = `${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}`;

// New:
const wsUrl = `${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}&user_id=${currentUser.user_id}`;
```

---

### 5. **Backend Integration Points**

#### **A. Cosmos DB Query** (in backend endpoint)
```python
# apps/rtagent/backend/api/v1/customers.py

from src.cosmosdb.manager import CosmosDBMongoCoreManager

users_manager = CosmosDBMongoCoreManager(
    database_name="retail-db",
    collection_name="users"
)

@app.get("/api/v1/customers")
async def get_customers():
    """Get list of available customers for demo"""
    users = await asyncio.to_thread(
        users_manager.query_documents,
        query={},
        projection={"user_id": 1, "full_name": 1, "loyalty_tier": 1, "location": 1, "preferences": 1}
    )
    
    # Transform for frontend
    customers = [
        {
            "user_id": user["user_id"],
            "full_name": user["full_name"],
            "loyalty_tier": user.get("dynamics365_data", {}).get("loyalty_tier", "Member"),
            "location": f"{user['location']['city']}, {user['location']['state']}",
            "avatar_emoji": get_avatar_emoji(user),
            "style_summary": ", ".join(user["preferences"]["style"][:2])
        }
        for user in users
    ]
    
    return {"status": "success", "customers": customers}
```

#### **B. Prompt Template Context** (pass user data)
```python
# When rendering prompt template
context = {
    "customer_name": current_user["full_name"],
    "loyalty_tier": current_user["loyalty_tier"],
    "location": f"{current_user['location']['city']}, {current_user['location']['state']}",
    "style_preferences": ", ".join(current_user["preferences"]["style"]),
    "recent_searches": ", ".join(current_user["conversation_memory"]["recent_queries"][:3])
}

prompt = template.render(**context)
```

---

## 🎨 UI MOCKUP (ASCII)

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│  ┌────────────────────────────────┐                   │
│  │ 🏃‍♀️ Sarah Johnson (Member) ▼ │                   │
│  └────────────────────────────────┘                   │
│                                                        │
│              ARTAgent                                  │
│     Retail Shopping Assistant                         │
│                                                        │
├────────────────────────────────────────────────────────┤
│                                                        │
│              [Waveform Visualization]                 │
│                                                        │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Agent: Hi Sarah! Welcome back. I see you're         │
│         training for a half marathon. Looking         │
│         for more running gear today?                  │
│                                                        │
│  You:   Show me waterproof running shoes             │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## ✅ IMPLEMENTATION CHECKLIST

### **Phase 1: Backend (30 mins)**
- [ ] Create `apps/rtagent/backend/api/v1/customers.py`
- [ ] Add `GET /api/v1/customers` endpoint
- [ ] Add `GET /api/v1/customer/{user_id}` endpoint
- [ ] Query Cosmos DB `retail-db.users` collection
- [ ] Add avatar emoji mapping logic
- [ ] Register routes in `main.py`
- [ ] Test endpoints with curl/Postman

### **Phase 2: Frontend State (20 mins)**
- [ ] Add new state variables (`currentUser`, `availableUsers`, etc.)
- [ ] Create `fetchAvailableUsers()` function
- [ ] Create `fetchUserProfile(userId)` function
- [ ] Update `useEffect` to load users on mount
- [ ] Modify `createNewSessionId()` to accept optional user context

### **Phase 3: UI Component (40 mins)**
- [ ] Create `UserSwitcher` component
- [ ] Design dropdown menu with user cards
- [ ] Add user avatar emojis (🏃‍♀️, 💼, 🌸)
- [ ] Implement click-outside-to-close logic
- [ ] Add loading spinner during user switch
- [ ] Style with existing blue gradient theme

### **Phase 4: WebSocket Integration (20 mins)**
- [ ] Update WebSocket URL to include `user_id` param
- [ ] Backend: Extract `user_id` from query params
- [ ] Pass user data to prompt template context
- [ ] Test personalized greetings

### **Phase 5: Session Management (15 mins)**
- [ ] Implement `handleUserSwitch()` function
- [ ] Clear chat history on switch
- [ ] Create new session ID
- [ ] Reconnect WebSocket
- [ ] Add confirmation toast ("Switched to Michael Chen")

### **Phase 6: Testing (15 mins)**
- [ ] Test switching between all 3 users
- [ ] Verify isolated sessions (no conversation leakage)
- [ ] Check personalized greetings mention correct name/tier
- [ ] Verify Cosmos DB queries are efficient
- [ ] Test mobile responsiveness

**Total Estimated Time**: ~2.5 hours

---

## 🔒 SECURITY CONSIDERATIONS

1. **No Authentication Required** (demo mode with synthetic users)
2. **Read-Only Access** (no user data modification)
3. **Session Isolation** (each user switch = new session)
4. **No PII Exposure** (only synthetic demo data)

---

## 📊 BENEFITS

✅ **Personalization Showcase**: Agent greets by name, knows preferences  
✅ **Loyalty Tier Demo**: Different discounts per user (10%/15%/20%)  
✅ **Context Awareness**: References recent searches, shopping patterns  
✅ **Clean UX**: Apple-style dropdown, smooth transitions  
✅ **Production Pattern**: Real Cosmos DB integration, scalable architecture  

---

## 🤔 QUESTIONS FOR APPROVAL

1. **Placement**: User switcher in header next to title (as designed above)? ✓  
2. **Default User**: Auto-select Sarah Johnson on first load? ✓  
3. **Avatar Style**: Emoji (🏃‍♀️) or initials (SJ)? → **Emoji preferred**  
4. **Animation**: Smooth fade transition on user switch? ✓  
5. **Confirmation**: Show toast message "Switched to [User]"? ✓  

---

## 🚀 NEXT STEPS

**IF APPROVED**:
1. I'll implement backend endpoints first (testable independently)
2. Then build frontend component (iterative with your feedback)
3. Integrate WebSocket user context
4. Polish UI animations and transitions
5. Test all 3 user scenarios

**AWAITING YOUR APPROVAL TO PROCEED** ✋

