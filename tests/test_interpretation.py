"""Deterministic Phase-3 interpretation tests (no network / API key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskwitness.interpretation import (
    GoalInterpreter,
    InterpretationStatus,
    ModelClientError,
)
from taskwitness.interpretation.client import FakeModelClient, ModelConfig
from taskwitness.interpretation.policy import APPROVED_SOURCE, validate_taskspec_policy
from taskwitness.schemas import ActionType, Authority, TaskSpec
from taskwitness.workflow import config_from_taskspec

ROOT = Path(__file__).resolve().parents[1]


def _base_spec_dict(**overrides):
    data = {
        "source_file": "data/candidates.csv",
        "role": "AI Engineering",
        "candidate_status": "Shortlisted",
        "actions": ["prepare_followup", "set_stage", "send_message"],
        "target_stage": "Interview Ready",
        "authority": {"send_message": False, "change_stage": True},
    }
    data.update(overrides)
    return data


def _ready(task_spec: dict) -> dict:
    return {"status": "ready", "task_spec": task_spec, "clarification_question": None}


def test_ready_valid_base_taskspec():
    client = FakeModelClient(_ready(_base_spec_dict()))
    result = GoalInterpreter(client).interpret("base goal")
    assert result.status == InterpretationStatus.ready
    assert result.task_spec is not None
    assert result.task_spec.role == "AI Engineering"
    assert ActionType.send_message in result.task_spec.actions
    assert result.task_spec.authority.send_message is False
    assert result.task_spec.authority.change_stage is True


def test_ready_valid_variation_taskspec():
    payload = _ready(
        _base_spec_dict(
            role="Backend Engineering",
            actions=["prepare_followup"],
            target_stage=None,
            authority={"send_message": False, "change_stage": False},
        )
    )
    result = GoalInterpreter(FakeModelClient(payload)).interpret("variation")
    assert result.status == InterpretationStatus.ready
    assert result.task_spec is not None
    assert result.task_spec.actions == [ActionType.prepare_followup]
    assert result.task_spec.target_stage is None


def test_ask_before_send_preserves_action_and_false_authority():
    payload = _ready(
        _base_spec_dict(
            actions=["prepare_followup", "send_message"],
            target_stage=None,
            authority={"send_message": False, "change_stage": False},
        )
    )
    result = GoalInterpreter(FakeModelClient(payload)).interpret("ask before send")
    assert result.status == InterpretationStatus.ready
    assert ActionType.send_message in result.task_spec.actions
    assert result.task_spec.authority.send_message is False


def test_ask_before_stage_preserves_action_and_false_authority():
    payload = _ready(
        _base_spec_dict(
            actions=["set_stage"],
            target_stage="Interview Ready",
            authority={"send_message": False, "change_stage": False},
        )
    )
    result = GoalInterpreter(FakeModelClient(payload)).interpret("ask before stage")
    assert result.status == InterpretationStatus.ready
    assert ActionType.set_stage in result.task_spec.actions
    assert result.task_spec.authority.change_stage is False
    config, deferred = config_from_taskspec(result.task_spec, headed=False)
    assert config.target_stage is None
    assert "set_stage:deferred_until_authority_phase" in deferred


def test_explicit_send_authority_true_is_representable_but_execution_defers_send():
    payload = _ready(
        _base_spec_dict(
            actions=["prepare_followup", "send_message"],
            target_stage=None,
            authority={"send_message": True, "change_stage": False},
        )
    )
    result = GoalInterpreter(FakeModelClient(payload)).interpret("send authorized")
    assert result.task_spec.authority.send_message is True
    config, deferred = config_from_taskspec(result.task_spec, headed=False)
    assert "send_message:deferred_until_authority_phase" in deferred
    assert config.target_stage is None


def test_missing_field_rejected():
    bad = _ready(_base_spec_dict())
    del bad["task_spec"]["role"]
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.invalid_model_output


def test_unknown_taskspec_field_rejected():
    bad = _ready(_base_spec_dict(browser_selector="#x"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.invalid_model_output


def test_unsupported_action_type_rejected():
    bad = _ready(_base_spec_dict(actions=["prepare_followup", "hack_linkedin"]))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.invalid_model_output


def test_duplicate_actions_rejected():
    bad = _ready(
        _base_spec_dict(
            actions=["prepare_followup", "prepare_followup"],
            target_stage=None,
        )
    )
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.invalid_model_output


def test_contradictory_target_stage_rejected():
    bad = _ready(
        _base_spec_dict(
            actions=["prepare_followup"],
            target_stage="Interview Ready",
        )
    )
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.invalid_model_output


def test_malformed_provider_result_handled():
    client = FakeModelClient(raw_text="{not-json")
    result = GoalInterpreter(client).interpret("x")
    assert result.status == InterpretationStatus.model_error


def test_provider_exception_becomes_model_error():
    client = FakeModelClient(error=ModelClientError("model provider error: boom"))
    result = GoalInterpreter(client).interpret("x")
    assert result.status == InterpretationStatus.model_error
    assert "boom" in (result.error or "")


def test_unapproved_source_blocked_by_policy():
    bad = _ready(_base_spec_dict(source_file="../../secrets.txt"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.policy_rejected
    assert "source" in (result.error or "").lower()


def test_url_source_blocked_by_policy():
    bad = _ready(_base_spec_dict(source_file="https://example.com/file.csv"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.policy_rejected


def test_unsupported_role_blocked():
    bad = _ready(_base_spec_dict(role="Quantum Wizard"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.policy_rejected


def test_unsupported_status_blocked():
    bad = _ready(_base_spec_dict(candidate_status="Maybe"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.policy_rejected


def test_unsupported_target_stage_blocked():
    bad = _ready(_base_spec_dict(target_stage="Hired Immediately"))
    result = GoalInterpreter(FakeModelClient(bad)).interpret("x")
    assert result.status == InterpretationStatus.policy_rejected


def test_hostile_executable_fields_cannot_enter_taskspec():
    payload = {
        "status": "ready",
        "task_spec": _base_spec_dict(),
        "clarification_question": None,
        "python": "import os; os.system('rm -rf /')",
        "selector": "#submit",
    }
    result = GoalInterpreter(FakeModelClient(payload)).interpret("hostile")
    assert result.status == InterpretationStatus.invalid_model_output
    assert result.task_spec is None


def test_needs_clarification_does_not_produce_executable_plan():
    payload = {
        "status": "needs_clarification",
        "task_spec": None,
        "clarification_question": (
            "What should I do: prepare follow-ups, change TalentDesk stage, or both?"
        ),
    }
    result = GoalInterpreter(FakeModelClient(payload)).interpret("handle them")
    assert result.status == InterpretationStatus.needs_clarification
    assert result.task_spec is None
    assert result.clarification_question


def test_missing_model_configuration_handled_clearly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ModelClientError, match="LLM_API_KEY"):
        ModelConfig.from_env()


def test_fixtures_file_is_loadable_and_compact():
    path = ROOT / "examples" / "interpretation_fixtures.json"
    fixtures = json.loads(path.read_text(encoding="utf-8"))
    assert 10 <= len(fixtures) <= 14
    ids = {f["id"] for f in fixtures}
    assert "base_exact" in ids
    assert "ask_before_stage" in ids
    assert "underspecified" in ids


def test_policy_accepts_approved_source_only():
    spec = TaskSpec.model_validate(_base_spec_dict())
    approved = validate_taskspec_policy(spec)
    assert approved.source_file == APPROVED_SOURCE
