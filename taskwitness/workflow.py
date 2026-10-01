"""Deterministic recruiting browser workflow (Phase 2).

No LLM. No durable journal. No autonomous send.
Side effects occur only through Playwright UI adapters.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from taskwitness.browser.session import BrowserSession
from taskwitness.browser.talentdesk import TalentDeskBrowser, VisibleCandidate
from taskwitness.browser.teammail import TeamMailBrowser
from taskwitness.candidate_source import (
    SourceCandidate,
    filter_candidates,
    load_candidates,
)
from taskwitness.schemas import ActionType, TaskSpec


@dataclass
class WorkflowConfig:
    """Explicit Phase-2 workflow input (not the long-term TaskSpec product schema)."""

    role: str
    candidate_status: str
    source_file: str = "data/candidates.csv"
    prepare_followups: bool = True
    target_stage: Optional[str] = None
    base_url: str = "http://127.0.0.1:8000"
    headed: bool = True
    slow_mo_ms: int = 0
    deferred_actions: list[str] = field(default_factory=list)


@dataclass
class ActionOutcome:
    name: str
    ok: bool
    detail: str = ""
    message_id: Optional[str] = None
    operation_id: Optional[str] = None


@dataclass
class CandidateRunResult:
    candidate_id: str
    precondition_ok: Optional[bool] = None
    stage_update: Optional[ActionOutcome] = None
    draft: Optional[ActionOutcome] = None
    deferred: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if self.precondition_ok is False:
            return False
        if self.stage_update is not None and not self.stage_update.ok:
            return False
        if self.draft is not None and not self.draft.ok:
            return False
        return True


@dataclass
class BrowserRunResult:
    selected_candidate_ids: list[str]
    candidate_results: list[CandidateRunResult]
    deferred_actions: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        return all(r.ok for r in self.candidate_results)


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
    """Deterministic logical operation id for a follow-up draft.

    Material: action | candidate_id | normalized role
    Encoded as a short stable slug plus a hash suffix for uniqueness/safety.
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
    """Map TaskSpec → Phase-2 config.

    Authority gates that Phase 4 will handle interactively are deferred here:
    - set_stage with authority.change_stage=false → do not mutate TalentDesk
    - send_message (any authority in Phase 2) → never send; report deferred
    False-authority actions are never silently discarded.
    """
    deferred: list[str] = []
    prepare = ActionType.prepare_followup in spec.actions
    target: Optional[str] = None

    if ActionType.set_stage in spec.actions:
        if spec.authority.change_stage:
            target = spec.target_stage
        else:
            deferred.append("set_stage:deferred_until_authority_phase")

    if ActionType.send_message in spec.actions:
        deferred.append("send_message:deferred_until_authority_phase")

    cfg = WorkflowConfig(
        source_file=spec.source_file,
        role=spec.role,
        candidate_status=spec.candidate_status,
        prepare_followups=prepare,
        target_stage=target,
        base_url=base_url,
        headed=headed,
        deferred_actions=list(deferred),
    )
    return cfg, deferred


class RecruitingWorkflow:
    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config

    def run(self) -> BrowserRunResult:
        deferred_actions = list(self.config.deferred_actions)
        try:
            wait_for_app(self.config.base_url)
        except RuntimeError as exc:
            return BrowserRunResult(
                selected_candidate_ids=[],
                candidate_results=[],
                deferred_actions=deferred_actions,
                error=str(exc),
            )

        source_path = Path(self.config.source_file)
        if not source_path.is_file():
            return BrowserRunResult(
                selected_candidate_ids=[],
                candidate_results=[],
                deferred_actions=deferred_actions,
                error=f"source file not found: {source_path}",
            )

        selected = filter_candidates(
            load_candidates(source_path),
            role=self.config.role,
            candidate_status=self.config.candidate_status,
        )
        selected_ids = [c.candidate_id for c in selected]
        results: list[CandidateRunResult] = []

        try:
            with BrowserSession(
                base_url=self.config.base_url,
                headed=self.config.headed,
                slow_mo_ms=self.config.slow_mo_ms,
            ) as session:
                desk = TalentDeskBrowser(session)
                mail = TeamMailBrowser(session)
                for candidate in selected:
                    results.append(self._process_candidate(desk, mail, candidate))
        except Exception as exc:  # noqa: BLE001 — surface clean workflow failure
            return BrowserRunResult(
                selected_candidate_ids=selected_ids,
                candidate_results=results,
                deferred_actions=deferred_actions,
                error=f"browser workflow failed: {exc}",
            )

        return BrowserRunResult(
            selected_candidate_ids=selected_ids,
            candidate_results=results,
            deferred_actions=deferred_actions,
        )

    def _process_candidate(
        self,
        desk: TalentDeskBrowser,
        mail: TeamMailBrowser,
        candidate: SourceCandidate,
    ) -> CandidateRunResult:
        result = CandidateRunResult(candidate_id=candidate.candidate_id)
        try:
            desk.filter_candidates(search=candidate.candidate_id, role=candidate.role)
            desk.open_candidate(candidate.candidate_id)
            visible = desk.read_candidate()
            matched, detail = identities_match(candidate, visible)
            result.precondition_ok = matched
            if not matched:
                result.error = f"precondition blocked: {detail}"
                return result

            if self.config.target_stage:
                stage = desk.set_stage(self.config.target_stage)
                result.stage_update = ActionOutcome(
                    name="set_stage",
                    ok=True,
                    detail=f"stage={stage}",
                )

            if self.config.prepare_followups:
                result.draft = self._prepare_followup(mail, candidate)
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
        return result

    def _prepare_followup(
        self, mail: TeamMailBrowser, candidate: SourceCandidate
    ) -> ActionOutcome:
        operation_id = make_operation_id(
            candidate_id=candidate.candidate_id,
            role=candidate.role,
        )
        existing = mail.find_draft_by_operation_id(operation_id)
        if existing:
            mail.open_draft(existing)
            draft = mail.read_draft()
            return ActionOutcome(
                name="prepare_followup",
                ok=True,
                detail="existing draft reused",
                message_id=draft.message_id or existing,
                operation_id=operation_id,
            )

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
            return ActionOutcome(
                name="prepare_followup",
                ok=False,
                detail="draft fields did not persist as expected",
                message_id=message_id,
                operation_id=operation_id,
            )
        return ActionOutcome(
            name="prepare_followup",
            ok=True,
            detail="draft created",
            message_id=message_id,
            operation_id=operation_id,
        )
