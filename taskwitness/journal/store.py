"""SQLite-backed TaskWitness execution journal."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from taskwitness.journal.types import (
    ALLOWED_TRANSITIONS,
    ActionRecord,
    ActionState,
    RunRecord,
)
from taskwitness.schemas import TaskSpec

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    goal_summary TEXT,
    task_spec_json TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    action_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    operation_id TEXT,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT,
    recovery_note TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_actions_run ON actions(run_id);
CREATE INDEX IF NOT EXISTS idx_actions_state ON actions(state);
"""


def default_journal_path() -> Path:
    """Default local assessment journal path (not demo_env)."""
    import os

    override = os.environ.get("TASKWITNESS_JOURNAL", "").strip()
    if override:
        return Path(override)
    return Path(".taskwitness") / "journal.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JournalError(RuntimeError):
    pass


class IllegalTransitionError(JournalError):
    pass


class Journal:
    """Small explicit journal API for durable effect tracking."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_journal_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Allow worker-thread workflow demos (pause harness) to use the same journal.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- runs -------------------------------------------------------------

    def create_run(
        self,
        *,
        task_spec: TaskSpec | dict[str, Any] | str,
        goal_summary: str | None = None,
        run_id: str | None = None,
        state: str = "running",
    ) -> RunRecord:
        with self._lock:
            rid = run_id or str(uuid.uuid4())
            if isinstance(task_spec, TaskSpec):
                spec_json = task_spec.model_dump_json()
            elif isinstance(task_spec, dict):
                spec_json = json.dumps(task_spec, sort_keys=True)
            else:
                spec_json = str(task_spec)
            now = _utc_now()
            self._conn.execute(
                "INSERT INTO runs "
                "(run_id, created_at, updated_at, state, goal_summary, task_spec_json, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (rid, now, now, state, goal_summary, spec_json),
            )
            self._conn.commit()
            record = self.load_run(rid)
            assert record is not None
            return record

    def finish_run(self, run_id: str, *, state: str) -> RunRecord:
        with self._lock:
            now = _utc_now()
            self._conn.execute(
                "UPDATE runs SET state = ?, updated_at = ?, finished_at = ? WHERE run_id = ?",
                (state, now, now, run_id),
            )
            self._conn.commit()
            record = self.load_run(run_id)
            if record is None:
                raise JournalError(f"unknown run_id: {run_id}")
            return record

    def load_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return RunRecord(
                run_id=row["run_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                state=row["state"],
                goal_summary=row["goal_summary"],
                task_spec_json=row["task_spec_json"],
                finished_at=row["finished_at"],
            )

    def load_task_spec(self, run_id: str) -> TaskSpec:
        run = self.load_run(run_id)
        if run is None:
            raise JournalError(f"unknown run_id: {run_id}")
        return TaskSpec.model_validate_json(run.task_spec_json)

    # --- actions ----------------------------------------------------------

    def plan_action(
        self,
        *,
        action_key: str,
        run_id: str,
        candidate_id: str,
        action_type: str,
        payload: dict[str, Any],
        operation_id: str | None = None,
    ) -> ActionRecord:
        with self._lock:
            existing = self.get_action(action_key)
            if existing is not None:
                return existing
            now = _utc_now()
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            self._conn.execute(
                "INSERT INTO actions "
                "(action_key, run_id, candidate_id, action_type, operation_id, payload_json, "
                "state, attempt_count, created_at, updated_at, last_error, recovery_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL)",
                (
                    action_key,
                    run_id,
                    candidate_id,
                    action_type,
                    operation_id,
                    payload_json,
                    ActionState.planned.value,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            record = self.get_action(action_key)
            assert record is not None
            return record

    def mark_in_progress(self, action_key: str) -> ActionRecord:
        """Write-ahead: commit IN_PROGRESS and bump attempt_count before side effect."""
        with self._lock:
            action = self._require(action_key)
            self._assert_transition(action.state, ActionState.in_progress)
            now = _utc_now()
            self._conn.execute(
                "UPDATE actions SET state = ?, attempt_count = attempt_count + 1, "
                "updated_at = ?, last_error = NULL WHERE action_key = ?",
                (ActionState.in_progress.value, now, action_key),
            )
            self._conn.commit()
            return self._require(action_key)

    def mark_succeeded(self, action_key: str, *, note: str | None = None) -> ActionRecord:
        return self._set_state(action_key, ActionState.succeeded, recovery_note=note)

    def mark_unknown(self, action_key: str, *, error: str) -> ActionRecord:
        return self._set_state(
            action_key,
            ActionState.unknown,
            last_error=error,
        )

    def mark_recovered(self, action_key: str, *, note: str) -> ActionRecord:
        return self._set_state(
            action_key,
            ActionState.recovered,
            recovery_note=note,
            last_error=None,
        )

    def mark_rejected(self, action_key: str, *, note: str | None = None) -> ActionRecord:
        with self._lock:
            action = self._require(action_key)
            self._assert_transition(action.state, ActionState.rejected)
            # Rejection must not increment attempt_count (no side effect attempted).
            now = _utc_now()
            self._conn.execute(
                "UPDATE actions SET state = ?, updated_at = ?, recovery_note = ? "
                "WHERE action_key = ?",
                (ActionState.rejected.value, now, note, action_key),
            )
            self._conn.commit()
            return self._require(action_key)

    def mark_blocked(self, action_key: str, *, note: str, error: str | None = None) -> ActionRecord:
        return self._set_state(
            action_key,
            ActionState.blocked,
            recovery_note=note,
            last_error=error,
        )

    def mark_failed(self, action_key: str, *, error: str) -> ActionRecord:
        return self._set_state(action_key, ActionState.failed, last_error=error)

    def get_action(self, action_key: str) -> ActionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM actions WHERE action_key = ?", (action_key,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_action(row)

    def list_actions(self, run_id: str) -> list[ActionRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM actions WHERE run_id = ? ORDER BY created_at, action_key",
                (run_id,),
            ).fetchall()
            return [self._row_to_action(r) for r in rows]

    def find_recoverable_actions(self, run_id: str | None = None) -> list[ActionRecord]:
        with self._lock:
            if run_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM actions WHERE state = ? ORDER BY updated_at",
                    (ActionState.unknown.value,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM actions WHERE run_id = ? AND state = ? ORDER BY updated_at",
                    (run_id, ActionState.unknown.value),
                ).fetchall()
            return [self._row_to_action(r) for r in rows]

    def reset(self) -> None:
        """Development/test cleanup: wipe journal tables. Does not touch demo_env."""
        with self._lock:
            self._conn.execute("DELETE FROM actions")
            self._conn.execute("DELETE FROM runs")
            self._conn.commit()

    # --- internals --------------------------------------------------------

    def _require(self, action_key: str) -> ActionRecord:
        action = self.get_action(action_key)
        if action is None:
            raise JournalError(f"unknown action_key: {action_key}")
        return action

    def _assert_transition(self, current: ActionState, new: ActionState) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if new not in allowed:
            raise IllegalTransitionError(
                f"illegal journal transition {current.value} -> {new.value}"
            )

    def _set_state(
        self,
        action_key: str,
        new_state: ActionState,
        *,
        last_error: str | None = None,
        recovery_note: str | None = None,
    ) -> ActionRecord:
        with self._lock:
            action = self._require(action_key)
            self._assert_transition(action.state, new_state)
            now = _utc_now()
            err = last_error if last_error is not None else action.last_error
            note = recovery_note if recovery_note is not None else action.recovery_note
            if last_error is None and new_state in {ActionState.succeeded, ActionState.recovered}:
                err = None
            self._conn.execute(
                "UPDATE actions SET state = ?, updated_at = ?, last_error = ?, recovery_note = ? "
                "WHERE action_key = ?",
                (new_state.value, now, err, note, action_key),
            )
            self._conn.commit()
            return self._require(action_key)

    @staticmethod
    def _row_to_action(row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            action_key=row["action_key"],
            run_id=row["run_id"],
            candidate_id=row["candidate_id"],
            action_type=row["action_type"],
            operation_id=row["operation_id"],
            payload_json=row["payload_json"],
            state=ActionState(row["state"]),
            attempt_count=int(row["attempt_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_error=row["last_error"],
            recovery_note=row["recovery_note"],
        )
