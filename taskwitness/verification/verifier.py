"""Independent goal verifier — fresh browser pass against target UI.

Does not trust executor success, journal SUCCEEDED/RECOVERED alone, or the LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from taskwitness.browser.session import BrowserSession
from taskwitness.browser.talentdesk import TalentDeskBrowser, VisibleCandidate
from taskwitness.browser.teammail import TeamMailBrowser
from taskwitness.journal.store import Journal
from taskwitness.schemas import ActionType
from taskwitness.verification.expectations import (
    ExpectationKind,
    ExpectedCheck,
    derive_expectations,
    expected_candidates,
)
from taskwitness.verification.types import (
    CheckStatus,
    OverallVerificationStatus,
    PostconditionCheck,
    VerificationResult,
    aggregate_overall,
)
from taskwitness.workflow import followup_subject, wait_for_app


class TalentDeskReader(Protocol):
    def filter_candidates(self, *, search: str = "", role: str = "") -> None: ...

    def open_candidate(self, candidate_id: str) -> None: ...

    def read_candidate(self) -> VisibleCandidate: ...


class TeamMailReader(Protocol):
    def find_draft_by_operation_id(self, operation_id: str) -> str | None: ...

    def open_draft(self, message_id: str) -> None: ...

    def read_draft(self): ...

    def find_sent_by_operation_id(self, operation_id: str) -> str | None: ...

    def count_sent_by_operation_id(self, operation_id: str) -> int: ...

    def inspect_sent(self, message_id: str) -> dict[str, str]: ...


class GoalVerifier:
    """Whole-goal verification against TalentDesk/TeamMail visible state."""

    def __init__(
        self,
        *,
        journal: Journal,
        base_url: str = "http://127.0.0.1:8000",
        headed: bool = False,
        source_root: Path | None = None,
        skip_app_wait: bool = False,
    ) -> None:
        self.journal = journal
        self.base_url = base_url
        self.headed = headed
        self.source_root = source_root
        self.skip_app_wait = skip_app_wait

    def verify(
        self,
        run_id: str,
        *,
        screenshot_dir: Path | None = None,
        desk: TalentDeskReader | None = None,
        mail: TeamMailReader | None = None,
    ) -> VerificationResult:
        run = self.journal.load_run(run_id)
        if run is None:
            raise ValueError(f"unknown run_id: {run_id}")
        spec = self.journal.load_task_spec(run_id)
        actions = self.journal.list_actions(run_id)
        candidates = expected_candidates(spec, source_root=self.source_root)
        expectations = derive_expectations(
            spec,
            journal_actions=actions,
            source_root=self.source_root,
        )

        checks: list[PostconditionCheck] = []
        if desk is not None and mail is not None:
            for exp in expectations:
                checks.append(
                    self._evaluate(
                        exp,
                        desk=desk,
                        mail=mail,
                        screenshot_dir=screenshot_dir,
                        session=None,
                    )
                )
        else:
            if not self.skip_app_wait:
                wait_for_app(self.base_url)
            with BrowserSession(base_url=self.base_url, headed=self.headed) as session:
                live_desk = TalentDeskBrowser(session)
                live_mail = TeamMailBrowser(session)
                for exp in expectations:
                    checks.append(
                        self._evaluate(
                            exp,
                            desk=live_desk,
                            mail=live_mail,
                            screenshot_dir=screenshot_dir,
                            session=session,
                        )
                    )

        overall = aggregate_overall(checks)
        return VerificationResult(
            run_id=run_id,
            overall_status=overall,
            verified_complete=overall is OverallVerificationStatus.passed,
            checks=checks,
            expected_candidate_ids=[c.candidate_id for c in candidates],
        )

    def _evaluate(
        self,
        exp: ExpectedCheck,
        *,
        desk: TalentDeskReader,
        mail: TeamMailReader,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
    ) -> PostconditionCheck:
        check_id = f"{exp.kind.value}:{exp.candidate.candidate_id}"
        evidence: list[str] = []
        try:
            if exp.kind is ExpectationKind.stage_equals:
                return self._check_stage_equals(
                    exp, desk, check_id, screenshot_dir, session, evidence
                )
            if exp.kind is ExpectationKind.stage_unchanged:
                return self._check_stage_unchanged(
                    exp, desk, check_id, screenshot_dir, session, evidence
                )
            if exp.kind is ExpectationKind.followup_artifact:
                return self._check_followup(
                    exp, mail, check_id, screenshot_dir, session, evidence
                )
            if exp.kind is ExpectationKind.send_exactly_one:
                return self._check_send_exactly_one(
                    exp, mail, check_id, screenshot_dir, session, evidence
                )
            if exp.kind is ExpectationKind.send_absent:
                return self._check_send_absent(
                    exp, mail, check_id, screenshot_dir, session, evidence
                )
            return PostconditionCheck(
                check_id=check_id,
                description=exp.description,
                expected=exp.expected_value,
                observed="unsupported expectation kind",
                status=CheckStatus.blocked,
                candidate_id=exp.candidate.candidate_id,
                action=exp.action.value if exp.action else None,
            )
        except Exception as exc:  # noqa: BLE001
            return PostconditionCheck(
                check_id=check_id,
                description=exp.description,
                expected=exp.expected_value,
                observed=f"inspection error: {exc}",
                status=CheckStatus.blocked,
                candidate_id=exp.candidate.candidate_id,
                action=exp.action.value if exp.action else None,
                note=str(exc),
            )

    def _shot(
        self,
        session: BrowserSession | None,
        screenshot_dir: Path | None,
        name: str,
        evidence: list[str],
    ) -> None:
        if session is None or screenshot_dir is None:
            return
        rel = f"screenshots/{name}"
        path = screenshot_dir / name
        session.screenshot(str(path))
        evidence.append(rel)

    def _check_stage_equals(
        self,
        exp: ExpectedCheck,
        desk: TalentDeskReader,
        check_id: str,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
        evidence: list[str],
    ) -> PostconditionCheck:
        cand = exp.candidate
        desk.filter_candidates(search=cand.candidate_id, role=cand.role)
        desk.open_candidate(cand.candidate_id)
        visible = desk.read_candidate()
        self._shot(
            session,
            screenshot_dir,
            f"talentdesk-{cand.candidate_id}-final.png",
            evidence,
        )
        observed = visible.current_stage
        if exp.from_rejection:
            if observed == exp.expected_value:
                status = CheckStatus.failed
                note = "Stage changed to target despite approval rejection"
            else:
                status = CheckStatus.incomplete
                note = "Stage change left incomplete because approval was rejected"
        elif observed == exp.expected_value:
            status = CheckStatus.passed
            note = None
        else:
            status = CheckStatus.failed
            note = None
        return PostconditionCheck(
            check_id=check_id,
            description=exp.description,
            expected=exp.expected_value,
            observed=observed,
            status=status,
            candidate_id=cand.candidate_id,
            action=ActionType.set_stage.value,
            evidence_refs=evidence,
            note=note,
        )

    def _check_stage_unchanged(
        self,
        exp: ExpectedCheck,
        desk: TalentDeskReader,
        check_id: str,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
        evidence: list[str],
    ) -> PostconditionCheck:
        cand = exp.candidate
        desk.filter_candidates(search=cand.candidate_id, role=cand.role)
        desk.open_candidate(cand.candidate_id)
        visible = desk.read_candidate()
        self._shot(
            session,
            screenshot_dir,
            f"talentdesk-{cand.candidate_id}-final.png",
            evidence,
        )
        observed = visible.current_stage
        status = (
            CheckStatus.passed if observed == exp.expected_value else CheckStatus.failed
        )
        return PostconditionCheck(
            check_id=check_id,
            description=exp.description,
            expected=exp.expected_value,
            observed=observed,
            status=status,
            candidate_id=cand.candidate_id,
            action=None,
            evidence_refs=evidence,
            note="Controlled assessment baseline comparison against CSV current_stage",
        )

    def _check_followup(
        self,
        exp: ExpectedCheck,
        mail: TeamMailReader,
        check_id: str,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
        evidence: list[str],
    ) -> PostconditionCheck:
        cand = exp.candidate
        op = exp.operation_id or ""
        subject = followup_subject(cand.role)
        sent_id = mail.find_sent_by_operation_id(op)
        draft_id = mail.find_draft_by_operation_id(op)
        if sent_id:
            detail = mail.inspect_sent(sent_id)
            self._shot(
                session,
                screenshot_dir,
                f"teammail-{cand.candidate_id}-sent.png",
                evidence,
            )
            ok = (
                detail.get("operation_id") == op
                and detail.get("recipient") == cand.email
                and detail.get("subject") == subject
            )
            observed = (
                f"sent {sent_id}; recipient={detail.get('recipient')}; "
                f"subject={detail.get('subject')}; operation_id={detail.get('operation_id')}"
            )
            status = CheckStatus.passed if ok else CheckStatus.failed
        elif draft_id:
            mail.open_draft(draft_id)
            draft = mail.read_draft()
            self._shot(
                session,
                screenshot_dir,
                f"teammail-{cand.candidate_id}-draft.png",
                evidence,
            )
            ok = (
                draft.operation_id == op
                and draft.recipient == cand.email
                and draft.subject == subject
            )
            observed = (
                f"draft {draft_id}; recipient={draft.recipient}; "
                f"subject={draft.subject}; operation_id={draft.operation_id}"
            )
            status = CheckStatus.passed if ok else CheckStatus.failed
        else:
            observed = "no draft or sent artifact for operation_id"
            status = CheckStatus.failed
        return PostconditionCheck(
            check_id=check_id,
            description=exp.description,
            expected=exp.expected_value,
            observed=observed,
            status=status,
            candidate_id=cand.candidate_id,
            action=ActionType.prepare_followup.value,
            evidence_refs=evidence,
        )

    def _check_send_exactly_one(
        self,
        exp: ExpectedCheck,
        mail: TeamMailReader,
        check_id: str,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
        evidence: list[str],
    ) -> PostconditionCheck:
        cand = exp.candidate
        op = exp.operation_id or ""
        subject = followup_subject(cand.role)
        count = mail.count_sent_by_operation_id(op)
        note: str | None = None
        if count > 1:
            status = CheckStatus.failed
            observed = f"sent_count={count} (duplicate)"
            note = "Duplicate Sent artifacts for the same operation_id"
        elif count == 1:
            mid = mail.find_sent_by_operation_id(op)
            assert mid is not None
            detail = mail.inspect_sent(mid)
            self._shot(
                session,
                screenshot_dir,
                f"teammail-{cand.candidate_id}-sent.png",
                evidence,
            )
            ok = (
                detail.get("operation_id") == op
                and detail.get("recipient") == cand.email
                and detail.get("subject") == subject
            )
            observed = (
                f"sent_count=1; message_id={mid}; recipient={detail.get('recipient')}; "
                f"subject={detail.get('subject')}; operation_id={detail.get('operation_id')}"
            )
            if exp.from_rejection:
                status = CheckStatus.failed
                note = "Message was sent despite approval rejection"
            else:
                status = CheckStatus.passed if ok else CheckStatus.failed
        else:
            observed = "sent_count=0"
            if exp.from_rejection or exp.incomplete_ok:
                status = CheckStatus.incomplete
                note = "Requested send was not completed because approval was rejected"
            else:
                status = CheckStatus.failed
        return PostconditionCheck(
            check_id=check_id,
            description=exp.description,
            expected=exp.expected_value,
            observed=observed,
            status=status,
            candidate_id=cand.candidate_id,
            action=ActionType.send_message.value,
            evidence_refs=evidence,
            note=note,
        )

    def _check_send_absent(
        self,
        exp: ExpectedCheck,
        mail: TeamMailReader,
        check_id: str,
        screenshot_dir: Path | None,
        session: BrowserSession | None,
        evidence: list[str],
    ) -> PostconditionCheck:
        cand = exp.candidate
        op = exp.operation_id or ""
        count = mail.count_sent_by_operation_id(op)
        # Capture drafts list context when possible for rejected-send evidence.
        if count == 0:
            draft_id = mail.find_draft_by_operation_id(op)
            if draft_id and session is not None:
                mail.open_draft(draft_id)
                self._shot(
                    session,
                    screenshot_dir,
                    f"teammail-{cand.candidate_id}-draft.png",
                    evidence,
                )
        else:
            mid = mail.find_sent_by_operation_id(op)
            if mid and session is not None:
                mail.inspect_sent(mid)
                self._shot(
                    session,
                    screenshot_dir,
                    f"teammail-{cand.candidate_id}-sent.png",
                    evidence,
                )
        status = CheckStatus.passed if count == 0 else CheckStatus.failed
        return PostconditionCheck(
            check_id=check_id,
            description=exp.description,
            expected=exp.expected_value,
            observed=f"sent_count={count}",
            status=status,
            candidate_id=cand.candidate_id,
            action=ActionType.send_message.value if exp.action else None,
            evidence_refs=evidence,
            note="Safety verification: no matching Sent artifact" if status is CheckStatus.passed else None,
        )
