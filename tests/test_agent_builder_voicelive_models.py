"""
Voice Live Model Listing Source
===============================

The builder's model dropdowns must list deployments from the resource that
actually serves the selected orchestration mode:

    cascade   -> AZURE_OPENAI_ENDPOINT      (primary AI Foundry / AOAI account)
    voicelive -> AZURE_VOICELIVE_ENDPOINT   (the Voice Live "AVL" account)

Voice Live is frequently provisioned as a SEPARATE account in a different region
with its own (much smaller) deployment set. Listing the primary account's
deployments for the VoiceLive dropdown lets a user pick a model Voice Live can't
reach: the WebSocket connects, the model never responds, and the session dies on
the ~900s idle timeout. These tests pin that split.
"""

from __future__ import annotations

import pytest

from apps.artagent.backend.api.v1.endpoints import agent_builder as ab

AOAI_ENDPOINT = "https://contoso-aif.openai.azure.com/"
VOICELIVE_ENDPOINT = "https://contoso-avl.cognitiveservices.azure.com/"


@pytest.fixture(autouse=True)
def _clear_models_cache():
    """The /models cache is process-wide; isolate each test."""
    ab._AVAILABLE_MODELS_CACHE.clear()
    yield
    ab._AVAILABLE_MODELS_CACHE.clear()


@pytest.fixture
def split_resources(monkeypatch):
    """Configure distinct AOAI and Voice Live accounts."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_OPENAI_KEY", "aoai-key")
    monkeypatch.setenv("AZURE_VOICELIVE_ENDPOINT", VOICELIVE_ENDPOINT)
    monkeypatch.setenv("AZURE_VOICELIVE_API_KEY", "avl-key")


# =============================================================================
# ENDPOINT NORMALIZATION
# =============================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://x.cognitiveservices.azure.com/", "https://x.cognitiveservices.azure.com"),
        # The Voice Live SDK endpoint may be given as a websocket URL...
        ("wss://x.cognitiveservices.azure.com", "https://x.cognitiveservices.azure.com"),
        # ...and/or carry the realtime path + query.
        (
            "wss://x.services.ai.azure.com/voice-live/realtime?api-version=2025-10-01",
            "https://x.services.ai.azure.com",
        ),
        ("x.openai.azure.com", "https://x.openai.azure.com"),
        ("", ""),
    ],
)
def test_normalize_control_plane_endpoint(raw, expected):
    assert ab._normalize_control_plane_endpoint(raw) == expected


# =============================================================================
# SOURCE RESOLUTION
# =============================================================================


def test_cascade_resolves_to_primary_foundry(split_resources):
    source = ab._resolve_deployment_source("cascade")
    assert source["endpoint"] == AOAI_ENDPOINT.rstrip("/")
    assert source["api_key"] == "aoai-key"
    assert source["restrict_modes"] is None
    assert source["fell_back"] is False


def test_voicelive_resolves_to_voice_live_resource(split_resources):
    source = ab._resolve_deployment_source("voicelive")
    assert source["endpoint"] == VOICELIVE_ENDPOINT.rstrip("/")
    assert source["api_key"] == "avl-key"
    assert source["restrict_modes"] == ["voicelive"]
    assert source["fell_back"] is False
    assert source["resource_name"] == "contoso-avl"


def test_voicelive_does_not_borrow_the_aoai_key_for_a_different_account(
    split_resources, monkeypatch
):
    """A key is scoped to its account — reusing it would 401 against the AVL one."""
    monkeypatch.delenv("AZURE_VOICELIVE_API_KEY", raising=False)
    source = ab._resolve_deployment_source("voicelive")
    assert source["api_key"] is None  # falls through to Entra credential


def test_voicelive_reuses_the_aoai_key_when_both_point_at_one_account(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_OPENAI_KEY", "shared-key")
    monkeypatch.setenv("AZURE_VOICELIVE_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.delenv("AZURE_VOICELIVE_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_VOICE_API_KEY", raising=False)
    source = ab._resolve_deployment_source("voicelive")
    assert source["api_key"] == "shared-key"


def test_voicelive_falls_back_to_primary_when_not_provisioned(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.delenv("AZURE_VOICELIVE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_VOICE_LIVE_ENDPOINT", raising=False)
    source = ab._resolve_deployment_source("voicelive")
    assert source["endpoint"] == AOAI_ENDPOINT.rstrip("/")
    assert source["fell_back"] is True


# =============================================================================
# /models ENDPOINT
# =============================================================================


@pytest.mark.asyncio
async def test_models_endpoint_queries_the_voice_live_resource(split_resources, monkeypatch):
    """mode=voicelive must hit the AVL account, not the primary Foundry one."""
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(endpoint=None, api_key=None):
        calls.append((endpoint, api_key))
        return {
            "deployments": [{"deployment_id": "gpt-realtime", "model_name": "gpt-realtime"}],
            "region": "Sweden Central",
        }

    monkeypatch.setattr(ab, "_fetch_real_deployments", fake_fetch)

    result = await ab.list_available_models(mode="voicelive")

    assert calls == [(VOICELIVE_ENDPOINT.rstrip("/"), "avl-key")]
    assert result["mode"] == "voicelive"
    assert result["resource_name"] == "contoso-avl"
    assert [m["deployment_id"] for m in result["models"]] == ["gpt-realtime"]
    # A VoiceLive-sourced listing may only advertise the voicelive mode.
    assert result["models"][0]["modes"] == ["voicelive"]


@pytest.mark.asyncio
async def test_models_endpoint_defaults_to_the_primary_resource(split_resources, monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(endpoint=None, api_key=None):
        calls.append((endpoint, api_key))
        return {
            "deployments": [{"deployment_id": "gpt-4o", "model_name": "gpt-4o"}],
            "region": "North Central US",
        }

    monkeypatch.setattr(ab, "_fetch_real_deployments", fake_fetch)

    result = await ab.list_available_models()

    assert calls == [(AOAI_ENDPOINT.rstrip("/"), "aoai-key")]
    assert result["mode"] == "cascade"
    assert result["models"][0]["modes"] == ["cascade", "voicelive"]


@pytest.mark.asyncio
async def test_voicelive_never_falls_back_to_the_primary_catalog(split_resources, monkeypatch):
    """An empty AVL listing returns [] rather than the primary account's models.

    Surfacing primary-resource models here is precisely the misrepresentation
    that makes the agent go silent; the UI falls back to the managed Voice Live
    catalog instead.
    """
    monkeypatch.setattr(ab, "_fetch_real_deployments", lambda endpoint=None, api_key=None: None)

    result = await ab.list_available_models(mode="voicelive")

    assert result["models"] == []
    assert result["source"] == "unavailable"


@pytest.mark.asyncio
async def test_models_cache_is_per_mode(split_resources, monkeypatch):
    """Both modes read different resources, so they can't share one cache slot."""
    payloads = {
        VOICELIVE_ENDPOINT.rstrip("/"): {
            "deployments": [{"deployment_id": "gpt-realtime"}],
            "region": "Sweden Central",
        },
        AOAI_ENDPOINT.rstrip("/"): {
            "deployments": [{"deployment_id": "gpt-4o"}],
            "region": "North Central US",
        },
    }
    monkeypatch.setattr(
        ab, "_fetch_real_deployments", lambda endpoint=None, api_key=None: payloads[endpoint]
    )

    vl = await ab.list_available_models(mode="voicelive")
    cascade = await ab.list_available_models()
    vl_cached = await ab.list_available_models(mode="voicelive")

    assert [m["deployment_id"] for m in vl["models"]] == ["gpt-realtime"]
    assert [m["deployment_id"] for m in cascade["models"]] == ["gpt-4o"]
    assert vl_cached["cached"] is True
    assert [m["deployment_id"] for m in vl_cached["models"]] == ["gpt-realtime"]


# =============================================================================
# REGION ATTRIBUTION
# =============================================================================
# Voice Live is only offered in a subset of regions, so the AVL account is
# routinely provisioned far from both the primary Foundry account and the app
# itself. In the reference deployment the backend runs in westus2, Cascade in
# northcentralus and Voice Live in swedencentral — a trans-Atlantic hop paid on
# the realtime audio path. The builder has to be able to say so, which means
# every model list must carry the region of the resource that produced it.


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The two shapes Azure reports: x-ms-region display form vs config slug.
        ("Sweden Central", "swedencentral"),
        ("swedencentral", "swedencentral"),
        ("North Central US", "northcentralus"),
        ("West-US-2", "westus2"),
        ("  westus2  ", "westus2"),
        ("", ""),
        (None, ""),
    ],
)
def test_region_key_canonicalizes_both_azure_spellings(raw, expected):
    """Display form and slug form must compare equal, or identical regions
    would render as a cross-region hop."""
    assert ab._region_key(raw) == expected


@pytest.mark.parametrize(
    "dns_suffix,expected",
    [
        ("calmstone-28851c8c.westus2.azurecontainerapps.io", "westus2"),
        ("Gentle-Rock-1234.northeurope.azurecontainerapps.io", "northeurope"),
        # A custom environment DNS suffix no longer encodes the region, so
        # parsing it would invent one.
        ("apps.contoso.com", ""),
        ("", ""),
    ],
)
def test_app_region_reads_the_container_apps_dns_suffix(monkeypatch, dns_suffix, expected):
    monkeypatch.delenv("AZURE_LOCATION", raising=False)
    monkeypatch.setenv("CONTAINER_APP_ENV_DNS_SUFFIX", dns_suffix)
    assert ab._app_region() == expected


def test_app_region_falls_back_to_azure_location_off_container_apps(monkeypatch):
    monkeypatch.delenv("CONTAINER_APP_ENV_DNS_SUFFIX", raising=False)
    monkeypatch.setenv("AZURE_LOCATION", "westus2")
    assert ab._app_region() == "westus2"


def test_app_region_is_empty_when_undeterminable(monkeypatch):
    """Unknown must stay unknown — the UI hides the comparison rather than guess."""
    monkeypatch.delenv("CONTAINER_APP_ENV_DNS_SUFFIX", raising=False)
    monkeypatch.delenv("AZURE_LOCATION", raising=False)
    assert ab._app_region() == ""


def test_cascade_region_hint_uses_speech_region_for_the_same_account(monkeypatch):
    """Speech and Azure OpenAI are two endpoints on one AI Foundry account here,
    so the Speech region does describe the model list's resource."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://contoso-aif.openai.azure.com/")
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", "https://contoso-aif.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "northcentralus")
    monkeypatch.delenv("AZURE_OPENAI_REGION", raising=False)
    assert ab._resolve_deployment_source("cascade")["region_hint"] == "northcentralus"


def test_cascade_region_hint_ignores_speech_region_from_another_account(monkeypatch):
    """A standalone Speech resource describes a different resource entirely;
    borrowing its region would mis-attribute the model list."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", "https://contoso-speech.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")
    monkeypatch.delenv("AZURE_OPENAI_REGION", raising=False)
    assert ab._resolve_deployment_source("cascade")["region_hint"] == ""


def test_voicelive_region_hint_comes_from_its_own_override(split_resources, monkeypatch):
    monkeypatch.setenv("AZURE_VOICELIVE_REGION", "swedencentral")
    assert ab._resolve_deployment_source("voicelive")["region_hint"] == "swedencentral"


def test_voicelive_does_not_inherit_the_primary_region_for_a_separate_account(
    split_resources, monkeypatch
):
    """The AVL account is the one that is usually somewhere else entirely — the
    primary account's region must never stand in for it."""
    monkeypatch.delenv("AZURE_VOICELIVE_REGION", raising=False)
    monkeypatch.delenv("AZURE_VOICE_LIVE_REGION", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_SPEECH_REGION", "northcentralus")
    assert ab._resolve_deployment_source("voicelive")["region_hint"] == ""


def test_voicelive_inherits_the_primary_region_when_it_shares_the_account(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", AOAI_ENDPOINT)
    monkeypatch.setenv("AZURE_SPEECH_REGION", "northcentralus")
    monkeypatch.delenv("AZURE_VOICELIVE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_VOICE_LIVE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_VOICELIVE_REGION", raising=False)
    source = ab._resolve_deployment_source("voicelive")
    assert source["fell_back"] is True
    assert source["region_hint"] == "northcentralus"


def test_fetch_real_deployments_reports_the_region_header(monkeypatch):
    """x-ms-region is the only region signal that needs no extra call, no
    management-plane permission and no new configuration."""
    import httpx

    class _Resp:
        status_code = 200
        headers = {"x-ms-region": "Sweden Central"}

        @staticmethod
        def json():
            return {"data": [{"id": "gpt-realtime", "model": {"name": "gpt-realtime"}}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())

    result = ab._fetch_real_deployments(VOICELIVE_ENDPOINT.rstrip("/"), "avl-key")

    assert result["region"] == "Sweden Central"
    assert [d["deployment_id"] for d in result["deployments"]] == ["gpt-realtime"]


def test_fetch_real_deployments_tolerates_a_missing_region_header(monkeypatch):
    import httpx

    class _Resp:
        status_code = 200
        headers: dict[str, str] = {}

        @staticmethod
        def json():
            return {"data": [{"id": "gpt-4o"}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())

    assert ab._fetch_real_deployments(AOAI_ENDPOINT.rstrip("/"), "aoai-key")["region"] == ""


@pytest.mark.asyncio
async def test_models_payload_attributes_the_region_to_the_serving_resource(
    split_resources, monkeypatch
):
    monkeypatch.setenv("CONTAINER_APP_ENV_DNS_SUFFIX", "calmstone.westus2.azurecontainerapps.io")
    monkeypatch.setattr(
        ab,
        "_fetch_real_deployments",
        lambda endpoint=None, api_key=None: {
            "deployments": [{"deployment_id": "gpt-realtime"}],
            "region": "Sweden Central",
        },
    )

    result = await ab.list_available_models(mode="voicelive")

    assert result["resource_name"] == "contoso-avl"
    assert result["endpoint_host"] == "contoso-avl.cognitiveservices.azure.com"
    assert result["region"] == "Sweden Central"
    assert result["region_key"] == "swedencentral"
    assert result["region_source"] == "resource"
    assert result["app_region_key"] == "westus2"
    # The whole point: these differ, so the UI can warn about the hop.
    assert result["region_key"] != result["app_region_key"]


@pytest.mark.asyncio
async def test_models_payload_prefers_the_reported_region_over_configuration(
    split_resources, monkeypatch
):
    """Configuration records where a resource was REQUESTED; the header records
    where it is actually served from. Only the latter reflects reality."""
    monkeypatch.setenv("AZURE_VOICELIVE_REGION", "westeurope")
    monkeypatch.setattr(
        ab,
        "_fetch_real_deployments",
        lambda endpoint=None, api_key=None: {
            "deployments": [{"deployment_id": "gpt-realtime"}],
            "region": "Sweden Central",
        },
    )

    result = await ab.list_available_models(mode="voicelive")

    assert result["region"] == "Sweden Central"
    assert result["region_source"] == "resource"


@pytest.mark.asyncio
async def test_models_payload_falls_back_to_the_configured_region(split_resources, monkeypatch):
    """An unavailable listing still names the resource and its configured
    region, so the panel is never blind about where VoiceLive connects."""
    monkeypatch.setenv("AZURE_VOICELIVE_REGION", "swedencentral")
    monkeypatch.setattr(ab, "_fetch_real_deployments", lambda endpoint=None, api_key=None: None)

    result = await ab.list_available_models(mode="voicelive")

    assert result["models"] == []
    assert result["source"] == "unavailable"
    assert result["region"] == "swedencentral"
    assert result["region_source"] == "config"
    assert result["resource_name"] == "contoso-avl"


@pytest.mark.asyncio
async def test_models_payload_marks_region_unknown_rather_than_guessing(
    split_resources, monkeypatch
):
    monkeypatch.delenv("AZURE_VOICELIVE_REGION", raising=False)
    monkeypatch.delenv("AZURE_VOICE_LIVE_REGION", raising=False)
    monkeypatch.setattr(
        ab,
        "_fetch_real_deployments",
        lambda endpoint=None, api_key=None: {
            "deployments": [{"deployment_id": "gpt-realtime"}],
            "region": "",
        },
    )

    result = await ab.list_available_models(mode="voicelive")

    assert result["region"] == ""
    assert result["region_source"] == ""
