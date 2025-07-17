"""
services/openai_client.py
-------------------------
Single shared Azure OpenAI client.  Import `client` anywhere you need
to talk to the Chat Completion API; it will be created once at
import-time.
"""

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from rtagents.RTInsuranceAgent.backend.settings import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)

# Use DefaultAzureCredential when API key is not provided
if AZURE_OPENAI_KEY:
    client = AzureOpenAI(
        api_version="2025-01-01-preview",
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
    )
else:
    credential = DefaultAzureCredential()
    azure_ad_token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        api_version="2025-01-01-preview",
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=azure_ad_token_provider,
    )

__all__ = ["client"]
