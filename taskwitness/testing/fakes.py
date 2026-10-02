"""Deterministic fake TalentDesk / TeamMail adapters for Phase-4 unit tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from taskwitness.browser.talentdesk import VisibleCandidate
from taskwitness.browser.teammail import SendResult, VisibleDraft


@dataclass
class FakeTalentDesk:
    candidates: dict[str, VisibleCandidate] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)
    stage_changes: list[tuple[str, str]] = field(default_factory=list)
    filter_calls: list[tuple[str, str]] = field(default_factory=list)
    _current: str | None = None

    def seed(self, candidate: VisibleCandidate) -> None:
        self.candidates[candidate.candidate_id] = candidate

    def filter_candidates(self, *, search: str = "", role: str = "") -> None:
        self.filter_calls.append((search, role))

    def open_candidate(self, candidate_id: str) -> None:
        if candidate_id not in self.candidates:
            raise RuntimeError(f"unknown candidate {candidate_id}")
        self.opened.append(candidate_id)
        self._current = candidate_id

    def read_candidate(self) -> VisibleCandidate:
        if self._current is None:
            raise RuntimeError("no candidate open")
        return self.candidates[self._current]

    def set_stage(self, stage: str) -> str:
        if self._current is None:
            raise RuntimeError("no candidate open")
        current = self.candidates[self._current]
        updated = VisibleCandidate(
            candidate_id=current.candidate_id,
            name=current.name,
            email=current.email,
            role=current.role,
            status=current.status,
            current_stage=stage,
        )
        self.candidates[self._current] = updated
        self.stage_changes.append((self._current, stage))
        return stage


@dataclass
class FakeTeamMail:
    drafts: dict[str, VisibleDraft] = field(default_factory=dict)
    sent: dict[str, VisibleDraft] = field(default_factory=dict)
    send_calls: list[str] = field(default_factory=list)
    _compose: dict[str, str] | None = None
    _open_draft_id: str | None = None
    _next_id: int = 1
    fail_send_unknown_once: bool = False

    def find_draft_by_operation_id(self, operation_id: str) -> str | None:
        for mid, draft in self.drafts.items():
            if draft.operation_id == operation_id:
                return mid
        return None

    def open_draft(self, message_id: str) -> None:
        if message_id not in self.drafts:
            raise RuntimeError(f"draft not found: {message_id}")
        self._open_draft_id = message_id

    def read_draft(self) -> VisibleDraft:
        if self._open_draft_id is None:
            raise RuntimeError("no draft open")
        return self.drafts[self._open_draft_id]

    def open_compose(self) -> None:
        self._compose = {
            "recipient": "",
            "subject": "",
            "body": "",
            "operation_id": "",
        }
        self._open_draft_id = None

    def fill_compose(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        operation_id: str = "",
    ) -> None:
        if self._compose is None:
            raise RuntimeError("compose not open")
        self._compose = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "operation_id": operation_id,
        }

    def save_draft(self) -> str:
        if self._compose is None:
            raise RuntimeError("compose not open")
        message_id = f"MAIL-{self._next_id:04d}"
        self._next_id += 1
        draft = VisibleDraft(
            message_id=message_id,
            recipient=self._compose["recipient"],
            subject=self._compose["subject"],
            body=self._compose["body"],
            operation_id=self._compose["operation_id"],
        )
        self.drafts[message_id] = draft
        self._open_draft_id = message_id
        self._compose = None
        return message_id

    def find_sent_by_operation_id(self, operation_id: str) -> str | None:
        for mid, draft in self.sent.items():
            if draft.operation_id == operation_id:
                return mid
        return None

    def count_sent_by_operation_id(self, operation_id: str) -> int:
        return sum(1 for d in self.sent.values() if d.operation_id == operation_id)

    def send_draft(
        self,
        message_id: str,
        *,
        expected_operation_id: str | None = None,
        expected_recipient: str | None = None,
    ) -> SendResult:
        if message_id not in self.drafts:
            raise RuntimeError(f"draft not found: {message_id}")
        draft = self.drafts[message_id]
        if expected_operation_id is not None and draft.operation_id != expected_operation_id:
            raise RuntimeError("operation_id mismatch")
        if expected_recipient is not None and draft.recipient != expected_recipient:
            raise RuntimeError("recipient mismatch")
        self.send_calls.append(message_id)
        if self.fail_send_unknown_once:
            self.fail_send_unknown_once = False
            self.sent[message_id] = draft
            del self.drafts[message_id]
            return SendResult(
                ok=False,
                message_id=message_id,
                operation_id=draft.operation_id,
                detail="send acknowledgement ambiguous/failed: interrupted",
                unknown=True,
            )
        self.sent[message_id] = draft
        del self.drafts[message_id]
        return SendResult(
            ok=True,
            message_id=message_id,
            operation_id=draft.operation_id,
            detail="message sent",
        )
