from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from utils import azure_auth


def local_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    for key in (
        "MSI_ENDPOINT",
        "IDENTITY_ENDPOINT",
        "WEBSITE_SITE_NAME",
        "CONTAINER_APP_NAME",
        "FUNCTIONS_WORKER_RUNTIME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AZURE_TENANT_ID", "configured-tenant")
    monkeypatch.setenv("AZURE_AUTH_SUBSCRIPTION", "configured-account-subscription")


def test_local_auth_pins_account_without_mutating_cli_or_combining_tenant_flags(monkeypatch):
    local_environment(monkeypatch)
    cli = Mock()
    fallback = Mock()
    monkeypatch.setattr(azure_auth, "SubscriptionPinnedAzureCliCredential", cli)
    monkeypatch.setattr(azure_auth, "DefaultAzureCredential", fallback)
    assert azure_auth._create_credential_internal() is cli.return_value
    assert cli.call_args.kwargs["subscription"] == "configured-account-subscription"
    assert "tenant_id" not in cli.call_args.kwargs
    fallback.assert_not_called()


def test_no_pin_preserves_existing_local_credential_behavior(monkeypatch):
    local_environment(monkeypatch)
    monkeypatch.delenv("AZURE_AUTH_SUBSCRIPTION")
    fallback = Mock()
    monkeypatch.setattr(azure_auth, "DefaultAzureCredential", fallback)
    assert azure_auth._create_credential_internal() is fallback.return_value
    assert fallback.call_args.kwargs["exclude_managed_identity_credential"] is True


def test_hosted_managed_identity_ignores_local_account_pin(monkeypatch):
    local_environment(monkeypatch)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://managed-identity")
    monkeypatch.setenv("AZURE_CLIENT_ID", "managed-client")
    managed = Mock()
    cli = Mock()
    monkeypatch.setattr(azure_auth, "ManagedIdentityCredential", managed)
    monkeypatch.setattr(azure_auth, "SubscriptionPinnedAzureCliCredential", cli)
    assert azure_auth._create_credential_internal() is managed.return_value
    managed.assert_called_once_with(client_id="managed-client")
    cli.assert_not_called()


@pytest.mark.asyncio
async def test_voicelive_uses_the_same_pinned_local_account(monkeypatch):
    from apps.artagent.backend.voice.voicelive import handler

    local_environment(monkeypatch)
    cli = Mock()
    monkeypatch.setattr(handler, "AsyncSubscriptionPinnedAzureCliCredential", cli)
    monkeypatch.setattr(handler, "_CACHED_CREDENTIAL", None)
    credential = await handler.VoiceLiveSDKHandler._build_credential(
        SimpleNamespace(has_api_key_auth=False, azure_client_id=None)
    )
    assert credential is cli.return_value
    assert cli.call_args.kwargs["subscription"] == "configured-account-subscription"
    assert "tenant_id" not in cli.call_args.kwargs


def test_matching_tenant_challenge_keeps_claims_and_never_changes_account():
    options = {"tenant_id": "configured-tenant", "enable_cae": False, "claims": "challenge"}
    assert azure_auth._pinned_cli_options(options, "configured-tenant") == {
        "enable_cae": False,
        "claims": "challenge",
    }
    assert options["tenant_id"] == "configured-tenant"


def test_pinned_account_rejects_an_unexpected_tenant_challenge():
    with pytest.raises(azure_auth.ClientAuthenticationError, match="does not match"):
        azure_auth._pinned_cli_options({"tenant_id": "different-tenant"}, "configured-tenant")
