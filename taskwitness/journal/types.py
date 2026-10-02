"""Journal domain types and action lifecycle states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ActionState(str, Enum):
    planned = "planned"
    in_progress = "in_progress"
    succeeded = "succeeded"
    unknown = "unknown"
    recovered = "recovered"
    rejected = "rejected"
    blocked = "blocked"
    failed = "failed"


# Allowed transitions for side-effect lifecycle (small explicit set).
ALLOWED_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.planned: frozenset(
        {
            ActionState.in_progress,
            ActionState.rejected,
            ActionState.blocked,
            ActionState.failed,
        }
    ),
    ActionState.in_progress: frozenset(
        {
            ActionState.succeeded,
            ActionState.unknown,
            ActionState.failed,
            ActionState.blocked,
        }
    ),
    ActionState.unknown: frozenset(
        {
            ActionState.recovered,
            ActionState.blocked,
            ActionState.in_progress,  # controlled same-operation retry
            ActionState.failed,
        }
    ),
    ActionState.recovered: frozenset(),
    ActionState.succeeded: frozenset(),
    ActionState.rejected: frozenset(),
    ActionState.blocked: frozenset(),
    ActionState.failed: frozenset(),
}


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    created_at: str
    updated_at: str
    state: str
    task_spec_json: str
    goal_summary: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass(frozen=True)
class ActionRecord:
    action_key: str
    run_id: str
    candidate_id: str
    action_type: str
    payload_json: str
    state: ActionState
    attempt_count: int
    created_at: str
    updated_at: str
    operation_id: Optional[str] = None
    last_error: Optional[str] = None
    recovery_note: Optional[str] = None
