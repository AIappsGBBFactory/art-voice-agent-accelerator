"""
Voice Live BYOM chat-completion model deployments
=================================================

Voice Live's ``byom-azure-openai-chat-completion`` profile drives a deployment
on the **Voice Live account** over ``/chat/completions``. A chat model that only
exists on the primary Foundry account is therefore unreachable through that
profile — which is how ``mosdev`` ended up with a Voice Live account hosting only
``gpt-realtime`` (realtime-only) and ``gpt-4o-transcribe`` (transcription), making
the chat-completion profile structurally unusable and every session mute.

These tests pin the Terraform contract that fixes it, and the model-config
plumbing that lets those deployments be pinned to "no reasoning" — reasoning
latency is paid on every turn, which a real-time voice agent cannot afford.

The Terraform locals are re-implemented here in Python rather than shelling out
to ``terraform``: the point is to lock the *placement invariants*, which is what
silently broke, and to keep the suite hermetic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"


# ═══════════════════════════════════════════════════════════════════════════
# Terraform placement invariants
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_placement(
    *,
    model_deployments: list[str],
    voice_live_model_deployments: list[str],
    voice_live_byom_model_deployments: list[str],
    should_create_voice_live_account: bool,
    should_enable_voice_live_here: bool = False,
) -> tuple[set[str], set[str]]:
    """Mirror of the ``main.tf`` locals that decide which account hosts what.

    Returns ``(primary_foundry_models, voice_live_models)``.
    """
    # Only the Voice Live *exclusive* models suppress a primary deployment. The
    # BYOM chat models deliberately do not participate.
    voice_live_model_names = set(voice_live_model_deployments)

    base = {
        name
        for name in model_deployments
        if not (should_create_voice_live_account and name in voice_live_model_names)
    }

    vl_map = set(voice_live_model_deployments)
    byom_map = set(voice_live_byom_model_deployments)

    combined = (
        base | vl_map | byom_map if should_enable_voice_live_here else base
    )
    voice_live = vl_map | byom_map
    return combined, voice_live


@pytest.fixture
def mosdev_inputs():
    """The live ``mosdev`` shape: a separate Voice Live account in another region.

    ``openai_location`` is northcentralus, which is not a Voice Live region, so
    ``should_create_voice_live_account`` is true and the exclusion logic is armed.
    """
    return {
        "model_deployments": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-5.4",
            "text-embedding-3-large",
        ],
        "voice_live_model_deployments": ["gpt-realtime", "gpt-4o-transcribe"],
        "voice_live_byom_model_deployments": ["gpt-5.4", "gpt-5-mini"],
        "should_create_voice_live_account": True,
    }


def test_byom_chat_models_land_on_the_voice_live_account(mosdev_inputs):
    """The whole point: chat models must exist where BYOM will look for them."""
    _primary, voice_live = _resolve_placement(**mosdev_inputs)

    assert "gpt-5.4" in voice_live
    assert "gpt-5-mini" in voice_live
    # ...alongside the realtime/transcription models it already had.
    assert "gpt-realtime" in voice_live
    assert "gpt-4o-transcribe" in voice_live


def test_shared_chat_model_is_not_stripped_from_the_primary_account(mosdev_inputs):
    """Regression guard for the trap in the obvious implementation.

    Adding ``gpt-5.4`` to ``voice_live_model_deployments`` would have put its name
    into ``voice_live_model_names``, whose only job is to *suppress* the primary
    deployment of that model. Since gpt-5.4 is the live Cascade model, Terraform
    would have destroyed it. Keeping BYOM chat models in their own variable is
    what prevents that, and this asserts it.
    """
    primary, voice_live = _resolve_placement(**mosdev_inputs)

    assert "gpt-5.4" in primary, "Cascade would lose its model"
    assert "gpt-5.4" in voice_live, "BYOM would have nothing to serve"


def test_naive_placement_would_have_destroyed_the_cascade_model(mosdev_inputs):
    """Demonstrates the failure mode the split variable exists to avoid."""
    naive = dict(mosdev_inputs)
    naive["voice_live_model_deployments"] = [
        *mosdev_inputs["voice_live_model_deployments"],
        "gpt-5.4",
    ]
    naive["voice_live_byom_model_deployments"] = ["gpt-5-mini"]

    primary, _voice_live = _resolve_placement(**naive)

    assert "gpt-5.4" not in primary


def test_realtime_models_stay_exclusive_to_the_voice_live_account(mosdev_inputs):
    """The existing suppression behaviour must survive unchanged."""
    inputs = dict(mosdev_inputs)
    # An operator listing a realtime model in both places still gets one copy,
    # on the Voice Live account only.
    inputs["model_deployments"] = [*mosdev_inputs["model_deployments"], "gpt-realtime"]

    primary, voice_live = _resolve_placement(**inputs)

    assert "gpt-realtime" not in primary
    assert "gpt-realtime" in voice_live


def test_model_listed_in_both_voice_live_variables_deploys_once(mosdev_inputs):
    """Maps are keyed by name, so a duplicate can't collide on the module for_each."""
    inputs = dict(mosdev_inputs)
    inputs["voice_live_byom_model_deployments"] = ["gpt-5.4", "gpt-5-mini", "gpt-realtime"]

    _primary, voice_live = _resolve_placement(**inputs)

    assert sorted(voice_live) == ["gpt-4o-transcribe", "gpt-5-mini", "gpt-5.4", "gpt-realtime"]


def test_terraform_declares_the_byom_variable_with_chat_models():
    """The committed default must actually carry chat-completion models.

    A realtime model here would recreate the original outage, since
    ``byom-azure-openai-chat-completion`` cannot drive a realtime deployment.
    """
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")

    assert 'variable "voice_live_byom_model_deployments"' in variables

    block = variables.split('variable "voice_live_byom_model_deployments"', 1)[1]
    block = block.split("\nvariable ", 1)[0]

    # Only the declared model names matter here — the surrounding prose explains
    # why realtime models live in the other variable and would false-positive a
    # naive substring check.
    names = re.findall(r'name\s*=\s*"([^"]+)"', block)

    assert "gpt-5.4" in names
    assert "gpt-5-mini" in names
    assert not [n for n in names if "realtime" in n], (
        f"a realtime model cannot serve /chat/completions: {names}"
    )


def test_terraform_exclusion_list_ignores_byom_models():
    """``voice_live_model_names`` must not be fed by the BYOM variable."""
    main_tf = (TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")

    line = next(
        ln for ln in main_tf.splitlines() if ln.strip().startswith("voice_live_model_names")
    )
    assert "var.voice_live_model_deployments" in line
    assert "byom" not in line.lower()


@pytest.mark.parametrize("env", ["mosdev", "dev", "staging", "prod"])
def test_env_tfvars_remain_valid_json(env):
    """The params files are consumed by the azd preprovision hook."""
    path = TERRAFORM_DIR / "params" / f"main.tfvars.{env}.json"
    if not path.exists():
        pytest.skip(f"no tfvars for {env}")
    json.loads(path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# "No reasoning" plumbing
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "deployment_id,supported",
    [
        ("gpt-5.4", True),
        ("gpt-5-mini", True),
        ("gpt-5", True),
        ("o3-mini", True),
        ("o1", True),
        ("gpt-4o", False),
        ("gpt-4o-mini", False),
        ("gpt-realtime", False),
    ],
)
def test_supports_reasoning_effort(deployment_id, supported):
    from apps.artagent.backend.registries.agentstore.base import ModelConfig

    assert ModelConfig(deployment_id=deployment_id).supports_reasoning_effort is supported


def test_gpt5_is_not_misreported_as_a_reasoning_only_model():
    """``is_reasoning_model`` keeps its o-series meaning.

    Cascade uses it to pick ``max_completion_tokens``; gpt-5 is already covered
    there by explicit family checks, so widening it would have been redundant and
    would have dragged the o-series ``reasoning_effort="low"`` default onto gpt-5 —
    the opposite of no reasoning.
    """
    from apps.artagent.backend.registries.agentstore.base import ModelConfig

    cfg = ModelConfig(deployment_id="gpt-5.4")
    assert cfg.is_reasoning_model is False
    assert cfg.supports_reasoning_effort is True


def test_no_reasoning_is_expressible_for_a_byom_chat_model():
    """Regression guard: this value used to be accepted and then dropped."""
    from apps.artagent.backend.registries.agentstore.base import ModelConfig

    cfg = ModelConfig.from_dict(
        {"deployment_id": "gpt-5.4", "reasoning_effort": "none"}
    )

    assert cfg.reasoning_effort == "none"
    assert cfg.supports_reasoning_effort is True
    assert cfg.to_dict()["reasoning_effort"] == "none"
