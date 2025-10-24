# Finance Agents

This directory contains agent configurations, tools, and prompts for the **Financial Services** use case.

## Structure

```
financeagent/
├── agent_store/     # YAML configurations for finance agents
├── tool_store/      # Custom tools for banking, loans, investments
├── prompt_store/    # Finance-specific prompt templates
└── README.md
```

## Agents

Finance use case includes the following specialist agents:

1. **AuthAgent** - Customer authentication and verification
2. **AccountAgent** - Account management and transactions
3. **LoanAgent** - Loan applications and inquiries
4. **InvestmentAgent** - Investment portfolio management

## Use Case Selection

Users access this use case by pressing **3** when prompted with the DTMF selection menu.

## Configuration

See `apps/rtagent/backend/src/config/use_cases.py` for use case configuration.
See `apps/rtagent/backend/src/orchestration/financeagent/` for orchestration logic.

## Tools

Finance-specific tools include:
- `check_balance` - View account balance
- `transfer_funds` - Transfer between accounts
- `loan_status` - Check loan application status
- `payment_schedule` - View loan payment schedule
- `portfolio_summary` - View investment portfolio
- `market_data` - Get current market information

## Next Steps

To implement finance agents:
1. Create agent YAML files in `agent_store/`
2. Define finance-specific tools in `tool_store/`
3. Add prompt templates to `prompt_store/`
4. Implement orchestrator in `src/orchestration/financeagent/`
