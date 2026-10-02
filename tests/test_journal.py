"""Phase 5 durable journal unit tests (no Chromium)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskwitness.journal import (
    ActionState,
    AmbiguousOperationOutcome,
    InspectionResult,
    Journal,
    make_action_key,
    resolve_unknown_send,
)
from taskwitness.journal.keys import (
    prepare_followup_payload,
    send_message_payload,
    set_stage_payload,
)
from taskwitness.journal.store import IllegalTransitionError
from taskwitness.schemas import ActionType, Authority, TaskSpec


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    j = Journal(tmp_path / "journal.sqlite3")
    yield j
    j.close()


def _spec() -> TaskSpec:
    return TaskSpec(
        source_file="data/candidates.csv",
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup, ActionType.send_message],
        target_stage=None,
        authority=Authority(send_message=False, change_stage=False),
    )


def test_journal_creates_durable_run(journal: Journal):
    run = journal.create_run(task_spec=_spec(), goal_summary="base")
    assert run.run_id
    assert run.goal_summary == "base"
    loaded = journal.load_run(run.run_id)
    assert loaded is not None
    assert loaded.run_id == run.run_id


def test_journal_persists_taskspec_snapshot(journal: Journal):
    spec = _spec()
    run = journal.create_run(task_spec=spec)
    loaded = journal.load_task_spec(run.run_id)
    assert loaded.model_dump() == spec.model_dump()
    assert loaded.authority.send_message is False


def test_planned_action_persists(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    action = journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    assert action.state is ActionState.planned
    assert action.attempt_count == 0
    assert journal.get_action(key) == action


def test_action_key_deterministic_for_same_logical_action():
    a = make_action_key(
        run_id="r1",
        action_type="set_stage",
        candidate_id="CAND-001",
        payload=set_stage_payload(target_stage="Interview Ready"),
    )
    b = make_action_key(
        run_id="r1",
        action_type="set_stage",
        candidate_id="CAND-001",
        payload=set_stage_payload(target_stage=" Interview Ready "),
    )
    assert a == b


def test_action_key_changes_for_different_payload():
    a = make_action_key(
        run_id="r1",
        action_type="set_stage",
        candidate_id="CAND-001",
        payload=set_stage_payload(target_stage="Interview Ready"),
    )
    b = make_action_key(
        run_id="r1",
        action_type="set_stage",
        candidate_id="CAND-001",
        payload=set_stage_payload(target_stage="Offer"),
    )
    assert a != b


def test_in_progress_increments_attempt_before_effect(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    mid = journal.mark_in_progress(key)
    assert mid.state is ActionState.in_progress
    assert mid.attempt_count == 1


def test_normal_success_path(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    done = journal.mark_succeeded(key, note="sent")
    assert done.state is ActionState.succeeded
    assert done.attempt_count == 1


def test_rejection_has_zero_attempts(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    rejected = journal.mark_rejected(key, note="human rejected")
    assert rejected.state is ActionState.rejected
    assert rejected.attempt_count == 0


def test_illegal_terminal_transition_rejected(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_succeeded(key)
    with pytest.raises(IllegalTransitionError):
        journal.mark_in_progress(key)


def test_journal_survives_close_reopen(tmp_path: Path):
    path = tmp_path / "j.sqlite3"
    j1 = Journal(path)
    run = j1.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    j1.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    j1.mark_in_progress(key)
    j1.mark_unknown(key, error="ack lost")
    j1.close()

    j2 = Journal(path)
    action = j2.get_action(key)
    assert action is not None
    assert action.state is ActionState.unknown
    assert action.attempt_count == 1
    assert action.operation_id == "op-1"
    j2.close()


class _Inspector:
    def __init__(self, result: InspectionResult) -> None:
        self.result = result
        self.calls = 0

    def inspect_sent_operation(self, operation_id: str) -> InspectionResult:
        self.calls += 1
        return self.result


def test_unknown_plus_one_match_recovers(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost")
    decision = resolve_unknown_send(
        journal,
        key,
        _Inspector(InspectionResult(match_count=1, message_id="MAIL-0001")),
    )
    assert decision.decision == "recovered"
    assert decision.action.state is ActionState.recovered
    assert decision.action.attempt_count == 1
    assert decision.should_retry is False


def test_unknown_zero_match_allows_controlled_retry(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost")
    decision = resolve_unknown_send(
        journal,
        key,
        _Inspector(InspectionResult(match_count=0)),
    )
    assert decision.decision == "retry"
    assert decision.should_retry is True
    assert decision.action.state is ActionState.unknown


def test_controlled_retry_limited(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost")
    # Second attempt already recorded.
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost again")
    decision = resolve_unknown_send(
        journal,
        key,
        _Inspector(InspectionResult(match_count=0)),
        max_attempts=2,
    )
    assert decision.decision == "blocked"
    assert decision.should_retry is False
    assert decision.action.attempt_count == 2


def test_multiple_matches_blocked(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost")
    decision = resolve_unknown_send(
        journal,
        key,
        _Inspector(InspectionResult(match_count=2)),
    )
    assert decision.decision == "blocked"
    assert decision.action.state is ActionState.blocked


def test_inspection_unavailable_blocked(journal: Journal):
    run = journal.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    journal.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    journal.mark_in_progress(key)
    journal.mark_unknown(key, error="ack lost")
    decision = resolve_unknown_send(
        journal,
        key,
        _Inspector(InspectionResult(match_count=0, available=False, detail="down")),
    )
    assert decision.decision == "blocked"
    assert "could not be inspected" in decision.note.lower() or "could not be" in decision.note


def test_reopen_unknown_and_recover_without_send(tmp_path: Path):
    path = tmp_path / "j.sqlite3"
    j1 = Journal(path)
    run = j1.create_run(task_spec=_spec())
    key = make_action_key(
        run_id=run.run_id,
        action_type="send_message",
        candidate_id="CAND-001",
        payload=send_message_payload(operation_id="op-1"),
    )
    j1.plan_action(
        action_key=key,
        run_id=run.run_id,
        candidate_id="CAND-001",
        action_type="send_message",
        payload=send_message_payload(operation_id="op-1"),
        operation_id="op-1",
    )
    j1.mark_in_progress(key)
    j1.mark_unknown(key, error="ack lost")
    j1.close()

    send_calls: list[str] = []

    class TrackingInspector:
        def inspect_sent_operation(self, operation_id: str) -> InspectionResult:
            return InspectionResult(match_count=1, message_id="MAIL-0001")

    j2 = Journal(path)
    recoverable = j2.find_recoverable_actions(run.run_id)
    assert len(recoverable) == 1
    decision = resolve_unknown_send(j2, key, TrackingInspector())
    assert decision.decision == "recovered"
    assert send_calls == []
    assert decision.action.attempt_count == 1
    j2.close()


def test_ambiguous_exception_message():
    exc = AmbiguousOperationOutcome("may have happened", operation_id="op-1")
    assert "may have happened" in str(exc)
    assert exc.operation_id == "op-1"


def test_prepare_payload_included_in_key_material():
    p = prepare_followup_payload(
        operation_id="op",
        recipient="Asha.Verma@example.test",
        role="AI Engineering",
    )
    assert p["recipient"] == "asha.verma@example.test"
    assert "operation_id" in json.dumps(p)
