"""Approval boundary: human gates for authority-exceeding side effects.

Approval is action-scoped and one-time. It does NOT mutate TaskSpec.authority.
The LLM never grants approval.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

from taskwitness.schemas import ActionType


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    action: ActionType
    candidate_id: str
    target: str
    reason: str
    operation_id: Optional[str] = None

    def describe(self) -> str:
        lines = [
            f"Approval required ({self.approval_id}):",
            f"  Action: {_action_label(self.action)}",
            f"  Candidate: {self.candidate_id}",
            f"  Target: {self.target}",
            f"  Reason: {self.reason}",
        ]
        if self.operation_id:
            lines.append(f"  Operation ID: {self.operation_id}")
        return "\n".join(lines)


class ApprovalProvider(Protocol):
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision: ...


def new_approval_id() -> str:
    return f"apr-{uuid.uuid4().hex[:10]}"


def _action_label(action: ActionType) -> str:
    if action is ActionType.set_stage:
        return "Change candidate stage"
    if action is ActionType.send_message:
        return "Send interview follow-up"
    return action.value


class AlwaysApprove:
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


class AlwaysReject:
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.REJECTED


class ScriptedApprovalProvider:
    """Deterministic provider for tests: consume decisions in order.

    If the script is exhausted, raises RuntimeError (fail closed).
    """

    def __init__(self, decisions: list[ApprovalDecision]) -> None:
        self._remaining = list(decisions)
        self.requests: list[ApprovalRequest] = []

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        if not self._remaining:
            raise RuntimeError(
                f"ScriptedApprovalProvider exhausted; unexpected request: {request}"
            )
        return self._remaining.pop(0)


class CyclingApprovalProvider:
    """Repeat a fixed decision sequence (useful for multi-candidate demos)."""

    def __init__(self, decisions: list[ApprovalDecision]) -> None:
        if not decisions:
            raise ValueError("decisions must not be empty")
        self._cycle = itertools.cycle(decisions)
        self.requests: list[ApprovalRequest] = []

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return next(self._cycle)


class TerminalApprovalProvider:
    """Development/manual provider. Reads stdin — never used inside unit tests.

    RecruitingWorkflow must not call input() directly; this provider owns it.
    """

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        print()
        print(request.describe())
        print()
        while True:
            raw = input("[a] approve  [r] reject: ").strip().lower()
            if raw in {"a", "approve", "y", "yes"}:
                return ApprovalDecision.APPROVED
            if raw in {"r", "reject", "n", "no"}:
                return ApprovalDecision.REJECTED
            print("Enter 'a' to approve or 'r' to reject.")
