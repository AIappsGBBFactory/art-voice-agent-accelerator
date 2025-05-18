"""
conversation_state.py

This module defines the ConversationManager class, which manages the conversation history and context for a voice agent application. It handles initialization of conversation state, selection of system prompts based on authentication, and maintains a chat history for interactions.

"""

import uuid
from typing import Any, Dict, List

from usecases.browser_RTMedAgent.backend.prompt_manager import PromptManager


class ConversationManager:
    """
    Manages conversation history and context for the voice agent.

    Attributes
    ----------
    pm : PromptManager
        Prompt factory.
    cid : str
        Short conversation ID.
    hist : List[Dict[str, Any]]
        OpenAI chat history.
    """

    def __init__(self, auth: bool = True) -> None:
        self.pm: PromptManager = PromptManager()
        self.cid: str = str(uuid.uuid4())[:8]
        prompt_key: str = (
            "voice_agent_authentication.jinja" if auth else "voice_agent_system.jinja"
        )
        if auth:
            # TODO: add dynamic prompt once patient metadata is supported
            system_prompt: str = self.pm.get_prompt(prompt_key)
        else:
            system_prompt: str = self.pm.create_prompt_system_main()

        self.hist: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
