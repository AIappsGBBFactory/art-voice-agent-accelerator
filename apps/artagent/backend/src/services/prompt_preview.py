"""Read-only prompt previews from draft configuration and one scoped session snapshot."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from apps.artagent.backend.api.v1.schemas.prompt_preview import (
    MAX_CONTEXT_BYTES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    PromptPreviewError,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptVariable,
    check_json_budget,
)
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.registries.agentstore.loader import discover_agents
from apps.artagent.backend.registries.scenariostore import loader as scenario_loader
from apps.artagent.backend.src.orchestration import session_scenarios
from apps.artagent.backend.src.orchestration.naming import (
    find_agent_by_name,
    find_scenario_by_name,
    get_scenario_from_corememory,
)
from apps.artagent.backend.src.orchestration.prompt_context import (
    cascade_prompt_context,
    cascade_runtime_prompt_context,
    refresh_voicelive_prompt_context,
    voicelive_prompt_context,
)
from apps.artagent.backend.src.orchestration.session_drafts import (
    DraftPersistenceError,
    SessionAuthoringSnapshot,
    get_authoring_redis,
    read_authoring_snapshot,
)
from apps.artagent.backend.src.services.prompt_sandbox import (
    PreviewLimitError,
    render_prompt_preview,
    template_path,
)
from apps.artagent.backend.voice.shared.session_state import sync_state_from_memo

MAX_VARIABLE_ROWS = 512
MAX_SECRET_SCAN_NODES = 20_000
MAX_SNAPSHOT_SCAN_BYTES = 4_000_000
_OMIT = object()
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESERVED = {
    "true",
    "false",
    "none",
    "True",
    "False",
    "None",
    "if",
    "else",
    "for",
    "in",
    "is",
    "and",
    "or",
    "not",
}
_INTERNAL_KEYS = {
    "memo_manager",
    "redis",
    "redis_manager",
    "redis_client",
    "session_agents_all",
    "session_scenarios_all",
    "session_scenario_config",
    "session_overrides",
    "environment",
    "environ",
    "env",
    "headers",
    "cookies",
}
_SENSITIVE_KEY = re.compile(
    r"secret|password|passphrase|passwd|credential|authorization|"
    r"(?:api|account|subscription|private|access|signing|encryption)[_-]?key|"
    r"connection[_-]?string|(?:^|[_-])(?:token|otp|pin|cvv|cvc|ssn|code|pwd)(?:$|[_-])|"
    r"(?:verification|security|authentication|auth|mfa|one[_-]?time)[_-]?(?:code|token)|"
    r"(?:^|[_-])mfa(?:$|[_-])",
    re.IGNORECASE,
)
_CREDENTIAL_LABEL = (
    r"(?:api[_ -]?key|password|passwd|secret|[\w-]*token|client[_ -]?secret|"
    r"account[_ -]?key|subscription[_ -]?key|(?:shared[_ -]?)?access[_ -]?key|"
    r"connection[_ -]?string|(?:verification|security|authentication|auth|mfa)[_ -]?code|"
    r"one[_ -]?time[_ -]?(?:code|password)|otp|pin)"
)
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:Bearer|Basic|Negotiate)\s+[A-Za-z0-9._~+/=-]+|"
    rf"\b{_CREDENTIAL_LABEL}"
    r"""["']?\s*[=:]\s*["']?[^\s,"';}\]]+|"""
    r"\b(?:verification code|one.time code|security code|the code)\s+(?:is\s+)?\d{4,10}\b|"
    r"[?&](?:sig|access_token|api_key|token)=[^&#\s]+|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
_SECRET_VALUES = (
    re.compile(r"(?i)\b(?:Bearer|Basic|Negotiate)\s+([A-Za-z0-9._~+/=-]+)"),
    re.compile(rf"(?i)\b{_CREDENTIAL_LABEL}" r"""["']?\s*[=:]\s*["']?([^\s,"';}\]]+)"""),
    re.compile(
        r"(?i)\b(?:verification code|one.time code|security code|the code)\s+(?:is\s+)?(\d{4,10})\b"
    ),
    re.compile(r"(?i)[?&](?:sig|access_token|api_key|token)=([^&#\s]+)"),
)
_CONTEXT_TYPES = {
    "session_profile": "object",
    "caller_name": "string",
    "client_id": "string",
    "customer_intelligence": "object",
    "institution_name": "string",
    "active_agent": "string",
    "previous_agent": "string",
    "visited_agents": "array",
    "handoff_context": "object",
}
_VOICELIVE_TYPES = {
    "slots": "object",
    "collected_information": "object",
    "tool_outputs": "object",
    "recent_user_messages": "array",
    "conversation_summary": "string",
    "last_assistant_response": "string",
}


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return bool(_SENSITIVE_KEY.search(normalized))


def _internal_key(key: str) -> bool:
    return key.startswith("_") or key.lower() in _INTERNAL_KEYS


def _json_type(value: Any) -> str:
    return {
        str: "string",
        bool: "boolean",
        int: "number",
        float: "number",
        dict: "object",
        list: "array",
        type(None): "null",
    }.get(type(value), "unknown")


@dataclass
class _Redactor:
    secrets: set[str] = field(default_factory=set)
    pattern: re.Pattern[str] | None = None
    masked: dict[str, str] = field(default_factory=dict)
    omitted: set[str] = field(default_factory=set)
    changed: bool = False
    visited: int = 0
    scanned_bytes: int = 0

    def collect(self, value: Any) -> None:
        """Find sensitive scalar values before copying anything into Jinja."""
        pending = [(value, False, 0)]
        count = 0
        while pending:
            item, sensitive, depth = pending.pop()
            count += 1
            if count > MAX_SECRET_SCAN_NODES or depth > MAX_JSON_DEPTH + 4:
                raise PreviewLimitError("Session snapshot exceeds the scan limit.")
            if type(item) is dict:
                if len(item) > MAX_SECRET_SCAN_NODES:
                    raise PreviewLimitError("Session snapshot exceeds the scan limit.")
                for key, child in item.items():
                    if type(key) is str:
                        protected = _sensitive_key(key) or key.lower() in {
                            "headers",
                            "cookies",
                            "environment",
                            "environ",
                            "env",
                        }
                        pending.append((child, sensitive or protected, depth + 1))
            elif type(item) is list:
                if len(item) > MAX_SECRET_SCAN_NODES:
                    raise PreviewLimitError("Session snapshot exceeds the scan limit.")
                pending.extend((child, sensitive, depth + 1) for child in item)
            elif sensitive and type(item) in (str, int, float):
                text = str(item)
                if text:
                    self.secrets.add(text)
            if type(item) is str:
                if len(item) > MAX_CONTEXT_BYTES:
                    raise PreviewLimitError("Session text exceeds the scan limit.")
                self.scanned_bytes += len(item.encode("utf-8"))
                if self.scanned_bytes > MAX_SNAPSHOT_SCAN_BYTES:
                    raise PreviewLimitError("Session snapshot exceeds the scan size limit.")
                for pattern in _SECRET_VALUES:
                    self.secrets.update(match.group(1) for match in pattern.finditer(item))
            if len(self.secrets) > 256 or sum(map(len, self.secrets)) > MAX_CONTEXT_BYTES:
                raise PreviewLimitError("Session redaction limit exceeded.")

    def prepare(self) -> None:
        if self.secrets:
            patterns = [
                re.escape(value) if len(value) > 3 else rf"(?<!\w){re.escape(value)}(?!\w)"
                for value in sorted(self.secrets, key=len, reverse=True)
            ]
            self.pattern = re.compile("|".join(patterns), re.IGNORECASE)

    def text(self, value: str) -> str:
        cleaned = self.pattern.sub("[redacted]", value) if self.pattern else value
        cleaned = _SECRET_TEXT.sub("[redacted]", cleaned)
        if cleaned != value:
            self.changed = True
        return cleaned

    def sanitize(self, value: Any, path: str = "", *, depth: int = 0) -> Any:
        self.visited += 1
        if self.visited > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise PreviewLimitError("Prompt context structure limit exceeded.")
        if type(value) is dict:
            if len(value) > MAX_JSON_NODES:
                raise PreviewLimitError("Prompt context structure limit exceeded.")
            result = {}
            for key, item in value.items():
                if type(key) is not str or len(key) > 128 or self.text(key) != key:
                    self.changed = True
                    continue
                child_path = template_path(path, key)
                if _internal_key(key) or (
                    not path and (not _IDENTIFIER.fullmatch(key) or key in _RESERVED)
                ):
                    self.omitted.add(child_path)
                    continue
                if _sensitive_key(key):
                    self.masked[child_path] = _json_type(item)
                    self.changed = True
                    continue
                child = self.sanitize(item, child_path, depth=depth + 1)
                if child is not _OMIT:
                    result[key] = child
            return result
        if type(value) is list:
            if len(value) > MAX_JSON_NODES:
                raise PreviewLimitError("Prompt context structure limit exceeded.")
            result = [
                self.sanitize(item, template_path(path, index), depth=depth + 1)
                for index, item in enumerate(value)
            ]
            # Never shift array indexes or substitute a fake runtime value.
            if any(item is _OMIT for item in result):
                self.masked[path] = "array"
                self.changed = True
                return _OMIT
            return result
        if type(value) is str:
            if len(value) > MAX_CONTEXT_BYTES:
                raise PreviewLimitError("Prompt context size limit exceeded.")
            if self.text(value) != value:
                self.masked[path] = "string"
                return _OMIT
            return value
        if value is None or type(value) in (bool, int, float):
            if type(value) in (int, float) and str(value) in self.secrets:
                self.masked[path] = "number"
                self.changed = True
                return _OMIT
            return value
        self.omitted.add(path)
        return _OMIT


def _selected_scenario(
    body: PromptPreviewRequest, snapshot: SessionAuthoringSnapshot, app_state: Any
) -> scenario_loader.ScenarioConfig | None:
    if body.scenario is not None:
        return session_scenarios._parse_scenario_data(body.scenario.model_dump())
    active = get_scenario_from_corememory(snapshot.memo)
    if not active and not snapshot.redis_data:
        active = session_scenarios._active_scenario.get(snapshot.memo.session_id)
    if active:
        _, scenario = find_scenario_by_name(snapshot.scenarios, active)
        if scenario is None:
            # Reading the already-loaded catalog must not discover/register scenarios.
            _, scenario = find_scenario_by_name(scenario_loader._SCENARIOS, active)
        if scenario is not None:
            return scenario
        deployed = getattr(app_state, "scenario", None)
        if deployed is not None and deployed.name.lower() == active.lower():
            return deployed
        raise DraftPersistenceError("The active scenario is not available in the snapshot.")
    return getattr(app_state, "scenario", None)


def _runtime_context(
    body: PromptPreviewRequest, snapshot: SessionAuthoringSnapshot, live: Any | None
) -> dict[str, Any]:
    memo = snapshot.memo
    if body.mode == "cascade":
        active = memo.get_value_from_corememory("active_agent")
        metadata = cascade_prompt_context(memo, agent_name=active if type(active) is str else None)
        return cascade_runtime_prompt_context(
            metadata, session_vars=getattr(live, "_session_vars", None)
        )
    if live is not None:
        history = list(live._user_message_history)
        _check_history(history)
        return voicelive_prompt_context(
            dict(live._system_vars),
            active_agent=live.active,
            user_messages=history,
            last_assistant_response=live._last_assistant_message,
        )
    variables = sync_state_from_memo(memo).system_vars
    refresh_voicelive_prompt_context(variables, memo)
    stored_history = memo.get_value_from_corememory("user_message_history")
    history = stored_history[-5:] if type(stored_history) is list else []
    _check_history(history)
    return voicelive_prompt_context(
        variables,
        active_agent=memo.get_value_from_corememory("active_agent"),
        user_messages=history,
        last_assistant_response=None,
    )


def _check_history(history: list[Any]) -> None:
    if not all(type(message) is str for message in history):
        raise DraftPersistenceError("The stored message history is invalid.")
    if (
        len(history) > 5
        or sum(len(message.encode("utf-8")) for message in history) > MAX_CONTEXT_BYTES
    ):
        raise PreviewLimitError("Session history exceeds the preview size limit.")


def _variable(
    path: str,
    source: str,
    *,
    value: Any = _OMIT,
    value_type: str = "unknown",
    sensitive: bool = False,
) -> PromptVariable:
    available = value is not _OMIT and not sensitive
    preview = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if available else ""
    if len(preview) > 180:
        preview = preview[:177] + "..."
    return PromptVariable(
        path=path,
        expression=f"{{{{ {path} }}}}",
        source=source,
        type=_json_type(value) if available else value_type,
        value_preview="[redacted]" if sensitive else preview,
        available=available,
        sensitive=sensitive,
    )


def _variables(
    context: dict[str, Any],
    sources: dict[str, str],
    redactor: _Redactor,
    *,
    mode: str,
    references: set[str],
    missing_paths: list[str],
) -> tuple[list[PromptVariable], bool]:
    rows: dict[str, PromptVariable] = {}
    expected = {"agent_name": "string", **_CONTEXT_TYPES}
    expected.update(
        _VOICELIVE_TYPES if mode == "voicelive" else {"is_acs": "boolean", "run_id": "string"}
    )
    for key, value_type in expected.items():
        rows[key] = _variable(key, sources.get(key, "session context"), value_type=value_type)
    pending = [(key, value, sources.get(key, "agent defaults")) for key, value in context.items()]
    while pending and len(rows) < MAX_VARIABLE_ROWS:
        path, value, source = pending.pop()
        rows[path] = _variable(path, source, value=value)
        if type(value) in (dict, list):
            items = value.items() if type(value) is dict else enumerate(value)
            pending.extend((template_path(path, key), child, source) for key, child in items)
    # Truncating nested rows must not mark populated top-level bindings unavailable.
    for key, value in context.items():
        if key in rows:
            rows[key] = _variable(key, sources.get(key, "agent defaults"), value=value)
    for path, value_type in redactor.masked.items():
        if len(rows) >= MAX_VARIABLE_ROWS and path not in rows:
            continue
        root = re.split(r"[.\[]", path, maxsplit=1)[0]
        rows[path] = _variable(
            path, sources.get(root, "session context"), value_type=value_type, sensitive=True
        )
    for path in sorted(references | set(missing_paths)):
        if len(rows) >= MAX_VARIABLE_ROWS:
            break
        if path not in rows and not _internal_key(path) and redactor.text(path) == path:
            rows[path] = _variable(path, "template reference", sensitive=_sensitive_key(path))
    rows = {
        path: item
        for path, item in rows.items()
        if redactor.text(path) == path
        and not any(
            path == hidden or path.startswith(hidden + ".") or path.startswith(hidden + "[")
            for hidden in redactor.omitted
        )
    }
    return sorted(rows.values(), key=lambda row: row.path), bool(pending)


def _render_snapshot(
    body: PromptPreviewRequest,
    snapshot: SessionAuthoringSnapshot,
    *,
    saved_agent: UnifiedAgent | None,
    app_state: Any,
    live: Any | None,
) -> PromptPreviewResponse:
    scenario = _selected_scenario(body, snapshot, app_state)
    template_vars = (
        body.template_vars
        if "template_vars" in body.model_fields_set
        else (saved_agent.template_vars if saved_agent is not None else {})
    )
    tools = (
        body.tools
        if "tools" in body.model_fields_set
        else (saved_agent.tool_names if saved_agent is not None else [])
    )
    merged = dict(template_vars)
    sources = dict.fromkeys(merged, "agent template vars")
    if scenario is not None:
        merged.update(scenario.global_template_vars)
        sources.update(dict.fromkeys(scenario.global_template_vars, "scenario global vars"))
        if scenario.agent_defaults:
            merged.update(scenario.agent_defaults.template_vars)
            sources.update(
                dict.fromkeys(scenario.agent_defaults.template_vars, "scenario agent defaults")
            )
    agent = UnifiedAgent(
        name=body.agent_name,
        prompt_template=body.prompt,
        template_vars=merged,
        tool_names=list(tools),
    )
    response = PromptPreviewResponse(mode=body.mode)
    response.warnings.append(
        "Preview renders the edited template only; runtime handoff instructions and "
        "conversation recap are appended separately."
    )
    if body.mode == "voicelive" and live is None:
        response.warnings.append(
            "Using persisted session context. Connection-only VoiceLive values are unavailable."
        )
    redactor = _Redactor()
    try:
        runtime = _runtime_context(body, snapshot, live)
        # Scan the scoped snapshot as well as the selected context: a credential
        # copied into an innocent-looking alias must not become renderable.
        redactor.collect(snapshot.memo.context)
        redactor.collect(
            {"template_vars": template_vars, "resolved_vars": merged, "runtime": runtime}
        )
        if scenario is not None:
            redactor.collect(scenario.global_template_vars)
            if scenario.agent_defaults:
                redactor.collect(scenario.agent_defaults.template_vars)
        redactor.prepare()
        response.scenario_name = redactor.text(scenario.name) if scenario is not None else None
        valid_runtime = {
            key: value
            for key, value in runtime.items()
            if type(value) in (dict, list, str, int, float, bool, type(None))
        }
        resolved = agent.get_prompt_context(valid_runtime)
        for key in runtime.keys() - valid_runtime.keys():
            resolved.pop(key, None)
            redactor.omitted.add(key)
        for key, value in valid_runtime.items():
            if value is not None and value != "None":
                sources[key] = "session context"
        for key in resolved:
            sources.setdefault(key, "agent defaults")
        safe_context = redactor.sanitize(resolved)
        check_json_budget(safe_context)
        result = render_prompt_preview(redactor.text(body.prompt), safe_context)
        response.rendered_prompt = result.rendered
        response.errors = result.errors
        response.missing_variables = [redactor.text(path) for path in result.missing]
        response.variables, truncated = _variables(
            safe_context,
            sources,
            redactor,
            mode=body.mode,
            references=result.references,
            missing_paths=result.missing,
        )
        if truncated:
            response.warnings.append("Variable metadata is limited to the first 512 paths.")
        if result.rendered is not None:
            response.rendered_prompt = redactor.text(result.rendered)
    except (PreviewLimitError, ValueError, RecursionError, OverflowError):
        response.rendered_prompt = None
        response.errors = [
            PromptPreviewError(
                message="Session prompt context exceeds the supported JSON size or structure limits.",
                kind="limit",
            )
        ]
        response.variables = [
            _variable(key, "session context", value_type=value_type)
            for key, value_type in _CONTEXT_TYPES.items()
        ]
    if redactor.changed or redactor.masked:
        response.warnings.append(
            "Sensitive fields and credential-like text are omitted or redacted."
        )
    if redactor.omitted:
        response.warnings.append("Internal objects and non-insertable context paths are omitted.")
    if tools and "tools" not in merged:
        response.warnings.append(
            "Tool selections are preview-only configuration, not a Jinja variable. No tools are run."
        )
    return response


async def preview_prompt(
    body: PromptPreviewRequest, *, session_id: str, app_state: Any
) -> PromptPreviewResponse:
    """Preview without registry writes, activation, model calls, or tool discovery."""
    redis = getattr(app_state, "redis_client", None) or get_authoring_redis(app_state)
    snapshot = await read_authoring_snapshot(session_id, redis)
    _, saved_agent = find_agent_by_name(snapshot.agents, body.agent_name)
    if saved_agent is None and not {"template_vars", "tools"} <= body.model_fields_set:
        builtins = await asyncio.wait_for(asyncio.to_thread(discover_agents), timeout=10)
        _, saved_agent = find_agent_by_name(builtins, body.agent_name)
    live = None
    if body.mode == "voicelive":
        from apps.artagent.backend.voice.voicelive.orchestrator import get_voicelive_orchestrator

        live = get_voicelive_orchestrator(session_id)
    else:
        from apps.artagent.backend.src.orchestration.unified import _adapters

        live = _adapters.get(session_id)
    return _render_snapshot(body, snapshot, saved_agent=saved_agent, app_state=app_state, live=live)
