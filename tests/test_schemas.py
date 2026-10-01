"""Behavior tests for TaskSpec / Authority / RunState contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from taskwitness.schemas import ActionType, Authority, RunState, TaskSpec

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _base_kwargs(**overrides):
    data = {
        "source_file": "data/candidates.csv",
        "role": "AI Engineering",
        "candidate_status": "Shortlisted",
        "actions": [
            ActionType.prepare_followup,
            ActionType.set_stage,
            ActionType.send_message,
        ],
        "target_stage": "Interview Ready",
        "authority": Authority(send_message=False, change_stage=True),
    }
    data.update(overrides)
    return data


def test_base_taskspec_is_valid():
    spec = TaskSpec(**_base_kwargs())
    assert spec.role == "AI Engineering"
    assert ActionType.set_stage in spec.actions
    assert spec.authority.send_message is False
    assert spec.authority.change_stage is True


def test_variation_taskspec_is_valid():
    spec = TaskSpec(
        source_file="data/candidates.csv",
        role="Backend Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup],
        target_stage=None,
        authority=Authority(send_message=False, change_stage=False),
    )
    assert spec.actions == [ActionType.prepare_followup]
    assert spec.target_stage is None


def test_base_plan_json_validates():
    payload = json.loads((EXAMPLES / "base-plan.json").read_text(encoding="utf-8"))
    spec = TaskSpec.model_validate(payload)
    assert spec.target_stage == "Interview Ready"
    assert ActionType.send_message in spec.actions
    assert spec.authority.send_message is False


def test_variation_plan_json_validates():
    payload = json.loads((EXAMPLES / "variation-plan.json").read_text(encoding="utf-8"))
    spec = TaskSpec.model_validate(payload)
    assert spec.role == "Backend Engineering"
    assert spec.actions == [ActionType.prepare_followup]
    assert spec.target_stage is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_file", ""),
        ("source_file", "   "),
        ("role", ""),
        ("role", "\t"),
        ("candidate_status", ""),
        ("candidate_status", "  "),
    ],
)
def test_blank_string_fields_rejected(field, value):
    kwargs = _base_kwargs(**{field: value})
    with pytest.raises(ValidationError):
        TaskSpec(**kwargs)


def test_empty_action_list_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(**_base_kwargs(actions=[]))


def test_duplicate_actions_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(
            **_base_kwargs(
                actions=[
                    ActionType.prepare_followup,
                    ActionType.prepare_followup,
                ],
                target_stage=None,
            )
        )


def test_set_stage_without_target_stage_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(**_base_kwargs(target_stage=None))


def test_blank_target_stage_with_set_stage_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(**_base_kwargs(target_stage="  "))


def test_target_stage_without_set_stage_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(
            **_base_kwargs(
                actions=[ActionType.prepare_followup],
                target_stage="Interview Ready",
            )
        )


def test_unknown_taskspec_field_rejected():
    with pytest.raises(ValidationError):
        TaskSpec(**_base_kwargs(browser_selector="#submit"))


def test_unknown_authority_field_rejected():
    with pytest.raises(ValidationError):
        Authority(send_message=False, change_stage=True, admin=True)


def test_send_message_with_send_authority_false_is_valid():
    spec = TaskSpec(**_base_kwargs())
    assert ActionType.send_message in spec.actions
    assert spec.authority.send_message is False


def test_set_stage_with_change_stage_authority_false_is_structurally_valid():
    spec = TaskSpec(
        **_base_kwargs(authority=Authority(send_message=False, change_stage=False))
    )
    assert ActionType.set_stage in spec.actions
    assert spec.authority.change_stage is False


def test_every_expected_runstate_value_is_represented():
    expected = {
        "ready",
        "planning",
        "running",
        "paused",
        "awaiting_approval",
        "verifying",
        "recovering",
        "completed",
        "partial",
        "failed",
    }
    assert {state.value for state in RunState} == expected


def test_invalid_runstate_rejected():
    with pytest.raises(ValueError):
        RunState("succeeded")
