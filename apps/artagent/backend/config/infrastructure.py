"""
Infrastructure Configuration (DEPRECATED)
=========================================

This file is deprecated. Import from config or config.settings instead.
"""

from .settings import (
    # Azure Identity
    AZURE_CLIENT_ID,
    AZURE_TENANT_ID,
    BACKEND_AUTH_CLIENT_ID,
    ALLOWED_CLIENT_IDS,
    ENTRA_JWKS_URL,
    ENTRA_ISSUER,
    ENTRA_AUDIENCE,
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_CHAT_DEPLOYMENT_ID,
    # Azure Speech
    AZURE_SPEECH_REGION,
    AZURE_SPEECH_ENDPOINT,
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_RESOURCE_ID,
    # Azure ACS
    ACS_ENDPOINT,
    ACS_CONNECTION_STRING,
    ACS_SOURCE_PHONE_NUMBER,
    BASE_URL,
    ACS_STREAMING_MODE,
    ACS_JWKS_URL,
    ACS_ISSUER,
    ACS_AUDIENCE,
    # Azure Storage
    AZURE_STORAGE_CONTAINER_URL,
    AZURE_COSMOS_CONNECTION_STRING,
    AZURE_COSMOS_DATABASE_NAME,
    AZURE_COSMOS_COLLECTION_NAME,
)
