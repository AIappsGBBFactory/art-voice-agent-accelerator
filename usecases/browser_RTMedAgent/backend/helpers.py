"""
helpers.py

This module provides utility functions for the browser_RTMedAgent backend. 

"""
from usecases.browser_RTMedAgent.backend.settings import STOP_WORDS


def check_for_stopwords(prompt: str) -> bool:
    """Return ``True`` iff the message contains an exit keyword."""
    return any(stop in prompt.lower() for stop in STOP_WORDS)


def check_for_interrupt(prompt: str) -> bool:
    """Return ``True`` iff the message is an interrupt control frame."""
    return "interrupt" in prompt.lower()


def add_space(text: str) -> str:
    """
    Ensure the chunk ends with a single space or newline.

    This prevents “...assistance.Could” from appearing when we flush on '.'.
    """
    if text and text[-1] not in [" ", "\n"]:
        return text + " "
    return text
