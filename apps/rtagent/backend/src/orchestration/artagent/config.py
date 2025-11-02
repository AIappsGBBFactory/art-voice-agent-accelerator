from __future__ import annotations

import os
from typing import Iterable, Optional

from utils.ml_logging import get_logger

logger = get_logger(__name__)

# Feature flags / constants
ORCHESTRATOR_TRACING: bool = os.getenv("ORCHESTRATOR_TRACING", "true").lower() == "true"
LAST_ANNOUNCED_KEY = "last_announced_agent"
APP_GREETS_ATTR = "greet_counts"

# Orchestration pattern (entry + specialists). Retail voice assistant multi-agent system.
ENTRY_AGENT: str = "ShoppingConcierge"
SPECIALISTS: list[str] = ["ShoppingConcierge", "PersonalStylist", "PostSale"]


def configure_entry_and_specialists(
    *, entry_agent: str = "ShoppingConcierge", specialists: Optional[Iterable[str]] = None
) -> None:
    """
    Configure the entry agent and ordered list of specialists for retail use case.

    Entry agent defaults to Shopping Concierge - the main retail assistant.

    :param entry_agent: Entry agent name (defaults to 'ShoppingConcierge')
    :param specialists: Ordered list of specialist agent names
    :return: None
    """
    global ENTRY_AGENT, SPECIALISTS  # noqa: PLW0603
    ENTRY_AGENT = entry_agent
    SPECIALISTS = list(specialists or ["ShoppingConcierge", "PersonalStylist", "PostSale"])
