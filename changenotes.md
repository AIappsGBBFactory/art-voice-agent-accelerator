# Change Notes - v2/speech-orchestration-and-monitoring Branch

> **Branch Summary**: 111 commits | 310 files changed | +67,861 / -22,223 lines

---

## 🎯 Major Features

### 1. Azure VoiceLive SDK Integration
- **New VoiceLive orchestration layer** (`voice/voicelive/`) for real-time voice AI
- Agent adapter pattern bridging unified agents to VoiceLive SDK protocols
- Session loader with YAML-driven agent configuration
- WebSocket-based audio streaming with VAD (Voice Activity Detection)
- Support for Azure Standard TTS voices with configurable speech parameters

### 2. Unified Agent Framework
- **YAML-driven agent definitions** (`agents/*.yaml`) replacing hardcoded agent logic
- New base `UnifiedAgent` class with Jinja2 prompt templating
- Agent loader with hot-reload capabilities
- Session manager for multi-agent state tracking
- Support for both Speech Cascade and VoiceLive orchestration modes

### 3. Multi-Agent Orchestration
- **Speech Cascade Adapter**: Browser-based speech recognition with streaming LLM
- **Live Orchestrator**: VoiceLive SDK orchestration with seamless agent handoffs
- Handoff protocol with context preservation across agent switches
- Greeting fallback mechanism for reliable agent introductions
- Tool execution routing through shared registry

### 4. Comprehensive Tool System
- Centralized tool registry (`agents/tools/`) with 15+ business tools
- **Authentication tools**: MFA verification, voicemail detection, PIN validation
- **Banking tools**: Balance inquiry, transaction history, bill pay, transfers
- **Fraud tools**: Alert review, dispute filing, card management
- **Handoff tools**: Agent-to-agent transfers with context passing
- **Knowledge base tools**: RAG-powered search across documentation
- Call transfer integration with Azure Communication Services

---

## 🏦 Banking & Finance Scenario

### New Agents
- **Concierge**: Intelligent routing with customer intent classification
- **AuthAgent**: Multi-factor authentication with voicemail detection
- **FraudAgent**: Fraud alert handling and dispute management
- **PayPalAgent**: Third-party payment service integration
- **InvestmentAdvisor**: Portfolio and investment guidance
- **CardRecommendation**: Credit card product recommendations
- **ComplianceDesk**: Regulatory compliance assistance
- **GeneralKBAgent**: FAQ and knowledge base queries

### Demo Environment
- 24-hour temporary demo users with TTL management
- Seed data for realistic banking scenarios
- MFA channel configuration (SMS/Email)
- Customer intelligence profiles with behavioral data

---

## 📞 Voice & Communication

### Azure Communication Services (ACS)
- Enhanced media streaming handler with session mapping
- DTMF tone detection and validation
- Call transfer to call center with warm handoff
- Event-driven architecture for call lifecycle management

### Speech Processing
- **Phrase biasing**: Dynamic phrase list management for improved recognition
- Configurable audio transcription settings per agent
- Speech-to-text with real-time streaming
- Text-to-speech with Azure neural voices

### Real-Time Features
- WebSocket message handlers for browser communication
- Audio buffering and playback management
- Barge-in detection with response cancellation
- Status tones and system message formatting

---

## 🔍 Observability & Telemetry

### OpenTelemetry Integration
- Comprehensive tracing decorators for LLM, speech, and ACS calls
- Span attributes for call connection ID, session ID, and agent context
- Latency tracking with percentile metrics
- Error reporting with structured event logging

### Monitoring Enhancements
- Health endpoints with readiness checks
- Metrics API for performance monitoring
- Backend health hooks for frontend integration
- Structured JSON logging with correlation IDs

---

## 🛠 Infrastructure & Configuration

### Terraform Updates
- Azure VoiceLive model deployment configurations
- Voice model capacity and SKU settings
- Communication services email domain resources
- Staging environment parameter updates

### Application Configuration
- Feature flags for gradual rollout
- Connection pooling for AOAI and Redis
- Security configuration refinements
- Environment-based settings management

---

## 🧪 Testing

### New Test Suites
- `test_call_transfer_service.py`: Call transfer functionality
- `test_cosmosdb_manager_ttl.py`: TTL and document lifecycle
- `test_on_demand_pool.py`: Connection pool management
- `test_phrase_list_manager.py`: Speech phrase biasing
- `test_realtime.py`: Real-time voice processing
- `test_session_agent_manager.py`: Multi-agent session state
- `test_speech_phrase_list.py`: Speech recognition tuning

### Test Infrastructure
- Shared fixtures in `conftest.py`
- Load testing utilities for ACS media
- Mock implementations for Azure services

---

## 🎨 Frontend Enhancements

### UI Components
- `StreamingModeSelector`: Choose between Speech Cascade and VoiceLive
- `ProfileButton` with MUI integration
- `ProfileDetailsPanel`: User profile display with institution details
- `DemoScenariosWidget`: Interactive demo scenario selection
- `BackendIndicator`: Health status display

### User Experience
- Chat bubble styling improvements
- System message dividers with timestamps
- Status tone metadata display
- Microphone stream cleanup on disconnect

---

## 📚 Documentation

### New Guides
- `BANKING_TESTING_GUIDE.md`: End-to-end testing instructions
- `BANKING_TOOLS_IMPLEMENTATION.md`: Tool development reference
- `agents/README.md`: Agent framework documentation
- `agent-consolidation-plan.md`: Architecture evolution plan

### API Documentation
- Handler architecture overview
- Configuration reference updates
- Deployment guides for voice services

---

## 🐛 Bug Fixes & Improvements

### Handoff Flow
- Fixed "I'm Assistant, your None assistant" greeting bug
- Resolved VoiceLive "already has active response" conflicts
- New agent now responds naturally after handoff (no transition message confusion)
- Context preservation across agent switches

### Streaming & Reliability
- Added 90s overall timeout and 5s per-chunk timeout for LLM streaming
- Fixed tool call index validation to filter malformed responses
- Graceful cancellation for TTS operations
- Session ID resolution retry mechanism

### Data & State
- Redis session persistence for cross-request continuity
- Auto-load user profile on handoff when client_id present
- Demo user TTL normalization to 24 hours
- CosmosDB TTL management improvements

