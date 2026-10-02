"""Deterministic recruiting browser workflow with human control + durable journal.

AI never executes side effects here. Authority gates, pause checkpoints, and
write-ahead journal recording sit between validated intent and browser mutations.

Ambiguous send outcomes are reconciled against TeamMail Sent state (Phase 5).
No final evidence package (Phase 6). No final operator UI (Phase 7).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from taskwitness.browser.session import BrowserSession
from taskwitness.browser.talentdesk import TalentDeskBrowser, VisibleCandidate
from taskwitness.browser.teammail import SendResult, TeamMailBrowser
from taskwitness.candidate_source import (
    SourceCandidate,
    filter_candidates,
    load_candidates,
)
from taskwitness.control.approval import (
    AlwaysApprove,
    ApprovalDecision,
    ApprovalProvider,
    ApprovalRequest,
    new_approval_id,
)
from taskwitness.control.progress import ProgressEvent, ProgressSink
from taskwitness.control.run_control import RunControl
from taskwitness.journal.keys import (
    make_action_key,
    prepare_followup_payload,
    send_message_payload,
    set_stage_payload,
)
from taskwitness.journal.recovery import BrowserSentInspector, resolve_unknown_send
from taskwitness.journal.store import Journal
from taskwitness.journal.types import ActionState
from taskwitness.schemas import ActionType, Authority, RunState, TaskSpec


class TalentDeskOps(Protocol):
    def filter_candidates(self, *, search: str = "", role: str = "") -> None: ...

    def open_candidate(self, candidate_id: str) -> None: ...

    def read_candidate(self) -> VisibleCandidate: ...

    def set_stage(self, stage: str) -> str: ...


class TeamMailOps(Protocol):
    def find_draft_by_operation_id(self, operation_id: str) -> str | None: ...

    def open_draft(self, message_id: str) -> None: ...

    def read_draft(self): ...

    def open_compose(self) -> None: ...

    def fill_compose(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        operation_id: str = "",
    ) -> None: ...

    def save_draft(self) -> str: ...

    def send_draft(
        self,
        message_id: str,
        *,
        expected_operation_id: str | None = None,
        expected_recipient: str | None = None,
    ) -> SendResult: ...

    def find_sent_by_operation_id(self, operation_id: str) -> str | None: ...

    def count_sent_by_operation_id(self, operation_id: str) -> int: ...


@dataclass
class WorkflowConfig:
    """Explicit workflow input derived from TaskSpec or CLI.

    Requested actions and authority remain separate fields.
    CLI-built configs without TaskSpec never enable send_message.
    """

    role: str
    candidate_status: str
    source_file: str = "data/candidates.csv"
    prepare_followups: bool = True
    set_stage_requested: bool = False
    send_message_requested: bool = False
    target_stage: Optional[str] = None
    authority_change_stage: bool = False
    authority_send_message: bool = False
    base_url: str = "http://127.0.0.1:8000"
    headed: bool = True
    slow_mo_ms: int = 0
    task_spec_json: Optional[str] = None
    goal_summary: Optional[str] = None


@dataclass
class ActionOutcome:
    name: str
    ok: bool
    detail: str = ""
    message_id: Optional[str] = None
    operation_id: Optional[str] = None
    approval: Optional[str] = None  # approved | rejected | None
    incomplete: bool = False
    unknown: bool = False
    recovered: bool = False
    action_key: Optional[str] = None
    attempt_count: Optional[int] = None


@dataclass
class CandidateRunResult:
    candidate_id: str
    precondition_ok: Optional[bool] = None
    stage_update: Optional[ActionOutcome] = None
    draft: Optional[ActionOutcome] = None
    send: Optional[ActionOutcome] = None
    incomplete: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if self.precondition_ok is False:
            return False
        for outcome in (self.stage_update, self.draft, self.send):
            if outcome is None:
                continue
            if outcome.recovered or outcome.ok:
                continue
            if outcome.incomplete:
                continue
            return False
        return True

    @property
    def has_incomplete(self) -> bool:
        if self.incomplete:
            return True
        for outcome in (self.stage_update, self.draft, self.send):
            if outcome is not None and outcome.incomplete:
                return True
        return False


@dataclass
class BrowserRunResult:
    selected_candidate_ids: list[str]
    candidate_results: list[CandidateRunResult]
    run_state: RunState = RunState.completed
    error: Optional[str] = None
    run_id: Optional[str] = None
    deferred_actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.run_state == RunState.completed and self.error is None

    @property
    def has_incomplete(self) -> bool:
        return any(r.has_incomplete for r in self.candidate_results)


def followup_subject(role: str) -> str:
    return f"Interview follow-up — {role}"


def followup_body(candidate: SourceCandidate) -> str:
    return (
        f"Hi {candidate.first_name},\n\n"
        f"Thanks for your interest in the {candidate.role} role.\n"
        "We'd like to continue the conversation with an interview.\n\n"
        "This is a synthetic TaskWitness demo message.\n\n"
        "Regards,\n"
        "Talent Team\n"
    )


def make_operation_id(*, candidate_id: str, role: str, action: str = "prepare_followup") -> str:
    """Deterministic logical operation id for a follow-up draft/send.

    The same id is preserved from draft → sent. Send does not generate a new id.
    """
    normalized_role = re.sub(r"\s+", "-", role.strip().lower())
    material = f"{action}|{candidate_id}|{normalized_role}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:10]
    return f"tw-{action}-{candidate_id.lower()}-{digest}"


def identities_match(source: SourceCandidate, visible: VisibleCandidate) -> tuple[bool, str]:
    checks = [
        ("candidate_id", source.candidate_id, visible.candidate_id),
        ("email", source.email, visible.email),
        ("role", source.role, visible.role),
        ("status", source.status, visible.status),
    ]
    mismatches = [
        f"{field}: source={expected!r} visible={actual!r}"
        for field, expected, actual in checks
        if expected != actual
    ]
    if mismatches:
        return False, "; ".join(mismatches)
    return True, "identity fields match"


def wait_for_app(base_url: str, *, timeout_s: float = 20.0) -> None:
    import socket
    import time
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"demo application unreachable at {base_url}: {last_error}")


def config_from_taskspec(
    spec: TaskSpec,
    *,
    headed: bool = True,
    base_url: str = "http://127.0.0.1:8000",
) -> tuple[WorkflowConfig, list[str]]:
    """Map TaskSpec → WorkflowConfig.

    Authority flags are copied, never rewritten. False authority does not
    strip the requested action — approval is obtained at the side effect.
    source_file must resolve to the approved candidates.csv before execution.
    """
    from taskwitness.interpretation.policy import resolve_execution_source

    source_path = resolve_execution_source(spec.source_file)
    cfg = WorkflowConfig(
        source_file=str(source_path),
        role=spec.role,
        candidate_status=spec.candidate_status,
        prepare_followups=ActionType.prepare_followup in spec.actions,
        set_stage_requested=ActionType.set_stage in spec.actions,
        send_message_requested=ActionType.send_message in spec.actions,
        target_stage=spec.target_stage,
        authority_change_stage=spec.authority.change_stage,
        authority_send_message=spec.authority.send_message,
        base_url=base_url,
        headed=headed,
        task_spec_json=spec.model_dump_json(),
        goal_summary=f"{spec.candidate_status} {spec.role}",
    )
    return cfg, []


def authority_snapshot(spec: TaskSpec) -> Authority:
    """Return a copy of TaskSpec authority for inspectability after a run."""
    return Authority(
        send_message=spec.authority.send_message,
        change_stage=spec.authority.change_stage,
    )


def _task_spec_snapshot(config: WorkflowConfig) -> dict[str, Any]:
    if config.task_spec_json:
        return json.loads(config.task_spec_json)
    actions: list[str] = []
    if config.prepare_followups:
        actions.append(ActionType.prepare_followup.value)
    if config.set_stage_requested:
        actions.append(ActionType.set_stage.value)
    if config.send_message_requested:
        actions.append(ActionType.send_message.value)
    return {
        "source_file": config.source_file,
        "role": config.role,
        "candidate_status": config.candidate_status,
        "actions": actions or [ActionType.prepare_followup.value],
        "target_stage": config.target_stage,
        "authority": {
            "send_message": config.authority_send_message,
            "change_stage": config.authority_change_stage,
        },
    }


class RecruitingWorkflow:
    def __init__(
        self,
        config: WorkflowConfig,
        *,
        run_control: RunControl | None = None,
        approval_provider: ApprovalProvider | None = None,
        progress: ProgressSink | None = None,
        desk: TalentDeskOps | None = None,
        mail: TeamMailOps | None = None,
        skip_app_wait: bool = False,
        journal: Journal | None = None,
        journal_path: Path | str | None = None,
        close_journal: bool | None = None,
    ) -> None:
        self.config = config
        self.control = run_control or RunControl()
        self.approvals = approval_provider or AlwaysApprove()
        self.progress = progress
        self._injected_desk = desk
        self._injected_mail = mail
        self._skip_app_wait = skip_app_wait or (desk is not None and mail is not None)
        self._owns_journal = journal is None
        self.journal = journal or Journal(journal_path)
        self._close_journal = self._owns_journal if close_journal is None else close_journal
        self._run_id: str | None = None

    def emit(
        self,
        message: str,
        *,
        run_state: RunState | None = None,
        candidate_id: str | None = None,
        action: str | None = None,
        event_type: str = "info",
    ) -> None:
        if self.progress is None:
            return
        state = run_state if run_state is not None else self.control.state
        self.progress.emit(
            ProgressEvent(
                run_state=state,
                message=message,
                candidate_id=candidate_id,
                action=action,
                event_type=event_type,
            )
        )

    def _checkpoint(self) -> None:
        self.control.wait_if_paused()

    def _request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.control.begin_awaiting_approval()
        self.emit(
            f"Approval required before {_approval_action_phrase(request)}.",
            run_state=RunState.awaiting_approval,
            candidate_id=request.candidate_id,
            action=request.action.value,
            event_type="approval_required",
        )
        try:
            decision = self.approvals.request_approval(request)
        finally:
            self.control.end_awaiting_approval()
        self.emit(
            f"Approval {decision.value} for {request.action.value}.",
            run_state=self.control.state,
            candidate_id=request.candidate_id,
            action=request.action.value,
            event_type=f"approval_{decision.value}",
        )
        return decision

    def run(self) -> BrowserRunResult:
        self.control.set_state(RunState.running)
        self.emit("Workflow started.", run_state=RunState.running)

        run_record = self.journal.create_run(
            task_spec=_task_spec_snapshot(self.config),
            goal_summary=self.config.goal_summary,
            state=RunState.running.value,
        )
        self._run_id = run_record.run_id

        try:
            return self._run_body()
        finally:
            if self._close_journal:
                self.journal.close()

    def _run_body(self) -> BrowserRunResult:
        assert self._run_id is not None

        if not self._skip_app_wait:
            try:
                wait_for_app(self.config.base_url)
            except RuntimeError as exc:
                self.control.mark_terminal(RunState.failed)
                self.journal.finish_run(self._run_id, state=RunState.failed.value)
                self.emit(str(exc), run_state=RunState.failed, event_type="error")
                return BrowserRunResult(
                    selected_candidate_ids=[],
                    candidate_results=[],
                    run_state=RunState.failed,
                    error=str(exc),
                    run_id=self._run_id,
                )

        source_path = Path(self.config.source_file)
        try:
            from taskwitness.interpretation.policy import (
                PolicyRejection,
                resolve_execution_source,
            )

            source_path = resolve_execution_source(str(source_path))
        except PolicyRejection as exc:
            err = str(exc.message)
            self.control.mark_terminal(RunState.failed)
            self.journal.finish_run(self._run_id, state=RunState.failed.value)
            self.emit(err, run_state=RunState.failed, event_type="error")
            return BrowserRunResult(
                selected_candidate_ids=[],
                candidate_results=[],
                run_state=RunState.failed,
                error=err,
                run_id=self._run_id,
            )
        if not source_path.is_file():
            err = f"source file not found: {source_path}"
            self.control.mark_terminal(RunState.failed)
            self.journal.finish_run(self._run_id, state=RunState.failed.value)
            self.emit(err, run_state=RunState.failed, event_type="error")
            return BrowserRunResult(
                selected_candidate_ids=[],
                candidate_results=[],
                run_state=RunState.failed,
                error=err,
                run_id=self._run_id,
            )

        selected = filter_candidates(
            load_candidates(source_path),
            role=self.config.role,
            candidate_status=self.config.candidate_status,
        )
        selected_ids = [c.candidate_id for c in selected]
        self.emit(
            f"Matched {len(selected_ids)} "
            f"{self.config.candidate_status.lower()} {self.config.role} candidates.",
            run_state=RunState.running,
        )
        results: list[CandidateRunResult] = []

        try:
            if self._injected_desk is not None and self._injected_mail is not None:
                for candidate in selected:
                    self._checkpoint()
                    results.append(
                        self._process_candidate(
                            self._injected_desk,
                            self._injected_mail,
                            candidate,
                        )
                    )
            else:
                with BrowserSession(
                    base_url=self.config.base_url,
                    headed=self.config.headed,
                    slow_mo_ms=self.config.slow_mo_ms,
                ) as session:
                    desk = TalentDeskBrowser(session)
                    mail = TeamMailBrowser(session)
                    for candidate in selected:
                        self._checkpoint()
                        results.append(self._process_candidate(desk, mail, candidate))
        except Exception as exc:  # noqa: BLE001
            err = f"browser workflow failed: {exc}"
            self.control.mark_terminal(RunState.failed)
            self.journal.finish_run(self._run_id, state=RunState.failed.value)
            self.emit(err, run_state=RunState.failed, event_type="error")
            return BrowserRunResult(
                selected_candidate_ids=selected_ids,
                candidate_results=results,
                run_state=RunState.failed,
                error=err,
                run_id=self._run_id,
            )

        run_state = self._finalize_state(results)
        self.control.mark_terminal(run_state)
        self.journal.finish_run(self._run_id, state=run_state.value)
        self.emit(
            f"Workflow finished ({run_state.value}).",
            run_state=run_state,
            event_type="finished",
        )
        return BrowserRunResult(
            selected_candidate_ids=selected_ids,
            candidate_results=results,
            run_state=run_state,
            run_id=self._run_id,
        )

    def _finalize_state(self, results: list[CandidateRunResult]) -> RunState:
        # Unresolved unknown (not recovered) should not count as clean success.
        unresolved_unknown = any(
            r.send is not None and r.send.unknown and not r.send.recovered
            for r in results
        )
        if unresolved_unknown:
            if any(r.has_incomplete or (r.send and r.send.recovered) or (r.send and r.send.ok)
                   or (r.stage_update and r.stage_update.ok) or (r.draft and r.draft.ok)
                   for r in results):
                return RunState.partial
            return RunState.failed
        hard_errors = [
            r
            for r in results
            if r.error and not str(r.error).startswith("precondition blocked:")
        ]
        if hard_errors:
            return RunState.failed
        if any(r.has_incomplete for r in results):
            return RunState.partial
        if any(r.precondition_ok is False for r in results):
            return RunState.partial
        if any(not r.ok for r in results):
            return RunState.failed
        return RunState.completed

    def _process_candidate(
        self,
        desk: TalentDeskOps,
        mail: TeamMailOps,
        candidate: SourceCandidate,
    ) -> CandidateRunResult:
        result = CandidateRunResult(candidate_id=candidate.candidate_id)
        try:
            self._checkpoint()
            desk.filter_candidates(search=candidate.candidate_id, role=candidate.role)
            desk.open_candidate(candidate.candidate_id)
            self.emit(
                "Opened candidate in TalentDesk.",
                candidate_id=candidate.candidate_id,
            )
            visible = desk.read_candidate()
            matched, detail = identities_match(candidate, visible)
            result.precondition_ok = matched
            if not matched:
                result.error = f"precondition blocked: {detail}"
                self.emit(
                    f"Identity check failed: {detail}",
                    candidate_id=candidate.candidate_id,
                    event_type="blocked",
                )
                return result
            self.emit(
                "Candidate identity checked.",
                candidate_id=candidate.candidate_id,
            )

            if self.config.set_stage_requested and self.config.target_stage:
                result.stage_update = self._maybe_set_stage(
                    desk, candidate, self.config.target_stage
                )
                if result.stage_update.incomplete:
                    result.incomplete.append("set_stage")

            if self.config.prepare_followups:
                self._checkpoint()
                result.draft = self._prepare_followup(mail, candidate)
                if result.draft is not None and not result.draft.ok:
                    return result

            if self.config.send_message_requested:
                result.send = self._maybe_send(mail, candidate, result.draft)
                if result.send is not None and result.send.incomplete:
                    result.incomplete.append("send_message")
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            self.emit(
                f"Candidate processing error: {exc}",
                candidate_id=candidate.candidate_id,
                event_type="error",
            )
        return result

    def _maybe_set_stage(
        self,
        desk: TalentDeskOps,
        candidate: SourceCandidate,
        target_stage: str,
    ) -> ActionOutcome:
        assert self._run_id is not None
        self._checkpoint()
        payload = set_stage_payload(target_stage=target_stage)
        action_key = make_action_key(
            run_id=self._run_id,
            action_type=ActionType.set_stage.value,
            candidate_id=candidate.candidate_id,
            payload=payload,
        )
        self.journal.plan_action(
            action_key=action_key,
            run_id=self._run_id,
            candidate_id=candidate.candidate_id,
            action_type=ActionType.set_stage.value,
            payload=payload,
        )

        approval_value = None
        if not self.config.authority_change_stage:
            request = ApprovalRequest(
                approval_id=new_approval_id(),
                action=ActionType.set_stage,
                candidate_id=candidate.candidate_id,
                target=target_stage,
                reason=(
                    "The goal requested this action but did not grant autonomous "
                    "stage-change authority."
                ),
            )
            decision = self._request_approval(request)
            self._checkpoint()
            if decision is ApprovalDecision.REJECTED:
                rec = self.journal.mark_rejected(
                    action_key, note="human rejected stage change"
                )
                self.emit(
                    "Stage change left incomplete because approval was rejected.",
                    run_state=RunState.partial,
                    candidate_id=candidate.candidate_id,
                    action=ActionType.set_stage.value,
                    event_type="rejected",
                )
                return ActionOutcome(
                    name="set_stage",
                    ok=False,
                    detail="rejected: stage unchanged",
                    approval=ApprovalDecision.REJECTED.value,
                    incomplete=True,
                    action_key=action_key,
                    attempt_count=rec.attempt_count,
                )
            approval_value = ApprovalDecision.APPROVED.value

        self._checkpoint()
        self.journal.mark_in_progress(action_key)
        try:
            stage = desk.set_stage(target_stage)
        except Exception as exc:  # noqa: BLE001
            rec = self.journal.mark_failed(action_key, error=str(exc))
            return ActionOutcome(
                name="set_stage",
                ok=False,
                detail=str(exc),
                approval=approval_value,
                action_key=action_key,
                attempt_count=rec.attempt_count,
            )

        rec = self.journal.mark_succeeded(action_key, note=f"stage={stage}")
        self.emit(
            f"Stage changed to {stage}.",
            candidate_id=candidate.candidate_id,
            action=ActionType.set_stage.value,
        )
        return ActionOutcome(
            name="set_stage",
            ok=True,
            detail=f"stage={stage}",
            approval=approval_value,
            action_key=action_key,
            attempt_count=rec.attempt_count,
        )

    def _prepare_followup(
        self, mail: TeamMailOps, candidate: SourceCandidate
    ) -> ActionOutcome:
        assert self._run_id is not None
        operation_id = make_operation_id(
            candidate_id=candidate.candidate_id,
            role=candidate.role,
        )
        payload = prepare_followup_payload(
            operation_id=operation_id,
            recipient=candidate.email,
            role=candidate.role,
        )
        action_key = make_action_key(
            run_id=self._run_id,
            action_type=ActionType.prepare_followup.value,
            candidate_id=candidate.candidate_id,
            payload=payload,
        )
        self.journal.plan_action(
            action_key=action_key,
            run_id=self._run_id,
            candidate_id=candidate.candidate_id,
            action_type=ActionType.prepare_followup.value,
            payload=payload,
            operation_id=operation_id,
        )

        existing = mail.find_draft_by_operation_id(operation_id)
        if existing:
            self.journal.mark_in_progress(action_key)
            mail.open_draft(existing)
            draft = mail.read_draft()
            rec = self.journal.mark_succeeded(action_key, note="existing draft reused")
            self.emit(
                f"Draft {draft.message_id or existing} reused.",
                candidate_id=candidate.candidate_id,
                action=ActionType.prepare_followup.value,
            )
            return ActionOutcome(
                name="prepare_followup",
                ok=True,
                detail="existing draft reused",
                message_id=draft.message_id or existing,
                operation_id=operation_id,
                action_key=action_key,
                attempt_count=rec.attempt_count,
            )

        self._checkpoint()
        self.journal.mark_in_progress(action_key)
        mail.open_compose()
        mail.fill_compose(
            recipient=candidate.email,
            subject=followup_subject(candidate.role),
            body=followup_body(candidate),
            operation_id=operation_id,
        )
        message_id = mail.save_draft()
        mail.open_draft(message_id)
        draft = mail.read_draft()
        if draft.recipient != candidate.email or draft.operation_id != operation_id:
            rec = self.journal.mark_failed(
                action_key, error="draft fields did not persist as expected"
            )
            return ActionOutcome(
                name="prepare_followup",
                ok=False,
                detail="draft fields did not persist as expected",
                message_id=message_id,
                operation_id=operation_id,
                action_key=action_key,
                attempt_count=rec.attempt_count,
            )
        rec = self.journal.mark_succeeded(action_key, note="draft created")
        self.emit(
            f"Draft {message_id} prepared.",
            candidate_id=candidate.candidate_id,
            action=ActionType.prepare_followup.value,
        )
        return ActionOutcome(
            name="prepare_followup",
            ok=True,
            detail="draft created",
            message_id=message_id,
            operation_id=operation_id,
            action_key=action_key,
            attempt_count=rec.attempt_count,
        )

    def _maybe_send(
        self,
        mail: TeamMailOps,
        candidate: SourceCandidate,
        draft_outcome: ActionOutcome | None,
    ) -> ActionOutcome:
        assert self._run_id is not None
        operation_id = make_operation_id(
            candidate_id=candidate.candidate_id,
            role=candidate.role,
        )
        message_id: str | None = None
        if draft_outcome is not None and draft_outcome.ok and draft_outcome.message_id:
            message_id = draft_outcome.message_id
            operation_id = draft_outcome.operation_id or operation_id
        else:
            message_id = mail.find_draft_by_operation_id(operation_id)

        payload = send_message_payload(operation_id=operation_id)
        action_key = make_action_key(
            run_id=self._run_id,
            action_type=ActionType.send_message.value,
            candidate_id=candidate.candidate_id,
            payload=payload,
        )
        self.journal.plan_action(
            action_key=action_key,
            run_id=self._run_id,
            candidate_id=candidate.candidate_id,
            action_type=ActionType.send_message.value,
            payload=payload,
            operation_id=operation_id,
        )

        if not message_id:
            detail = (
                "send blocked: no known corresponding draft/artifact for this "
                "follow-up (prepare_followup was not performed and no matching "
                "draft exists)"
            )
            rec = self.journal.mark_blocked(action_key, note=detail)
            self.emit(
                detail,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
                event_type="blocked",
            )
            return ActionOutcome(
                name="send_message",
                ok=False,
                detail=detail,
                operation_id=operation_id,
                incomplete=True,
                action_key=action_key,
                attempt_count=rec.attempt_count,
            )

        self._checkpoint()
        approval_value = None
        if not self.config.authority_send_message:
            request = ApprovalRequest(
                approval_id=new_approval_id(),
                action=ActionType.send_message,
                candidate_id=candidate.candidate_id,
                target=candidate.email,
                reason=(
                    "The goal requested sending but requires approval before "
                    "external action."
                ),
                operation_id=operation_id,
            )
            decision = self._request_approval(request)
            self._checkpoint()
            if decision is ApprovalDecision.REJECTED:
                rec = self.journal.mark_rejected(
                    action_key, note="human rejected send"
                )
                self.emit(
                    "Follow-up left as draft because approval was rejected.",
                    run_state=RunState.partial,
                    candidate_id=candidate.candidate_id,
                    action=ActionType.send_message.value,
                    event_type="rejected",
                )
                return ActionOutcome(
                    name="send_message",
                    ok=False,
                    detail="rejected: draft left intact, message not sent",
                    message_id=message_id,
                    operation_id=operation_id,
                    approval=ApprovalDecision.REJECTED.value,
                    incomplete=True,
                    action_key=action_key,
                    attempt_count=rec.attempt_count,
                )
            approval_value = ApprovalDecision.APPROVED.value

        return self._execute_send(
            mail,
            candidate=candidate,
            message_id=message_id,
            operation_id=operation_id,
            action_key=action_key,
            approval_value=approval_value,
        )

    def _execute_send(
        self,
        mail: TeamMailOps,
        *,
        candidate: SourceCandidate,
        message_id: str,
        operation_id: str,
        action_key: str,
        approval_value: str | None,
    ) -> ActionOutcome:
        self._checkpoint()
        self.emit(
            "Sending follow-up...",
            candidate_id=candidate.candidate_id,
            action=ActionType.send_message.value,
        )
        rec = self.journal.mark_in_progress(action_key)
        send_result = mail.send_draft(
            message_id,
            expected_operation_id=operation_id,
            expected_recipient=candidate.email,
        )

        if send_result.unknown:
            self.journal.mark_unknown(action_key, error=send_result.detail)
            self.emit(
                "Send acknowledgement lost; checking TeamMail Sent state.",
                run_state=RunState.recovering,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
                event_type="recovering",
            )
            return self._recover_send(
                mail,
                candidate=candidate,
                message_id=message_id,
                operation_id=operation_id,
                action_key=action_key,
                approval_value=approval_value,
            )

        if not send_result.ok:
            rec = self.journal.mark_failed(action_key, error=send_result.detail)
            self.emit(
                send_result.detail,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
                event_type="error",
            )
            return ActionOutcome(
                name="send_message",
                ok=False,
                detail=send_result.detail,
                message_id=send_result.message_id,
                operation_id=send_result.operation_id or operation_id,
                approval=approval_value,
                action_key=action_key,
                attempt_count=rec.attempt_count,
            )

        rec = self.journal.mark_succeeded(action_key, note=send_result.detail)
        self.emit(
            "Follow-up sent.",
            candidate_id=candidate.candidate_id,
            action=ActionType.send_message.value,
        )
        return ActionOutcome(
            name="send_message",
            ok=True,
            detail=send_result.detail,
            message_id=send_result.message_id,
            operation_id=send_result.operation_id or operation_id,
            approval=approval_value,
            action_key=action_key,
            attempt_count=rec.attempt_count,
        )

    def _recover_send(
        self,
        mail: TeamMailOps,
        *,
        candidate: SourceCandidate,
        message_id: str,
        operation_id: str,
        action_key: str,
        approval_value: str | None,
    ) -> ActionOutcome:
        self.control.set_state(RunState.recovering)
        inspector = BrowserSentInspector(mail)
        decision = resolve_unknown_send(self.journal, action_key, inspector)

        if decision.decision == "recovered":
            self.emit(
                f"Found existing message with operation ID {operation_id}.",
                run_state=RunState.recovering,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
                event_type="recovering",
            )
            self.emit(
                "Send recovered without retry.",
                run_state=RunState.running,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
            )
            self.control.set_state(RunState.running)
            return ActionOutcome(
                name="send_message",
                ok=True,
                detail=decision.note,
                message_id=decision.message_id or message_id,
                operation_id=operation_id,
                approval=approval_value,
                recovered=True,
                action_key=action_key,
                attempt_count=decision.action.attempt_count,
            )

        if decision.should_retry:
            self.emit(
                decision.note,
                run_state=RunState.recovering,
                candidate_id=candidate.candidate_id,
                action=ActionType.send_message.value,
                event_type="recovering",
            )
            # Controlled same-operation retry: journal IN_PROGRESS again, reuse operation_id.
            draft_id = mail.find_draft_by_operation_id(operation_id) or message_id
            self.control.set_state(RunState.running)
            return self._execute_send(
                mail,
                candidate=candidate,
                message_id=draft_id,
                operation_id=operation_id,
                action_key=action_key,
                approval_value=approval_value,
            )

        self.emit(
            decision.note,
            run_state=RunState.partial,
            candidate_id=candidate.candidate_id,
            action=ActionType.send_message.value,
            event_type="blocked",
        )
        self.control.set_state(RunState.running)
        return ActionOutcome(
            name="send_message",
            ok=False,
            detail=decision.note,
            message_id=message_id,
            operation_id=operation_id,
            approval=approval_value,
            incomplete=True,
            unknown=True,
            action_key=action_key,
            attempt_count=decision.action.attempt_count,
        )


def _approval_action_phrase(request: ApprovalRequest) -> str:
    if request.action is ActionType.send_message:
        return f"sending follow-up to {request.target}"
    if request.action is ActionType.set_stage:
        return f"changing stage to {request.target}"
    return request.action.value
