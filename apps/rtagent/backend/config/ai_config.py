"""
AI and Model Configuration
===========================

Azure OpenAI, model parameters, and AI-related settings
for the real-time voice agent.
"""

import os

# ==============================================================================
# RETAIL AGENT CONFIGURATIONS
# ==============================================================================

# Retail agent configuration file paths
AGENT_SHOPPING_CONCIERGE_CONFIG = os.getenv(
    "AGENT_SHOPPING_CONCIERGE_CONFIG",
    "apps/rtagent/backend/src/agents/artagent/agent_store/shopping_concierge_agent.yaml"
)

AGENT_PERSONAL_STYLIST_CONFIG = os.getenv(
    "AGENT_PERSONAL_STYLIST_CONFIG",
    "apps/rtagent/backend/src/agents/artagent/agent_store/personal_stylist_agent.yaml",
)

AGENT_POSTSALE_CONFIG = os.getenv(
    "AGENT_POSTSALE_CONFIG",
    "apps/rtagent/backend/src/agents/artagent/agent_store/postsale_agent.yaml",
)

# ==============================================================================
# AZURE OPENAI SETTINGS
# ==============================================================================

# Model behavior configuration
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "500"))

# Request timeout settings
AOAI_REQUEST_TIMEOUT = float(os.getenv("AOAI_REQUEST_TIMEOUT", "30.0"))
