"""Phase 4 human-control unit tests (no Chromium)."""

from __future__ import annotations

import threading
from pathlib import Path

from taskwitness.browser.talentdesk import VisibleCandidate
from taskwitness.control import (
    AlwaysApprove,
    AlwaysReject,
    ApprovalDecision,
    InMemoryProgressCollector,
    RunControl,
    ScriptedApprovalProvider,
)
from taskwitness.control.progress import ProgressEvent
from taskwitness.schemas import ActionType, Authority, RunState, TaskSpec
from taskwitness.testing.fakes import FakeTalentDesk, FakeTeamMail
from taskwitness.workflow import (
    RecruitingWorkflow,
    WorkflowConfig,
    authority_snapshot,
    config_from_taskspec,
    make_operation_id,
)

ROOT = Path(__file__).resolve().parents[1]
CSV = str(ROOT / "data" / "candidates.csv")


def _seed_ai_desk() -> FakeTalentDesk:
    desk = FakeTalentDesk()
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-001",
            name="Asha Verma",
            email="asha.verma@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Phone Screen",
        )
    )
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-002",
            name="Jordan Lee",
            email="jordan.lee@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Recruiter Review",
        )
    )
    return desk


def _base_config(**overrides) -> WorkflowConfig:
    data = dict(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        prepare_followups=True,
        set_stage_requested=True,
        send_message_requested=True,
        target_stage="Interview Ready",
        authority_change_stage=True,
        authority_send_message=False,
    )
    data.update(overrides)
    return WorkflowConfig(**data)


def _run(config: WorkflowConfig, *, desk=None, mail=None, **kwargs):
    desk = desk or _seed_ai_desk()
    mail = mail or FakeTeamMail()
    result = RecruitingWorkflow(
        config,
        desk=desk,
        mail=mail,
        skip_app_wait=True,
        **kwargs,
    ).run()
    return result, desk, mail


def test_authorized_stage_executes_without_approval_request():
    provider = ScriptedApprovalProvider([])
    result, desk, _ = _run(
        _base_config(send_message_requested=False, authority_change_stage=True),
        approval_provider=provider,
    )
    assert provider.requests == []
    assert result.run_state == RunState.completed
    assert desk.stage_changes == [
        ("CAND-001", "Interview Ready"),
        ("CAND-002", "Interview Ready"),
    ]


def test_unauthorized_stage_requests_approval():
    provider = ScriptedApprovalProvider(
        [ApprovalDecision.APPROVED, ApprovalDecision.APPROVED]
    )
    result, desk, _ = _run(
        _base_config(
            prepare_followups=False,
            send_message_requested=False,
            authority_change_stage=False,
        ),
        approval_provider=provider,
    )
    assert len(provider.requests) == 2
    assert all(r.action is ActionType.set_stage for r in provider.requests)
    assert provider.requests[0].target == "Interview Ready"
    assert "did not grant autonomous stage-change authority" in provider.requests[0].reason
    assert result.run_state == RunState.completed
    assert len(desk.stage_changes) == 2


def test_approved_stage_action_executes():
    result, desk, _ = _run(
        _base_config(
            prepare_followups=False,
            send_message_requested=False,
            authority_change_stage=False,
        ),
        approval_provider=ScriptedApprovalProvider(
            [ApprovalDecision.APPROVED, ApprovalDecision.APPROVED]
        ),
    )
    assert all(c.stage_update and c.stage_update.ok for c in result.candidate_results)
    assert all(c.stage_update.approval == "approved" for c in result.candidate_results)
    assert desk.stage_changes


def test_rejected_stage_action_does_not_execute():
    provider = ScriptedApprovalProvider(
        [ApprovalDecision.REJECTED, ApprovalDecision.REJECTED]
    )
    result, desk, _ = _run(
        _base_config(
            prepare_followups=False,
            send_message_requested=False,
            authority_change_stage=False,
        ),
        approval_provider=provider,
    )
    assert desk.stage_changes == []
    assert result.run_state == RunState.partial
    assert all(c.stage_update and c.stage_update.incomplete for c in result.candidate_results)
    assert all(c.stage_update.approval == "rejected" for c in result.candidate_results)


def test_authorized_send_executes_without_approval_request():
    provider = ScriptedApprovalProvider([])
    result, _, mail = _run(
        _base_config(
            set_stage_requested=False,
            target_stage=None,
            authority_send_message=True,
        ),
        approval_provider=provider,
    )
    assert provider.requests == []
    assert result.run_state == RunState.completed
    assert len(mail.send_calls) == 2
    assert len(mail.sent) == 2
    assert len(mail.drafts) == 0


def test_unauthorized_send_requests_approval():
    provider = ScriptedApprovalProvider(
        [ApprovalDecision.APPROVED, ApprovalDecision.APPROVED]
    )
    result, _, mail = _run(
        _base_config(set_stage_requested=False, target_stage=None),
        approval_provider=provider,
    )
    assert len(provider.requests) == 2
    assert all(r.action is ActionType.send_message for r in provider.requests)
    assert provider.requests[0].target.endswith("@example.test")
    assert "requires approval before external action" in provider.requests[0].reason
    assert provider.requests[0].operation_id
    assert result.run_state == RunState.completed
    assert len(mail.sent) == 2


def test_approved_send_executes():
    result, _, mail = _run(
        _base_config(set_stage_requested=False, target_stage=None),
        approval_provider=AlwaysApprove(),
    )
    assert all(c.send and c.send.ok for c in result.candidate_results)
    assert len(mail.send_calls) == 2


def test_rejected_send_does_not_execute():
    result, _, mail = _run(
        _base_config(set_stage_requested=False, target_stage=None),
        approval_provider=AlwaysReject(),
    )
    assert mail.send_calls == []
    assert len(mail.drafts) == 2
    assert len(mail.sent) == 0
    assert result.run_state == RunState.partial
    assert all(c.send and c.send.incomplete for c in result.candidate_results)
    assert all(c.send.approval == "rejected" for c in result.candidate_results)


def test_rejection_does_not_mutate_taskspec_authority():
    spec = TaskSpec(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup, ActionType.send_message],
        target_stage=None,
        authority=Authority(send_message=False, change_stage=False),
    )
    before = authority_snapshot(spec)
    config, _ = config_from_taskspec(spec, headed=False)
    _run(config, approval_provider=AlwaysReject())
    assert spec.authority.send_message is False
    assert spec.authority.change_stage is False
    assert authority_snapshot(spec) == before


def test_rejection_yields_partial_when_other_work_completed():
    result, desk, mail = _run(
        _base_config(),
        approval_provider=AlwaysReject(),
    )
    assert result.run_state == RunState.partial
    assert len(desk.stage_changes) == 2
    assert len(mail.drafts) == 2
    assert mail.send_calls == []
    assert all(c.stage_update and c.stage_update.ok for c in result.candidate_results)
    assert all(c.draft and c.draft.ok for c in result.candidate_results)
    assert all(c.send and c.send.incomplete for c in result.candidate_results)


def test_successful_requested_work_yields_completed():
    result, _, mail = _run(
        _base_config(authority_send_message=True),
        approval_provider=AlwaysApprove(),
    )
    assert result.run_state == RunState.completed
    assert result.ok
    assert len(mail.sent) == 2


def test_pause_prevents_next_side_effect_and_resume_allows_it():
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    control = RunControl()
    config = _base_config(
        prepare_followups=False,
        send_message_requested=False,
        authority_change_stage=True,
    )
    control.request_pause()
    started = threading.Event()
    finished = threading.Event()
    box: dict = {}

    def worker() -> None:
        started.set()
        box["result"] = RecruitingWorkflow(
            config,
            run_control=control,
            approval_provider=AlwaysApprove(),
            desk=desk,
            mail=mail,
            skip_app_wait=True,
        ).run()
        finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=2)
    for _ in range(400):
        if control.state == RunState.paused:
            break
        threading.Event().wait(0.01)
    assert control.state == RunState.paused
    assert desk.stage_changes == []
    assert desk.opened == []

    control.resume()
    assert finished.wait(timeout=5)
    thread.join(timeout=1)
    assert desk.stage_changes == [
        ("CAND-001", "Interview Ready"),
        ("CAND-002", "Interview Ready"),
    ]
    assert box["result"].run_state == RunState.completed


def test_progress_reports_paused_running_transitions():
    collector = InMemoryProgressCollector()
    control = RunControl(
        on_state_change=lambda state: collector.emit(
            ProgressEvent(
                run_state=state,
                message=f"state={state.value}",
                event_type="state",
            )
        )
    )
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    config = _base_config(
        prepare_followups=False,
        send_message_requested=False,
    )
    control.request_pause()
    done = threading.Event()

    def worker() -> None:
        RecruitingWorkflow(
            config,
            run_control=control,
            approval_provider=AlwaysApprove(),
            progress=collector,
            desk=desk,
            mail=mail,
            skip_app_wait=True,
        ).run()
        done.set()

    threading.Thread(target=worker).start()
    for _ in range(400):
        if control.state == RunState.paused:
            break
        threading.Event().wait(0.01)
    assert control.state == RunState.paused
    control.resume()
    assert done.wait(timeout=5)
    states = collector.states()
    assert RunState.paused in states
    assert RunState.running in states
    assert RunState.completed in states


def test_progress_events_emitted_in_meaningful_order():
    collector = InMemoryProgressCollector()
    result, _, _ = _run(
        _base_config(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        progress=collector,
    )
    assert result.run_state == RunState.completed
    messages = collector.messages()
    assert any("Matched 2" in m for m in messages)
    assert any("Opened candidate" in m for m in messages)
    assert any("Stage changed" in m for m in messages)
    assert any("Draft" in m and "prepared" in m for m in messages)
    assert any("Follow-up sent" in m for m in messages)


def test_approval_event_contains_concrete_action_target_reason():
    provider = ScriptedApprovalProvider(
        [ApprovalDecision.REJECTED, ApprovalDecision.REJECTED]
    )
    collector = InMemoryProgressCollector()
    _run(
        _base_config(set_stage_requested=False, target_stage=None),
        approval_provider=provider,
        progress=collector,
    )
    assert provider.requests
    req = provider.requests[0]
    assert req.action is ActionType.send_message
    assert req.candidate_id == "CAND-001"
    assert req.target == "asha.verma@example.test"
    assert req.reason
    assert req.operation_id
    assert any(e.event_type == "approval_required" for e in collector.events)
    assert any(e.event_type == "approval_rejected" for e in collector.events)


def test_false_authority_stage_cannot_execute_without_approval():
    provider = ScriptedApprovalProvider(
        [ApprovalDecision.REJECTED, ApprovalDecision.REJECTED]
    )
    result, desk, _ = _run(
        _base_config(
            prepare_followups=False,
            send_message_requested=False,
            authority_change_stage=False,
        ),
        approval_provider=provider,
    )
    assert desk.stage_changes == []
    assert len(provider.requests) == 2
    assert result.run_state == RunState.partial


def test_send_cannot_occur_before_approval_when_authority_false():
    gate = threading.Event()
    seen_before_decision = threading.Event()

    class GatedProvider:
        def __init__(self) -> None:
            self.requests = []

        def request_approval(self, request):
            self.requests.append(request)
            seen_before_decision.set()
            assert gate.wait(timeout=2)
            return ApprovalDecision.APPROVED

    mail = FakeTeamMail()
    provider = GatedProvider()
    done = threading.Event()

    def worker() -> None:
        RecruitingWorkflow(
            _base_config(set_stage_requested=False, target_stage=None),
            approval_provider=provider,
            desk=_seed_ai_desk(),
            mail=mail,
            skip_app_wait=True,
        ).run()
        done.set()

    threading.Thread(target=worker).start()
    assert seen_before_decision.wait(timeout=2)
    assert mail.send_calls == []
    gate.set()
    assert done.wait(timeout=5)
    assert len(mail.send_calls) == 2


def test_send_without_known_draft_is_blocked():
    result, _, mail = _run(
        _base_config(
            prepare_followups=False,
            set_stage_requested=False,
            target_stage=None,
            send_message_requested=True,
            authority_send_message=True,
        ),
        approval_provider=AlwaysApprove(),
    )
    assert mail.send_calls == []
    assert result.run_state == RunState.partial
    assert all(c.send and c.send.incomplete for c in result.candidate_results)
    assert all(
        "no known corresponding draft" in (c.send.detail or "")
        for c in result.candidate_results
    )


def test_ambiguous_send_is_not_retried():
    mail = FakeTeamMail()
    mail.fail_send_unknown_once = True
    result, _, mail = _run(
        _base_config(
            set_stage_requested=False,
            target_stage=None,
            authority_send_message=True,
        ),
        mail=mail,
        approval_provider=AlwaysApprove(),
    )
    first = result.candidate_results[0]
    assert first.send is not None
    assert first.send.unknown is True
    assert first.send.ok is False
    # Ambiguous message id appears exactly once in send_calls (no blind retry).
    ambiguous_id = mail.send_calls[0]
    assert mail.send_calls.count(ambiguous_id) == 1


def test_config_from_taskspec_preserves_false_authority_actions():
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
        authority=Authority(send_message=False, change_stage=False),
    )
    config, deferred = config_from_taskspec(spec, headed=False)
    assert deferred == []
    assert config.set_stage_requested is True
    assert config.send_message_requested is True
    assert config.target_stage == "Interview Ready"
    assert config.authority_change_stage is False
    assert config.authority_send_message is False


def test_operation_id_preserved_from_draft_to_send():
    result, _, mail = _run(
        _base_config(
            set_stage_requested=False,
            target_stage=None,
            authority_send_message=True,
        ),
        approval_provider=AlwaysApprove(),
    )
    for c in result.candidate_results:
        expected = make_operation_id(candidate_id=c.candidate_id, role="AI Engineering")
        assert c.draft and c.draft.operation_id == expected
        assert c.send and c.send.operation_id == expected
        assert c.send.message_id in mail.sent
        assert mail.sent[c.send.message_id].operation_id == expected
