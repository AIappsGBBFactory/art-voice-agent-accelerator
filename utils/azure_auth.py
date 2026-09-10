# src/utils/azure_auth.py
import logging
import os
from functools import lru_cache
from typing import Any

from azure.core.credentials import AccessToken, AccessTokenInfo, TokenRequestOptions
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
from azure.identity.aio import AzureCliCredential as AsyncAzureCliCredential

logging.getLogger("azure.identity").setLevel(logging.WARNING)

# Timeout for credential acquisition (prevents hanging on auth failures)
_CREDENTIAL_TIMEOUT_SEC = float(os.getenv("AZURE_CREDENTIAL_TIMEOUT_SEC", "10.0"))


def _pinned_cli_options(options: dict[str, Any], expected_tenant: str) -> dict[str, Any]:
    """Honor a resource's tenant challenge without passing conflicting CLI flags."""
    cleaned = dict(options)
    requested_tenant = cleaned.pop("tenant_id", None)
    if requested_tenant and (
        not expected_tenant or requested_tenant.lower() != expected_tenant.lower()
    ):
        raise ClientAuthenticationError(
            "The resource tenant does not match the tenant configured for the pinned Azure login."
        )
    return cleaned


class SubscriptionPinnedAzureCliCredential(AzureCliCredential):
    """Keep the selected CLI account when SDKs repeat the configured tenant in a challenge.

    Azure CLI rejects --subscription plus --tenant. Only a challenge matching the
    configured tenant is redundant; a different tenant is explicitly rejected.
    """

    def __init__(self, *, expected_tenant: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._expected_tenant = expected_tenant

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return super().get_token(*scopes, **_pinned_cli_options(kwargs, self._expected_tenant))

    def get_token_info(
        self, *scopes: str, options: TokenRequestOptions | None = None
    ) -> AccessTokenInfo:
        return super().get_token_info(
            *scopes, options=_pinned_cli_options(options or {}, self._expected_tenant)
        )


class AsyncSubscriptionPinnedAzureCliCredential(AsyncAzureCliCredential):
    """Async counterpart using the same account and tenant-challenge checks."""

    def __init__(self, *, expected_tenant: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._expected_tenant = expected_tenant

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return await super().get_token(
            *scopes, **_pinned_cli_options(kwargs, self._expected_tenant)
        )

    async def get_token_info(
        self, *scopes: str, options: TokenRequestOptions | None = None
    ) -> AccessTokenInfo:
        return await super().get_token_info(
            *scopes, options=_pinned_cli_options(options or {}, self._expected_tenant)
        )


def _using_managed_identity() -> bool:
    """Check if running with Managed Identity (Azure hosted environment)."""
    if os.getenv("MSI_ENDPOINT") or os.getenv("IDENTITY_ENDPOINT"):
        return True

    return bool(os.getenv("AZURE_CLIENT_ID") and _is_azure_hosted())


def _is_azure_hosted() -> bool:
    """Return True when Azure hosting environment markers are present."""
    return bool(
        os.getenv("WEBSITE_SITE_NAME")  # App Service
        or os.getenv("CONTAINER_APP_NAME")  # Container Apps
        or os.getenv("FUNCTIONS_WORKER_RUNTIME")  # Functions
        or os.getenv("IDENTITY_ENDPOINT")
        or os.getenv("MSI_ENDPOINT")
    )


def _environment_credential_broken() -> bool:
    """True when EnvironmentCredential would fail due to a partial config.

    GitHub Actions OIDC sets ``AZURE_CLIENT_ID`` (and ``AZURE_TENANT_ID``) so
    ``az login`` can federate, but provides no ``AZURE_CLIENT_SECRET``.
    ``DefaultAzureCredential`` tries ``EnvironmentCredential`` first, which then
    raises "secret should be a Microsoft Entra application's client secret".
    Detect that case so callers can exclude EnvironmentCredential and fall
    through to ``AzureCliCredential``.
    """
    return bool(os.getenv("AZURE_CLIENT_ID")) and not os.getenv("AZURE_CLIENT_SECRET")


def _is_local_dev() -> bool:
    """
    Check if running in local development mode.

    Detection priority:
    1. ENVIRONMENT env var: "dev", "development", "local" = local dev
    2. Azure hosting signals: WEBSITE_SITE_NAME, CONTAINER_APP_NAME = production
    3. Default: assume local dev if no signals present
    """
    env = os.getenv("ENVIRONMENT", "").lower()

    if env in ("dev", "development", "local"):
        return True

    if env in ("prod", "production", "staging"):
        return not _is_azure_hosted()

    return not _is_azure_hosted()


def _create_credential_internal():
    """
    Internal credential creation - not cached.

    Returns the appropriate credential based on environment.
    """
    if _using_managed_identity():
        return ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))

    # For local development, allow CLI credential (from `az login`)
    if _is_local_dev():
        cli_options = get_local_cli_credential_options()
        if cli_options:
            return SubscriptionPinnedAzureCliCredential(**cli_options)
        return DefaultAzureCredential(
            exclude_environment_credential=_environment_credential_broken(),
            exclude_managed_identity_credential=True,  # Not available locally
            exclude_workload_identity_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_cli_credential=False,  # Allow CLI for local dev
            exclude_powershell_credential=True,
            exclude_interactive_browser_credential=True,
        )

    # "prod-safe" DAC (only env + MI)
    return DefaultAzureCredential(
        exclude_environment_credential=_environment_credential_broken(),
        exclude_managed_identity_credential=False,
        exclude_workload_identity_credential=True,
        exclude_shared_token_cache_credential=True,
        exclude_visual_studio_code_credential=True,
        exclude_cli_credential=True,
        exclude_powershell_credential=True,
        exclude_interactive_browser_credential=True,
    )


def get_local_cli_credential_options() -> dict[str, Any]:
    """Pin local authentication to an explicit CLI account without changing CLI defaults."""
    subscription = os.getenv("AZURE_AUTH_SUBSCRIPTION", "").strip()
    if not subscription:
        return {}
    # Azure CLI accepts subscription OR tenant; the selected subscription pins both account and tenant.
    return {
        "subscription": subscription,
        "expected_tenant": os.getenv("AZURE_TENANT_ID", "").strip(),
        "process_timeout": _CREDENTIAL_TIMEOUT_SEC,
    }


def should_use_managed_identity_for_acs() -> bool:
    """Return whether ACS clients should prefer managed identity auth."""
    override = os.getenv("ACS_USE_MANAGED_IDENTITY", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return _using_managed_identity()


@lru_cache(maxsize=1)
def get_credential():
    """
    Get Azure credential based on environment.

    - Managed Identity: Used when AZURE_CLIENT_ID/MSI_ENDPOINT/IDENTITY_ENDPOINT is set
    - Local Dev: Uses CLI credential (requires `az login`)
    - Production: Uses only environment + managed identity credentials

    Note: Credential creation is fast, but token acquisition (which happens
    on first use) can be slow. The credential object is cached for reuse.
    """
    return _create_credential_internal()
