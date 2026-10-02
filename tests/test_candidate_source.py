"""Candidate CSV source and deterministic helper tests (no browser)."""

from __future__ import annotations

from pathlib import Path

from taskwitness.candidate_source import filter_candidates, load_candidates
from taskwitness.schemas import ActionType, Authority, TaskSpec
from taskwitness.workflow import (
    config_from_taskspec,
    followup_body,
    followup_subject,
    make_operation_id,
)

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "candidates.csv"


def test_csv_loads_six_candidates():
    rows = load_candidates(CSV)
    assert len(rows) == 6
    assert rows[0].candidate_id == "CAND-001"


def test_filter_ai_engineering_shortlisted():
    selected = filter_candidates(
        load_candidates(CSV),
        role="AI Engineering",
        candidate_status="Shortlisted",
    )
    assert [c.candidate_id for c in selected] == ["CAND-001", "CAND-002"]


def test_filter_backend_shortlisted():
    selected = filter_candidates(
        load_candidates(CSV),
        role="Backend Engineering",
        candidate_status="Shortlisted",
    )
    assert [c.candidate_id for c in selected] == ["CAND-003", "CAND-005"]


def test_followup_content_is_deterministic():
    candidate = load_candidates(CSV)[0]
    assert followup_subject(candidate.role) == "Interview follow-up — AI Engineering"
    body = followup_body(candidate)
    assert "Hi Asha," in body
    assert "AI Engineering" in body
    assert "synthetic TaskWitness demo message" in body


def test_operation_id_is_stable_and_not_random():
    a = make_operation_id(candidate_id="CAND-001", role="AI Engineering")
    b = make_operation_id(candidate_id="CAND-001", role="AI Engineering")
    c = make_operation_id(candidate_id="CAND-002", role="AI Engineering")
    assert a == b
    assert a != c
    assert a.startswith("tw-prepare_followup-cand-001-")


def test_taskspec_send_message_preserved_with_false_authority():
    spec = TaskSpec(
        source_file="data/candidates.csv",
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[
            ActionType.prepare_followup,
            ActionType.set_stage,
            ActionType.send_message,
        ],
        target_stage="Interview Ready",
        authority=Authority(send_message=False, change_stage=True),
    )
    config, deferred = config_from_taskspec(spec, headed=False)
    assert deferred == []
    assert config.prepare_followups is True
    assert config.target_stage == "Interview Ready"
    assert config.send_message_requested is True
    assert config.authority_send_message is False
    assert config.authority_change_stage is True


def test_set_stage_with_change_stage_true_may_execute():
    spec = TaskSpec(
        source_file="data/candidates.csv",
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.set_stage],
        target_stage="Interview Ready",
        authority=Authority(send_message=False, change_stage=True),
    )
    config, deferred = config_from_taskspec(spec, headed=False)
    assert config.target_stage == "Interview Ready"
    assert config.set_stage_requested is True
    assert config.authority_change_stage is True
    assert deferred == []


def test_set_stage_with_change_stage_false_remains_requested_for_approval():
    spec = TaskSpec(
        source_file="data/candidates.csv",
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.set_stage],
        target_stage="Interview Ready",
        authority=Authority(send_message=False, change_stage=False),
    )
    config, deferred = config_from_taskspec(spec, headed=False)
    assert config.target_stage == "Interview Ready"
    assert config.set_stage_requested is True
    assert config.authority_change_stage is False
    assert deferred == []
    assert ActionType.set_stage in spec.actions


def test_send_message_with_send_authority_false_remains_requested_for_approval():
    spec = TaskSpec(
        source_file="data/candidates.csv",
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup, ActionType.send_message],
        target_stage=None,
        authority=Authority(send_message=False, change_stage=False),
    )
    config, deferred = config_from_taskspec(spec, headed=False)
    assert config.prepare_followups is True
    assert config.send_message_requested is True
    assert config.authority_send_message is False
    assert ActionType.send_message in spec.actions
    assert deferred == []
