> ⚠️ **Work in Progress Notice**
> 
> This load testing suite is currently under active development and is **not yet in a functional state**. The test framework, scenarios, and configuration are being implemented and may not work as documented. Please check back for updates as development progresses.

# RTMedAgent Load Testing Suite

This directory contains comprehensive load tests for the RTMedAgent real-time voice automation system, organized by logical component groupings.

## 📁 Test Structure

### Core Test Files

- **`config.py`** - Centralized configuration and utilities for all load tests
- **`test_api_endpoints.py`** - REST API endpoint load testing  
- **`test_websockets.py`** - WebSocket handler load testing
- **`test_backend_services.py`** - Backend service (Redis, OpenAI, Speech, Cosmos) load testing
- **`test_integration_flows.py`** - End-to-end integration flow testing
- **`run_load_tests.py`** - Master orchestrator for coordinated testing

### Component Groupings

#### 1. **API Endpoints Group** (`test_api_endpoints.py`)
Tests REST API performance and reliability:
- `GET /health` - Health check monitoring
- `POST /api/call` - Call initiation 
- `POST /api/call/inbound` - Inbound call handling
- `POST /call/callbacks` - ACS webhook processing
- `GET /api/call/{id}/metrics` - Metrics retrieval

**Key Metrics**: Response time, throughput, error rates, concurrent request handling

#### 2. **WebSocket Handlers Group** (`test_websockets.py`)
Tests real-time voice streaming and WebSocket capacity:
- `/ws/realtime` - Browser voice streaming (sub-100ms latency requirement)
- `/ws/call/stream` - ACS bidirectional PCM audio streaming
- `/ws/relay` - Event relay and notifications

**Key Metrics**: Connection latency, message throughput, voice loop latency, concurrent connections

#### 3. **Backend Services Group** (`test_backend_services.py`)
Tests supporting infrastructure performance:
- **Redis Cache** - Session storage and conversation state
- **Azure OpenAI** - LLM completion and TTFT performance
- **Azure Speech Services** - STT/TTS latency and quality
- **Azure Cosmos DB** - Conversation persistence and querying

**Key Metrics**: Service latency, throughput, error handling, resource utilization

#### 4. **Integration Flows Group** (`test_integration_flows.py`)
Tests complete end-to-end scenarios:
- Emergency consultation flows (chest pain, breathing issues)
- Routine medical questions and follow-ups
- Medication consultation and side effects
- Mental health support conversations
- Concurrent call capacity testing

**Key Metrics**: End-to-end latency, conversation quality, user satisfaction simulation, system reliability

## 🚀 Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export API_BASE_URL="https://your-rtmedagent-api.azurewebsites.net"
export WS_BASE_URL="wss://your-rtmedagent-api.azurewebsites.net"
export REDIS_URL="redis://your-redis.cache.windows.net:6380"
```

### Running Individual Tests

```bash
# API endpoints test
python test_api_endpoints.py

# WebSocket handlers test  
python test_websockets.py

# Backend services test
python test_backend_services.py

# Integration flows test
python test_integration_flows.py
```

### Running Comprehensive Test Suite

```bash
# Quick test suite (low load)
python run_load_tests.py --test-suite quick

# Standard test suite (recommended)
python run_load_tests.py --test-suite standard --parallel

# Comprehensive test suite (high load)
python run_load_tests.py --test-suite comprehensive
```

### Custom Test Configuration

```bash
# Custom user counts and parallel execution
python run_load_tests.py \
  --api-users 50 \
  --websocket-users 25 \
  --integration-users 15 \
  --parallel \
  --host https://your-api.azurewebsites.net
```

## 📊 Performance Targets

Based on the load testing documentation, the tests validate against these targets:

| Metric | Target (P95/P99) | Component |
|--------|------------------|-----------|
| WebSocket handshake | < 150ms | WebSocket Handlers |
| Ping-pong RTT | < 250ms | WebSocket Handlers |
| STT first partial | < 400ms | Backend Services |
| STT final segment | < 1000ms | Backend Services |
| LLM TTFT | ≤ 600ms | Backend Services |
| TTS first byte | < 200ms | Backend Services |
| End-to-end voice loop | ≤ 700ms | Integration Flows |

## 📈 Test Scenarios

### Medical Consultation Scenarios

The integration tests simulate realistic medical scenarios:

1. **Emergency Scenarios** (High Priority)
   - Chest pain and cardiac symptoms
   - Breathing difficulties
   - Severe allergic reactions

2. **Urgent Care Scenarios** (Medium Priority)
   - Medication side effects
   - Mental health crises
   - Moderate injury assessment

3. **Routine Care Scenarios** (Normal Priority)
   - Annual checkup questions
   - Lab result discussions
   - Prescription refills
   - Follow-up appointments

### Load Patterns

- **Ramp-up Testing**: Gradual user increase to find capacity limits
- **Sustained Load**: Constant user load for stability testing  
- **Spike Testing**: Sudden load increases to test elasticity
- **Concurrent Scenarios**: Multiple call types simultaneously

## 🔧 Configuration

### Environment Variables

```bash
# Required
API_BASE_URL=https://your-api.azurewebsites.net
WS_BASE_URL=wss://your-api.azurewebsites.net

# Optional (with defaults)
REDIS_URL=redis://localhost:6379
COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com
OPENAI_ENDPOINT=https://your-openai.openai.azure.com
TEST_DURATION=300
MAX_USERS=100
```

### Test Parameters

```python
# In config.py - customize these based on your environment
class TestConfig:
    # Performance targets
    websocket_handshake_target_ms = 150
    end_to_end_voice_loop_target_ms = 700
    stt_final_segment_target_ms = 1000
    llm_ttft_target_ms = 600
    tts_first_byte_target_ms = 200
    
    # Test execution
    test_duration_seconds = 300
    max_concurrent_users = 100
    ramp_up_seconds = 60
```

## 📋 Results and Reports

### Output Files

Tests generate comprehensive reports in the `results/` directory:

- **CSV files**: Raw performance metrics for analysis
- **HTML reports**: Visual performance dashboards  
- **JSON reports**: Machine-readable test results
- **Summary logs**: Console output with pass/fail status

### Report Analysis

```bash
# View test results
ls results/
cat results/load_test_report_YYYYMMDD_HHMMSS.json

# Analyze performance trends
python -c "
import json
with open('results/load_test_report_latest.json') as f:
    data = json.load(f)
    print(f'Success Rate: {data[\"summary\"][\"success_rate\"]:.1f}%')
"
```

## 🎯 Performance Validation

### Success Criteria

- **Overall success rate**: ≥ 95%
- **Voice loop latency**: P95 ≤ 700ms  
- **API response time**: P95 ≤ 150ms
- **WebSocket connection**: P95 ≤ 150ms
- **Error rate**: ≤ 0.5% for critical flows

### Failure Thresholds

Tests fail if:
- Success rate < 80%
- Critical latency targets missed by >50%
- WebSocket connections drop >10%
- Backend service errors >5%

## 🔍 Troubleshooting

### Common Issues

1. **Connection Timeouts**
   ```bash
   # Increase timeout values in config.py
   # Check network connectivity to target environment
   ```

2. **WebSocket Failures**
   ```bash
   # Verify WebSocket endpoint URLs
   # Check firewall/proxy settings
   # Reduce concurrent WebSocket users
   ```

3. **Service Authentication**
   ```bash
   # Verify Azure credentials are set
   # Check service principal permissions
   # Validate connection strings
   ```

4. **Resource Limits**
   ```bash
   # Monitor Azure service quotas
   # Check Redis connection limits
   # Verify OpenAI TPM/RPM limits
   ```

### Debug Mode

```bash
# Run with verbose output
python run_load_tests.py --test-suite quick --verbose

# Run single component test with debugging
LOCUST_LOGLEVEL=DEBUG python test_websockets.py
```

## 🚀 Integration with CI/CD

### GitHub Actions

```yaml
# .github/workflows/load-test.yml
- name: Run Load Tests
  run: |
    python tests/load/run_load_tests.py \
      --test-suite standard \
      --host ${{ secrets.STAGING_API_URL }}
```

### Azure DevOps

```yaml
# azure-pipelines.yml  
- task: PythonScript@0
  inputs:
    scriptSource: 'filePath'
    scriptPath: 'tests/load/run_load_tests.py'
    arguments: '--test-suite standard --parallel'
```

## 📞 Support

For issues with load testing:

1. Check test configuration in `config.py`
2. Verify environment connectivity 
3. Review Azure service quotas and limits
4. Consult the main Load Testing documentation in `docs/LoadTesting.md`

The load testing suite is designed to provide comprehensive validation of the RTMedAgent system's performance under realistic call center workloads while maintaining the sub-100ms latency requirements critical for natural voice interactions.
