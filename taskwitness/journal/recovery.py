"""Unknown-outcome recovery for effectful operations (Phase 5).

Recovery asks: did THIS uncertain side effect already happen?
It is not Phase-6 whole-goal verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from taskwitness.journal.store import Journal
from taskwitness.journal.types import ActionRecord, ActionState


class AmbiguousOperationOutcome(Exception):
    """The side effect may have happened; acknowledgement is inconclusive."""

    def __init__(self, message: str, *, operation_id: str | None = None) -> None:
        super().__init__(message)
        self.operation_id = operation_id


@dataclass(frozen=True)
class InspectionResult:
    """Result of inspecting TeamMail Sent for a logical operation_id."""

    match_count: int
    message_id: Optional[str] = None
    available: bool = True
    detail: str = ""


class SentTargetInspector(Protocol):
    def inspect_sent_operation(self, operation_id: str) -> InspectionResult: ...


@dataclass(frozen=True)
class RecoveryDecision:
    action: ActionRecord
    decision: str  # recovered | retry | blocked
    note: str
    should_retry: bool = False
    message_id: Optional[str] = None


def resolve_unknown_send(
    journal: Journal,
    action_key: str,
    inspector: SentTargetInspector,
    *,
    max_attempts: int = 2,
) -> RecoveryDecision:
    """Resolve an UNKNOWN send via target-state inspection.

    Decisions:
    - exactly one match → RECOVERED (no retry)
    - zero matches and conclusive → controlled retry if attempt_count < max_attempts
    - multiple matches / unavailable → BLOCKED (no retry)
    """
    action = journal.get_action(action_key)
    if action is None:
        raise ValueError(f"unknown action_key: {action_key}")
    if action.state is not ActionState.unknown:
        raise ValueError(
            f"resolve_unknown_send requires UNKNOWN state, got {action.state.value}"
        )
    if not action.operation_id:
        updated = journal.mark_blocked(
            action_key,
            note="Send acknowledgement was lost and no operation_id is available for reconciliation.",
        )
        return RecoveryDecision(
            action=updated,
            decision="blocked",
            note=updated.recovery_note or "",
        )

    inspection = inspector.inspect_sent_operation(action.operation_id)
    if not inspection.available:
        note = (
            "Send acknowledgement was lost. TeamMail Sent state could not be "
            "inspected, so TaskWitness stopped rather than risk sending the message twice."
        )
        updated = journal.mark_blocked(
            action_key,
            note=note,
            error=inspection.detail or None,
        )
        return RecoveryDecision(action=updated, decision="blocked", note=note)

    if inspection.match_count == 1:
        note = (
            f"Found existing message with operation ID {action.operation_id}"
            + (f" ({inspection.message_id})" if inspection.message_id else "")
            + "; recovered without retry."
        )
        updated = journal.mark_recovered(action_key, note=note)
        return RecoveryDecision(
            action=updated,
            decision="recovered",
            note=note,
            message_id=inspection.message_id,
        )

    if inspection.match_count > 1:
        note = (
            f"Multiple Sent artifacts share operation ID {action.operation_id}; "
            "blocked to avoid further duplicate delivery."
        )
        updated = journal.mark_blocked(action_key, note=note)
        return RecoveryDecision(action=updated, decision="blocked", note=note)

    # Zero matches — conclusive absence.
    if action.attempt_count >= max_attempts:
        note = (
            f"No Sent artifact for operation ID {action.operation_id} after "
            f"{action.attempt_count} attempt(s); blocked (retry limit reached)."
        )
        updated = journal.mark_blocked(action_key, note=note)
        return RecoveryDecision(action=updated, decision="blocked", note=note)

    note = (
        f"No Sent artifact for operation ID {action.operation_id}; "
        "one controlled same-operation retry is allowed."
    )
    return RecoveryDecision(
        action=action,
        decision="retry",
        note=note,
        should_retry=True,
    )


class BrowserSentInspector:
    """Inspect Sent through TeamMailBrowser visible UI."""

    def __init__(self, mail) -> None:
        self._mail = mail

    def inspect_sent_operation(self, operation_id: str) -> InspectionResult:
        try:
            count = self._mail.count_sent_by_operation_id(operation_id)
            message_id = None
            if count == 1:
                message_id = self._mail.find_sent_by_operation_id(operation_id)
            return InspectionResult(match_count=count, message_id=message_id, available=True)
        except Exception as exc:  # noqa: BLE001
            return InspectionResult(
                match_count=0,
                available=False,
                detail=str(exc),
            )
