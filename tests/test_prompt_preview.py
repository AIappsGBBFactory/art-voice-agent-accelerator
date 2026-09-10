"""Offline prompt-preview contracts, sandbox limits, isolation, and redaction."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from apps.artagent.backend.api.v1.endpoints.prompt_preview import router
from apps.artagent.backend.api.v1.schemas.prompt_preview import (
    MAX_PREVIEW_REQUEST_BYTES,
    PromptPreviewRequest,
)
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.registries.scenariostore.loader import (
    AgentOverride,
    ScenarioConfig,
)
from apps.artagent.backend.src.orchestration import session_agents, session_scenarios
from apps.artagent.backend.src.orchestration.session_drafts import SessionAuthoringSnapshot
from apps.artagent.backend.src.services.prompt_preview import _render_snapshot
from apps.artagent.backend.src.services.prompt_sandbox import render_prompt_preview
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Template
from src.stateful.state_managment import MemoManager


def request_data(prompt: str = "Hello {{ caller_name | default('there') }}", **changes) -> dict:
    """The complete frontend wire contract, including empty draft overrides."""
    return {
        "prompt": prompt,
        "agent_name": "Draft",
        "template_vars": {},
        "tools": [],
        "scenario": None,
        "mode": "cascade",
        **changes,
    }


def preview(
    prompt: str, *, memory: dict | None = None, live=None, saved=None, state=None, **changes
):
    memo = MemoManager(session_id="preview-test")
    memo.context.update(memory or {})
    snapshot = SessionAuthoringSnapshot(memo, {}, {}, {})
    body = PromptPreviewRequest.model_validate(request_data(prompt, **changes))
    return _render_snapshot(
        body, snapshot, saved_agent=saved, app_state=state or SimpleNamespace(), live=live
    )


@pytest.mark.parametrize(
    "prompt,context",
    [
        ("", {}),
        ("# Hello {{ caller_name }}\n\n**Markdown**", {"caller_name": "Avery"}),
        ("{{ unknown | default('not supplied') }}", {}),
        ("{% if unknown %}yes{% else %}no{% endif %}", {}),
        ("{{ profile.nickname | default('none') }}", {"profile": {}}),
        (
            "{{ profile['display-name'] }} {{ profile['items'] }}",
            {"profile": {"display-name": "Avery", "items": 0}},
        ),
        ("{{ value }} {{ value | default('fallback') }}", {"value": None}),
        ("{{ value | default('fallback', true) }}", {"value": False}),
        ("{% set n = value * 100 %}{{ n | round(0) }}", {"value": 0.2}),
        ("{{ '{:,.2f}'.format(balance) }}", {"balance": 1234.5}),
        ("{{ profile.full_name.split()[0] }}", {"profile": {"full_name": "Avery Lee"}}),
        ("{{ profile.get('missing', 'fallback') }}", {"profile": {}}),
        ("{{ profile.get('missing') or 'fallback' }}", {"profile": {}}),
        (
            "{% for k, v in profile.items() %}{{ k }}={{ v }};{% endfor %}",
            {"profile": {"a": 0, "b": False}},
        ),
        (
            "{% set accounts = profile.accounts | default([]) %}"
            "{% for account in accounts if account.active %}"
            "{{ loop.index }}: {{ account.get('name', 'unnamed') }}"
            "{% else %}none{% endfor %}",
            {"profile": {"accounts": [{"active": True, "name": "Primary"}, {"active": False}]}},
        ),
        (
            "{% if profile is mapping %}{{ profile.name | upper }}{% endif %}",
            {"profile": {"name": "Avery"}},
        ),
        ("{{ values | join(', ') }}", {"values": [1, 2, 3]}),
        ("{{ profile | tojson }}", {"profile": {"name": "<Avery>", "ok": False}}),
        ("{% for value in rows[:2] %}{{ value }}{% endfor %}", {"rows": [1, 2, 3]}),
    ],
)
def test_safe_jinja_matches_normal_runtime(prompt, context):
    result = render_prompt_preview(prompt, context)
    assert result.errors == []
    assert result.missing == []
    assert result.rendered == Template(prompt).render(**context)


def test_undefined_output_is_not_a_success_shaped_raw_template():
    result = render_prompt_preview("{{ missing }} / {{ profile.unknown }}", {"profile": {}})
    assert result.rendered is None
    assert result.missing == ["missing", "profile.unknown"]
    assert {error.kind for error in result.errors} == {"undefined"}


@pytest.mark.parametrize(
    "path",
    sorted(Path("apps/artagent/backend/registries/agentstore").glob("*/prompt.jinja")),
    ids=lambda path: path.parent.name,
)
def test_shipped_templates_support_the_preview_syntax_subset(path):
    result = render_prompt_preview(
        path.read_text(),
        {
            "agent_name": "Test agent",
            "institution_name": "Test institution",
            "session_profile": {},
            "customer_intelligence": {},
            "handoff_context": {},
            "caller_name": "Test caller",
            "client_id": "test-client",
        },
    )
    # Unavailable business fields are legitimate diagnostics, not rejected Jinja syntax.
    assert all(error.kind == "undefined" for error in result.errors)


def test_default_does_not_make_a_missing_parent_chainable():
    result = render_prompt_preview("{{ missing.child | default('fallback') }}", {})
    assert result.rendered is None
    assert result.missing == ["missing"]


def test_unfinished_template_retains_context_and_line_number():
    result = preview("Hello\n{% if caller_name", memory={"caller_name": "Avery"})
    assert result.rendered_prompt is None
    assert result.errors[0].kind == "syntax"
    assert result.errors[0].line == 2
    row = next(item for item in result.variables if item.path == "caller_name")
    assert row.available and row.value_preview == '"Avery"'


@pytest.mark.parametrize(
    "prompt",
    [
        "{% include 'secret.txt' %}",
        "{% extends 'secret.txt' %}",
        "{% import 'secret.txt' as secret %}",
        "{% from 'secret.txt' import secret %}",
        "{% macro repeat() %}{{ repeat() }}{% endmacro %}{{ repeat() }}",
        "{% for x in rows recursive %}{{ loop(rows) }}{% endfor %}",
        "{{ range(1000000000) }}",
        "{{ lipsum() }}",
        "{{ cycler.__init__.__globals__ }}",
        "{{ profile.__class__ }}",
        "{{ profile['__class__'] }}",
        "{{ profile.get(private_key) }}",
        "{{ profile.clear() }}",
        "{{ profile | attr('name') }}",
        "{{ '{0.__class__}'.format(1) }}",
        "{{ '{:1000000000}'.format(1) }}",
        "{{ 'x' * 1000000000 }}",
        "{{ 10 ** 1000000000 }}",
        "{% set profile.name = 'mutated' %}",
        "{% filter upper %}no blocks{% endfilter %}",
    ],
)
def test_unsafe_templates_have_explicit_nonleaking_diagnostics(prompt):
    context = {"profile": {"name": "Avery"}, "rows": [1], "private_key": "__class__"}
    before = copy.deepcopy(context)
    result = render_prompt_preview(prompt, context)
    assert result.rendered is None
    assert result.errors and result.errors[0].kind == "unsafe"
    assert context == before
    assert "secret.txt" not in str(result.errors)


@pytest.mark.parametrize(
    "prompt,context",
    [
        (
            "{% for a in rows %}{% for b in rows %}{% endfor %}{% endfor %}",
            {"rows": list(range(50))},
        ),
        ("{{ text }}" * 20, {"text": "x" * 8000}),
        ("{{ values | join(separator) }}", {"values": ["x", "y", "z"], "separator": "x" * 80_000}),
        ("{{ text | replace('x', replacement) }}", {"text": "x" * 1000, "replacement": "y" * 1000}),
        (
            "{% set value = [1] %}{% for row in rows %}{% set value = [value, value] %}{{ value }}{% endfor %}",
            {"rows": list(range(1001))},
        ),
        ("{{ " + "(" * 80 + "1" + ")" * 80 + " }}", {}),
        ("{{ profile | tojson(indent=1000000) }}", {"profile": {"name": "Avery"}}),
        ("{{ 1.25 | round(1000000, 'ceil') }}", {}),
    ],
)
def test_size_and_work_limits_are_deterministic(prompt, context):
    result = render_prompt_preview(prompt, context)
    assert result.rendered is None
    assert result.errors and result.errors[0].kind == "limit"


def test_nested_paths_are_insertable_and_match_runtime():
    context = {
        "session_profile": {
            "contact-info": {"display name": "Avery"},
            "items": ["first", {"enabled": False}],
            "none": None,
        }
    }
    result = preview("Hello", memory=context)
    rows = {row.path: row for row in result.variables}
    assert rows['session_profile["contact-info"]["display name"]'].available
    assert rows['session_profile["items"][1].enabled'].value_preview == "false"
    for row in result.variables:
        if row.available and row.source == "session context":
            assert render_prompt_preview(row.expression, context).errors == []
    assert rows["session_profile.none"].available
    assert rows["session_profile.none"].type == "null"


def test_draft_scenario_overrides_authoring_not_live_runtime():
    result = preview(
        "{{ caller_name }}|{{ institution_name }}|{{ custom }}|{{ only_draft }}|{{ tools | default('unbound') }}",
        template_vars={
            "caller_name": "Draft caller",
            "institution_name": "Draft institution",
            "custom": "agent",
            "only_draft": 0,
        },
        tools=["unsaved_tool"],
        scenario={
            "name": "New scenario",
            "global_template_vars": {
                "custom": "global",
                "institution_name": "Scenario institution",
            },
            "agent_defaults": {"template_vars": {"custom": "scenario agent default"}},
        },
        memory={"caller_name": "Real caller", "institution_name": "Real institution"},
    )
    assert result.errors == []
    assert result.rendered_prompt == "Real caller|Real institution|scenario agent default|0|unbound"
    assert result.scenario_name == "New scenario"
    rows = {row.path: row for row in result.variables}
    assert rows["caller_name"].source == "session context"
    assert rows["custom"].source == "scenario agent defaults"
    assert rows["only_draft"].source == "agent template vars"
    assert not rows["tools"].available


def test_runtime_none_is_filtered_but_false_and_zero_are_not():
    result = preview(
        "{{ caller_name }}|{{ client_id }}|{{ previous_agent }}|{{ handoff_context.empty }}",
        template_vars={"caller_name": "default", "client_id": 99, "previous_agent": "default"},
        memory={
            "caller_name": None,
            "client_id": 0,
            "previous_agent": False,
            "handoff_context": {"empty": None},
        },
    )
    assert result.rendered_prompt == "default|0|False|None"
    result = preview(
        "{{ caller_name }}",
        template_vars={"caller_name": "default"},
        memory={"caller_name": "None"},
    )
    assert result.rendered_prompt == "default"


def test_no_sample_profile_or_unbound_history_alias_is_invented():
    result = preview(
        "{{ session_profile | default('absent') }}|{{ user_message_history | default('absent') }}",
        mode="voicelive",
        memory={"user_message_history": ["First question", "Follow-up"]},
    )
    assert result.errors == []
    assert result.rendered_prompt == "absent|absent"
    rows = {row.path: row for row in result.variables}
    assert not rows["session_profile"].available
    assert not rows["last_assistant_response"].available
    assert rows["recent_user_messages"].available
    assert rows["conversation_summary"].value_preview == '"First question → Follow-up"'
    assert not rows["user_message_history"].available


def test_credentials_and_codes_never_appear_in_any_response_field():
    result = preview(
        "{{ session_profile | tojson }} {{ caller_name | default('unavailable') }} "
        "{{ verification_code | default('unavailable') }} {{ 'vault-secret-value' | upper }}",
        memory={
            "caller_name": "Use vault-secret-value",
            "verification_code": 837261,
            "session_profile": {
                "name": "Avery",
                "apiKey": "vault-secret-value",
                "credentials": {"password": "nested-private-value"},
                "mfa": {"code": "555333"},
                "notes": "The code is 555333",
                "copy": "837261",
                "authorization": "Bearer private-token-value",
                "innocent_bearer_alias": "private-token-value",
                "connection_string": "Server=local;Password=connection-password-value",
                "innocent_password_alias": "connection-password-value",
            },
            "memo_manager": object(),
        },
    )
    encoded = result.model_dump_json()
    for secret in (
        "vault-secret-value",
        "nested-private-value",
        "837261",
        "555333",
        "private-token-value",
        "connection-password-value",
    ):
        assert secret.lower() not in encoded.lower()
    assert result.errors == []
    assert any(row.sensitive and not row.available for row in result.variables)
    assert all("memo_manager" not in row.path for row in result.variables)
    assert any("redacted" in warning for warning in result.warnings)


def test_live_python_objects_are_not_stringified_or_exposed():
    class InternalClient:
        def __str__(self):
            raise AssertionError("Client must not be stringified")

        def __repr__(self):
            raise AssertionError("Client must not be represented")

    result = preview(
        "{{ session_profile | tojson }}",
        memory={"session_profile": {"name": "Avery", "sdk": InternalClient()}},
    )
    assert result.errors == []
    assert result.rendered_prompt == '{"name": "Avery"}'
    assert not any(row.path.endswith(".sdk") for row in result.variables)


def test_oversized_context_is_explicit_and_never_rendered_partially():
    result = preview("{{ caller_name }}", memory={"caller_name": "x" * 130_000})
    assert result.rendered_prompt is None
    assert result.errors[0].kind == "limit"
    assert result.variables


def test_truncated_inventory_keeps_root_availability_truthful():
    result = preview(
        "{{ caller_name }}",
        memory={"caller_name": "Avery", "handoff_context": {"entries": list(range(600))}},
    )
    rows = {row.path: row for row in result.variables}
    assert result.errors == []
    assert result.rendered_prompt == "Avery"
    assert len(rows) <= 512
    assert rows["caller_name"].available
    assert rows["agent_name"].available
    assert any("512 paths" in warning for warning in result.warnings)


class ReadOnlyRedis:
    def __init__(self, sessions: dict[str, dict]) -> None:
        self.data = {
            f"session:{session_id}": {"corememory": json.dumps(memory)}
            for session_id, memory in sessions.items()
        }
        self.read_keys: list[str] = []

    def get_session_data(self, key: str) -> dict:
        self.read_keys.append(key)
        return copy.deepcopy(self.data.get(key, {}))

    def __getattr__(self, name: str):
        raise AssertionError(f"Preview must not use Redis operation {name}")


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(session_agents, "_session_agents", {})
    monkeypatch.setattr(session_scenarios, "_session_scenarios", {})
    monkeypatch.setattr(session_scenarios, "_active_scenario", {})
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/agent-builder")
    redis = ReadOnlyRedis(
        {"current": {"caller_name": "Current caller"}, "other": {"caller_name": "Other caller"}}
    )
    app.state.redis = redis
    return TestClient(app), redis


@pytest.mark.parametrize("mode", ["cascade", "voicelive"])
def test_endpoint_is_scoped_read_only_and_contract_exact(api, monkeypatch, mode):
    client, redis = api
    before = copy.deepcopy(redis.data)
    from apps.artagent.backend.src.services import prompt_preview as service

    discover = Mock(
        side_effect=AssertionError("Complete drafts do not require tool/catalog loading")
    )
    monkeypatch.setattr(service, "discover_agents", discover)
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current", json=request_data(mode=mode)
    )
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {
        "variables",
        "rendered_prompt",
        "errors",
        "missing_variables",
        "warnings",
        "mode",
        "scenario_name",
    }
    assert result["rendered_prompt"] == "Hello Current caller"
    assert "Other caller" not in response.text
    assert redis.read_keys == ["session:current"]
    assert redis.data == before
    assert session_agents._session_agents == {}
    assert session_scenarios._session_scenarios == {}
    discover.assert_not_called()


@pytest.mark.parametrize(
    "prompt,kind",
    [
        ("Hello\n{{", "syntax"),
        ("Hello\n{{ session_profile['__class__'] }}", "unsafe"),
        ("Hello\n{{ missing }}", "undefined"),
    ],
)
def test_endpoint_returns_metadata_with_editing_diagnostics(api, prompt, kind):
    client, _ = api
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current",
        json=request_data(prompt),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rendered_prompt"] is None
    assert data["errors"][0]["kind"] == kind
    assert data["errors"][0]["line"] == 2
    assert any(row["path"] == "caller_name" and row["available"] for row in data["variables"])


def test_credentials_in_overridden_layers_and_header_aliases_are_omitted():
    result = preview(
        "{{ public_copy | default('omitted') }}|{{ session_profile | tojson }}",
        template_vars={"password": "old-draft-secret", "public_copy": "old-draft-secret"},
        scenario={
            "name": "Draft scenario",
            "global_template_vars": {"password": "new-draft-secret"},
        },
        memory={
            "headers": {"Authorization": "Basic dXNlcjpwd2Q="},
            "session_profile": {"client": {"name": "Avery"}, "copy": "dXNlcjpwd2Q="},
        },
    )
    assert result.errors == []
    assert result.rendered_prompt == 'omitted|{"client": {"name": "Avery"}}'
    for secret in ("old-draft-secret", "new-draft-secret", "dXNlcjpwd2Q="):
        assert secret not in result.model_dump_json()


def test_embedded_verification_codes_and_signed_urls_are_not_context_values():
    result = preview(
        "{{ session_profile | tojson }}",
        memory={
            "session_profile": {
                "note": 'MFA code: "394827"',
                "code_copy": "394827",
                "public_code_copy": "394827",
                "storage_url": "https://example.invalid/file?sv=1&sig=sas-signature-value",
                "signature_copy": "sas-signature-value",
                "connection_string": "Endpoint=example.invalid;SharedAccessKey=shared-key-value",
                "key_copy": "shared-key-value",
                "name": "Avery",
            }
        },
    )
    assert result.rendered_prompt == '{"name": "Avery"}'
    for secret in ("394827", "sas-signature-value", "shared-key-value"):
        assert secret not in result.model_dump_json()


def test_request_depth_limit_does_not_echo_nested_values(api):
    client, redis = api
    value = "private-deep-value"
    for _ in range(20):
        value = {"nested": value}
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current",
        json=request_data(template_vars=value),
    )
    assert response.status_code == 422
    assert "private-deep-value" not in response.text
    assert not redis.read_keys


def test_saved_and_new_draft_configs_are_read_without_registration(api):
    client, redis = api
    saved = UnifiedAgent(
        name="Saved", template_vars={"removed": "saved", "choice": "old"}, tool_names=["old_tool"]
    )
    scenario = ScenarioConfig(
        name="Saved scenario",
        agent_defaults=AgentOverride(template_vars={"organization": "Saved organization"}),
        global_template_vars={"choice": "saved scenario"},
    )
    redis.data["session:current"]["corememory"] = json.dumps(
        {
            "session_agents_all": {"Saved": session_agents._serialize_agent(saved)},
            "session_scenarios_all": {
                "saved scenario": session_scenarios._serialize_scenario(scenario)
            },
            "active_scenario_name": "saved scenario",
        }
    )
    before = copy.deepcopy(redis.data)
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current",
        json=request_data(
            "{{ removed | default('absent') }}|{{ choice }}|{{ organization }}",
            agent_name="Saved",
            template_vars={"choice": "draft"},
            tools=["draft_tool"],
        ),
    )
    assert response.status_code == 200
    assert response.json()["rendered_prompt"] == "absent|saved scenario|Saved organization"
    assert response.json()["scenario_name"] == "Saved scenario"
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current",
        json=request_data(
            "{{ choice }}",
            agent_name="Never saved",
            template_vars={"choice": "draft"},
            scenario={
                "name": "Never saved scenario",
                "global_template_vars": {"choice": "new scenario"},
            },
        ),
    )
    assert response.status_code == 200
    assert response.json()["rendered_prompt"] == "new scenario"
    assert redis.data == before
    assert session_agents._session_agents == {}
    assert session_scenarios._session_scenarios == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": None},
        {"mode": "invalid-secret-value"},
        {"template_vars": "invalid-secret-value"},
        {"tools": ["valid", {"password": "invalid-secret-value"}]},
        {"extra": "invalid-secret-value"},
        {"prompt": "invalid-secret-value" * 5000},
        {"template_vars": {"number": 10**200}},
    ],
)
def test_invalid_request_shapes_do_not_echo_input(api, changes):
    client, redis = api
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current", json=request_data(**changes)
    )
    assert response.status_code in {413, 422}
    assert "invalid-secret-value" not in response.text
    assert not redis.read_keys


def test_raw_body_limit_and_missing_session_id(api):
    client, redis = api
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current",
        content=b"x" * (MAX_PREVIEW_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    response = client.post("/api/v1/agent-builder/prompt-preview", json=request_data())
    assert response.status_code == 422
    assert not redis.read_keys


def test_service_failure_is_not_a_fake_preview(api, monkeypatch):
    client, redis = api
    monkeypatch.setattr(
        redis, "get_session_data", Mock(side_effect=RuntimeError("password=private-failure-value"))
    )
    response = client.post(
        "/api/v1/agent-builder/prompt-preview?session_id=current", json=request_data()
    )
    assert response.status_code == 503
    assert "private-failure-value" not in response.text
    assert "rendered_prompt" not in response.json()
