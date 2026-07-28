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
        return [{"deployment_id": "gpt-realtime", "model_name": "gpt-realtime"}]

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
        return [{"deployment_id": "gpt-4o", "model_name": "gpt-4o"}]

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
        VOICELIVE_ENDPOINT.rstrip("/"): [{"deployment_id": "gpt-realtime"}],
        AOAI_ENDPOINT.rstrip("/"): [{"deployment_id": "gpt-4o"}],
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
