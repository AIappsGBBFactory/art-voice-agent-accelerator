from __future__ import annotations

"""
Shared Orchestration Utilities Package
=======================================

This package contains shared utilities used by all use case orchestrators:
- cm_utils: Context management helpers
- gpt_flow: GPT streaming logic
- latency: Latency tracking
- termination: Termination/escalation logic

Use case-specific orchestrators are in:
- insuranceagents.orchestrator
- healthcareagents.orchestrator  
- financeagents.orchestrator

These are loaded dynamically by the factory based on DTMF/UI selection.
"""

# This __init__.py intentionally does not import use-case-specific modules
# to avoid circular dependencies and maintain clean separation.
# 
# Use the factory.py to dynamically load orchestrators:
#   from apps.rtagent.backend.src.orchestration.factory import get_orchestrator
