"""Offline regressions for the actual post-deploy evaluation workflow scripts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from apps.artagent.backend.api.v1.endpoints.health import health_check
from apps.artagent.backend.api.v1.router import v1_router

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _workflow(filename: str) -> dict:
    # GitHub uses YAML 1.2: "on" is a key, not the YAML 1.1 boolean True.
    return yaml.load((WORKFLOWS / filename).read_text(), Loader=yaml.BaseLoader)


def _step(workflow: dict, job: str, name: str) -> dict:
    return next(step for step in workflow["jobs"][job]["steps"] if name in step["name"])


def _run_script(step: dict, helpers: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    script = step["run"].replace("${{ github.repository }}", "example/repo")
    return subprocess.run(
        ["bash", "-c", helpers + "\n" + script],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_live_evals_use_staging_dispatch_not_default_branch_workflow_run():
    workflow = _workflow("live-evals-staging.yml")
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["jobs"]["prepare"]["environment"] == "staging"
    assert workflow["env"]["EVAL_STRICT_GATE"] == "1"


def test_dispatch_uses_job_token_with_caller_and_finalizer_permissions():
    deploy = _workflow("deploy-azd-complete.yml")
    template = _workflow("_template-deploy-azd.yml")
    dispatch = _step(template, "finalize", "Dispatch Live Evals")
    assert dispatch["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert deploy["permissions"]["actions"] == "write"
    assert template["jobs"]["finalize"]["permissions"]["actions"] == "write"
    assert "needs.execute.result == 'success'" in template["jobs"]["finalize"]["if"]
    assert "github.event_name != 'pull_request'" in template["jobs"]["finalize"]["if"]
    assert dispatch["if"] == (
        "inputs.environment == 'staging' && " "(inputs.action == 'up' || inputs.action == 'deploy')"
    )


@pytest.mark.parametrize("exit_code", ["0", "1"])
def test_dispatch_passes_deployment_coordinates_and_propagates_failure(exit_code):
    dispatch = _step(_workflow("_template-deploy-azd.yml"), "finalize", "Dispatch Live Evals")
    result = _run_script(
        dispatch,
        'gh() { printf "<%s>\\n" "$@"; return "$GH_EXIT_CODE"; }',
        {
            "GH_TOKEN": "fake-job-token",
            "GH_REPO": "example/repo",
            "GH_EXIT_CODE": exit_code,
            "BACKEND_URL": "https://backend.example",
            "BACKEND_CONTAINER_APP_NAME": "backend-app",
            "RESOURCE_GROUP": "backend-group",
        },
    )
    assert result.returncode == int(exit_code), result.stdout + result.stderr
    assert "<--ref>\n<staging>" in result.stdout
    assert "<--repo>\n<example/repo>" in result.stdout
    assert "<backend_url=https://backend.example>" in result.stdout
    assert "<backend_container_app_name=backend-app>" in result.stdout
    assert "<resource_group=backend-group>" in result.stdout
    assert ("Live evals dispatched on staging" in result.stdout) == (exit_code == "0")


@pytest.mark.parametrize(
    ("env_key", "input_key", "output_key"),
    [
        ("BACKEND_CONTAINER_APP_URL", "backend_url", "backend_url"),
        (
            "BACKEND_CONTAINER_APP_NAME",
            "backend_container_app_name",
            "backend_container_app_name",
        ),
        ("AZURE_RESOURCE_GROUP", "resource_group", "resource_group"),
    ],
)
def test_live_evals_prefer_dispatched_coordinates_over_stale_environment_variables(
    env_key, input_key, output_key
):
    workflow = _workflow("live-evals-staging.yml")
    assert workflow["on"]["workflow_dispatch"]["inputs"][input_key]["type"] == "string"
    assert workflow["jobs"]["prepare"]["env"][env_key].startswith(
        "${{ inputs." + input_key + " || "
    )
    dispatch = _step(_workflow("_template-deploy-azd.yml"), "finalize", "Dispatch Live Evals")
    assert "${{ needs.execute.outputs." + output_key + " }}" in dispatch["env"].values()
    if input_key == "backend_url":
        assert workflow["jobs"]["voice-e2e"]["env"]["EVAL_LIVE_URL"].startswith(
            "${{ inputs.backend_url || "
        )


@pytest.mark.parametrize("base_url", ["https://backend.example", "https://backend.example/"])
@pytest.mark.parametrize("status", ["200", "503"])
def test_readiness_polls_registered_health_route_and_preserves_failure_gate(base_url, status):
    workflow = _workflow("live-evals-staging.yml")
    readiness = _step(workflow, "prepare", "Wait for Backend Revision")
    health_path = next(route.path for route in v1_router.routes if route.endpoint is health_check)
    result = _run_script(
        readiness,
        """
exec 3>&2
az() {
    case "$*" in
        *runningState*) echo Running ;;
        *provisioningState*) echo Provisioned ;;
        *) return 1 ;;
    esac
}
curl() {
    local url="${@: -1}"
    echo "PROBE $url" >&3
    if [ "$url" = "$EXPECTED_HEALTH_URL" ]; then
        echo "$HEALTH_STATUS"
    else
        echo 404
    fi
}
sleep() { :; }
""",
        {
            "BACKEND_CONTAINER_APP_NAME": "backend-app",
            "AZURE_RESOURCE_GROUP": "backend-group",
            "BACKEND_CONTAINER_APP_URL": base_url,
            "EXPECTED_HEALTH_URL": base_url.rstrip("/") + health_path,
            "HEALTH_STATUS": status,
        },
    )
    assert result.returncode == (0 if status == "200" else 1), result.stdout + result.stderr
    assert result.stderr.splitlines() == ["PROBE " + base_url.rstrip("/") + health_path] * (
        1 if status == "200" else 10
    )


def test_workflow_changes_trigger_their_offline_regressions():
    unit = _workflow("test-unit.yml")
    for event in ("push", "pull_request"):
        for filename in (
            "live-evals-staging.yml",
            "_template-deploy-azd.yml",
            "deploy-azd-complete.yml",
        ):
            assert ".github/workflows/" + filename in unit["on"][event]["paths"]
