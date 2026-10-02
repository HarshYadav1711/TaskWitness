"""UI-backed ApprovalProvider for the operator console.

Publishes ApprovalRequest to the active run and waits until the UI resolves
APPROVED or REJECTED exactly once. Does not perform side effects.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from taskwitness.control.approval import ApprovalDecision, ApprovalRequest


class ApprovalError(ValueError):
    """Invalid or stale approval resolution attempt."""


class WebApprovalProvider:
    """Blocks the workflow thread until the operator UI resolves the request."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: Optional[ApprovalRequest] = None
        self._decision: Optional[ApprovalDecision] = None
        self._resolved_ids: set[str] = set()
        self.on_pending_changed: Optional[Callable[[Optional[ApprovalRequest]], None]] = None

    @property
    def pending(self) -> Optional[ApprovalRequest]:
        with self._condition:
            return self._pending

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        with self._condition:
            if request.approval_id in self._resolved_ids:
                raise ApprovalError(f"approval already resolved: {request.approval_id}")
            self._pending = request
            self._decision = None
            callback = self.on_pending_changed
        if callback is not None:
            callback(request)
        with self._condition:
            while self._decision is None:
                self._condition.wait(timeout=0.5)
            decision = self._decision
            self._pending = None
            self._decision = None
            self._resolved_ids.add(request.approval_id)
        if callback is not None:
            callback(None)
        assert decision is not None
        return decision

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRequest:
        with self._condition:
            if approval_id in self._resolved_ids:
                raise ApprovalError("approval already resolved")
            if self._pending is None:
                raise ApprovalError("no pending approval")
            if self._pending.approval_id != approval_id:
                raise ApprovalError("approval id mismatch")
            if decision not in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED):
                raise ApprovalError("invalid decision")
            pending = self._pending
            self._decision = decision
            # Claim immediately so concurrent resolve() cannot also succeed
            # before request_approval() wakes and records the id.
            self._resolved_ids.add(approval_id)
            self._pending = None
            callback = self.on_pending_changed
            self._condition.notify_all()
        if callback is not None:
            callback(None)
        return pending
