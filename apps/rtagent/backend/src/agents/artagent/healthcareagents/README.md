# Healthcare Agents

This directory contains agent configurations, tools, and prompts for the **Healthcare Services** use case.

## Structure

```
healthcareagent/
├── agent_store/     # YAML configurations for healthcare agents
├── tool_store/      # Custom tools for appointments, prescriptions, benefits
├── prompt_store/    # Healthcare-specific prompt templates
└── README.md
```

## Agents

Healthcare use case includes the following specialist agents:

1. **AuthAgent** - Patient authentication and verification
2. **Scheduler** - Appointment scheduling and management
3. **Insurance** - Insurance benefits and prescription refills

## Use Case Selection

Users access this use case by pressing **2** when prompted with the DTMF selection menu.

## Configuration

See `apps/rtagent/backend/src/config/use_cases.py` for use case configuration.
See `apps/rtagent/backend/src/orchestration/healthcareagent/` for orchestration logic.

## Tools

Healthcare-specific tools include:
- `check_availability` - Check appointment slot availability
- `schedule_appointment` - Book new appointments
- `insurance_eligibility` - Verify insurance coverage
- `benefits_lookup` - Check coverage details
- `list_medications` - View prescriptions
- `refill_prescription` - Request refills

## Next Steps

To implement healthcare agents:
1. Copy agent YAML files from `samples/voice_live_sdk/voicelive_multiagent/agents/`
2. Create healthcare-specific tools in `tool_store/`
3. Add prompt templates to `prompt_store/`
4. Implement orchestrator in `src/orchestration/healthcareagent/`
