# Transfer Agency Multi-Agent System Test Guide

## Overview

This system implements a multi-agent voice interface for financial services with two main capabilities:
1. **Fraud Detection Agent** - Detects suspicious activities and security threats
2. **Transfer Agency System** - Handles DRIP liquidations with compliance and trading specialists

## Architecture

```
AutoAuth Agent (MFA Entry Point)
├── Fraud Agent (Suspicious Activity Detection)
└── Agency Agent (Transfer Agency Coordinator)
    ├── Compliance Specialist (AML/FATCA Review)
    └── Trading Specialist (Complex Execution)
```

## Quick Start

### 1. Start the System
```bash
# Activate environment
conda activate audioagent

# Start backend
make start_backend

# Start frontend (separate terminal)
make start_frontend
```

### 2. Access the Interface
- Web Interface: http://localhost:3000
- Backend API: http://localhost:8080
- Health Check: http://localhost:8080/api/v1/health

## Test Scenarios

### Fraud Detection Use Case

**Scenario**: Suspicious account activity requiring investigation

**Test Questions**:
```
"I need to report suspicious activity on my account"
"Someone has been trying to access my account from different locations"
"I received unauthorized transaction alerts"
"My account shows transfers I didn't make"
"I think my identity has been stolen"
```

**Expected Flow**:
1. AutoAuth Agent authenticates caller
2. Routes to Fraud Agent based on keywords
3. Fraud Agent investigates and documents findings
4. Escalates to appropriate security channels

### Transfer Agency Use Case

**Scenario**: Emily Rivera DRIP liquidation (Mock client GCA-48273)

**Test Questions**:
```
"I need to liquidate my DRIP positions"
"Can you help me cash out my dividend reinvestment plan?"
"I want to sell my PLTR shares from the DRIP program"
"What's the process for liquidating DRIP investments?"
"I need to convert my DRIP holdings to cash"
```

**Expected Flow**:
1. AutoAuth Agent authenticates caller
2. Routes to Agency Agent for transfer services
3. Agency Agent retrieves client data (Emily Rivera, GCA-48273)
4. Shows PLTR position: 1,078.42 shares
5. Identifies compliance issue: AML expires in 5 days
6. Hands off to Compliance Specialist for review
7. After compliance, Trading Specialist handles execution
8. Final proceeds: approximately €14,580.38

### Multi-Agent Handoff Testing

**Compliance Handoff Questions**:
```
"My AML documentation needs review before liquidation"
"Is my compliance status current for this transaction?"
"Do I need updated KYC for this DRIP liquidation?"
```

**Trading Handoff Questions**:
```
"What's the best execution strategy for my PLTR position?"
"How do I minimize market impact for this liquidation?"
"Can you handle the FX conversion from USD to EUR?"
```

## Validation Checklist

### System Health
- [ ] All 5 agents show "healthy" in health endpoint
- [ ] Frontend displays agent status correctly
- [ ] No configuration import errors in logs

### Agent Loading
- [ ] AutoAuth agent loaded
- [ ] Fraud agent loaded  
- [ ] Agency agent loaded
- [ ] Compliance agent loaded
- [ ] Trading agent loaded

### Routing Validation
- [ ] Fraud keywords route to Fraud Agent
- [ ] Transfer/DRIP keywords route to Agency Agent
- [ ] Compliance issues trigger specialist handoff
- [ ] Trading complexity triggers specialist handoff

### Emily Rivera Scenario
- [ ] Client lookup returns correct data (GCA-48273)
- [ ] PLTR position shows 1,078.42 shares
- [ ] Compliance status shows AML expiring soon
- [ ] Liquidation calculation shows ~€14,580.38
- [ ] Handoffs work between Agency→Compliance→Trading

## Test Commands

### Backend Health Check
```bash
curl http://localhost:8080/api/v1/health | jq .
```

### Agent Status Check
```bash
curl http://localhost:8080/api/v1/agents | jq .
```

### Readiness Check
```bash
curl http://localhost:8080/api/v1/readiness | jq .
```

## Mock Data Reference

### Emily Rivera Profile
- **Client ID**: GCA-48273
- **Name**: Emily Rivera
- **Firm**: Global Capital Advisors  
- **Account Currency**: EUR
- **DRIP Position**: 1,078.42 PLTR shares
- **Compliance Status**: AML expires in 5 days
- **Liquidation Value**: ~€14,580.38

## Troubleshooting

### Common Issues
1. **Config Import Errors**: Ensure running from correct directory
2. **Agent Not Loading**: Check YAML config files exist
3. **Routing Failures**: Verify orchestrator bindings
4. **Tool Errors**: Confirm all 24 tools registered

### Debug Commands
```bash
# Test orchestrator setup
python -c "from apps.rtagent.backend.src.orchestration.artagent.orchestrator import bind_default_handlers; bind_default_handlers(); print('OK')"

# Test tool registry
python -c "from apps.rtagent.backend.src.agents.artagent.tool_store.tool_registry import function_mapping; print(f'Tools: {len(function_mapping)}')"

# Test Emily Rivera data
python -c "import asyncio; from apps.rtagent.backend.src.agents.artagent.tool_store.transfer_agency_tools import get_client_data; print(asyncio.run(get_client_data('GCA-48273')))"
```

## Success Metrics

**System Ready When**:
- All health checks pass
- 5 agents loaded and responsive  
- Fraud detection routing works
- Emily Rivera scenario executes end-to-end
- Multi-agent handoffs complete successfully
- Frontend shows real-time agent status

## Next Steps

After successful testing:
1. Configure production environment variables
2. Set up real client data sources
3. Implement actual trading integrations
4. Add production security controls
5. Deploy to Azure infrastructure