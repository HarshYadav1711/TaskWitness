"""In-memory operator runtime: one active run, worker thread, UI coordination.

Durable execution/recovery state remains in the TaskWitness journal.
This registry only coordinates the live operator console.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from taskwitness.control import (
    CallbackProgressSink,
    InMemoryProgressCollector,
    MultiplexProgressSink,
    RunControl,
)
from taskwitness.control.approval import ApprovalDecision, ApprovalRequest
from taskwitness.control.progress import ProgressEvent
from taskwitness.interpretation.interpreter import GoalInterpreter
from taskwitness.interpretation.types import (
    InterpretationResult,
    InterpretationStatus,
    ModelClientError,
)
from taskwitness.journal import Journal, default_journal_path
from taskwitness.operator.approval import ApprovalError, WebApprovalProvider
from taskwitness.schemas import RunState, TaskSpec
from taskwitness.verify_demo import run_verification
from taskwitness.workflow import RecruitingWorkflow, config_from_taskspec

MAX_GOAL_LENGTH = 4000
SOURCE_LABEL = "candidates.csv"


class OperatorError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ActiveRun:
    run_id: str
    goal: str
    mode: str  # natural_language | validated_plan
    created_at: str = field(default_factory=_utc_now)
    run_state: RunState = RunState.ready
    interpretation_status: Optional[str] = None
    clarification_question: Optional[str] = None
    error: Optional[str] = None
    journal_run_id: Optional[str] = None
    task_spec: Optional[dict[str, Any]] = None
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: Optional[dict[str, Any]] = None
    pause_requested: bool = False
    execution_state: Optional[str] = None
    verification: Optional[dict[str, Any]] = None
    evidence_path: Optional[str] = None
    verified_complete: Optional[bool] = None
    final_message: Optional[str] = None
    terminal: bool = False

    # runtime handles (not serialized)
    control: RunControl | None = field(default=None, repr=False)
    approval: WebApprovalProvider | None = field(default=None, repr=False)
    progress: InMemoryProgressCollector | None = field(default=None, repr=False)
    journal: Journal | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


def _event_to_dict(event: ProgressEvent) -> dict[str, Any]:
    return {
        "timestamp": event.timestamp.isoformat(),
        "run_state": event.run_state.value,
        "message": event.message,
        "candidate_id": event.candidate_id,
        "action": event.action,
        "event_type": event.event_type,
    }


def _approval_to_dict(request: ApprovalRequest | None) -> dict[str, Any] | None:
    if request is None:
        return None
    return {
        "approval_id": request.approval_id,
        "action": request.action.value,
        "candidate_id": request.candidate_id,
        "target": request.target,
        "reason": request.reason,
        "operation_id": request.operation_id,
    }


class OperatorRuntime:
    """Coordinates at most one active operator run for the local prototype."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        headed: bool = True,
        slow_mo_ms: int = 0,
        journal_path: Path | str | None = None,
        evidence_root: Path | str | None = None,
        source_root: Path | None = None,
        demo_task_spec: TaskSpec | None = None,
        interpreter: GoalInterpreter | None = None,
        interpreter_factory: Callable[[], GoalInterpreter] | None = None,
        workflow_hooks: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url
        self.headed = headed
        self.slow_mo_ms = slow_mo_ms
        self.journal_path = Path(journal_path) if journal_path else default_journal_path()
        self.evidence_root = Path(evidence_root) if evidence_root else Path("evidence")
        self.source_root = source_root or Path(".")
        self.demo_task_spec = demo_task_spec
        self._interpreter = interpreter
        self._interpreter_factory = interpreter_factory
        self._workflow_hooks = workflow_hooks or {}
        self._lock = threading.RLock()
        self._active: ActiveRun | None = None
        self._history: dict[str, ActiveRun] = {}

    @property
    def demo_mode(self) -> bool:
        return self.demo_task_spec is not None

    def config_snapshot(self) -> dict[str, Any]:
        return {
            "demo_mode": self.demo_mode,
            "source_label": SOURCE_LABEL,
            "base_url": self.base_url,
            "headed": self.headed,
            "max_goal_length": MAX_GOAL_LENGTH,
            "one_active_run": True,
            "polling_note": (
                "Operator UI polls GET /api/runs/{id} about every 500ms. "
                "Polling was chosen over WebSockets for local simplicity and reliability."
            ),
        }

    def get_run(self, run_id: str) -> ActiveRun | None:
        with self._lock:
            if self._active and self._active.run_id == run_id:
                return self._active
            return self._history.get(run_id)

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise OperatorError("run not found")
        with self._lock:
            return self._snapshot_locked(run)

    def current_active_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if self._active is None:
                return None
            return self._snapshot_locked(self._active)

    def _snapshot_locked(self, run: ActiveRun) -> dict[str, Any]:
        pause_label = None
        if run.pause_requested and run.run_state not in {
            RunState.paused,
            RunState.awaiting_approval,
        } and not run.terminal:
            pause_label = "pausing"
        return {
            "run_id": run.run_id,
            "journal_run_id": run.journal_run_id,
            "goal": run.goal,
            "mode": run.mode,
            "created_at": run.created_at,
            "run_state": run.run_state.value,
            "pause_requested": run.pause_requested,
            "pause_label": pause_label,
            "interpretation_status": run.interpretation_status,
            "clarification_question": run.clarification_question,
            "error": run.error,
            "task_spec": run.task_spec,
            "events": list(run.events),
            "event_count": len(run.events),
            "pending_approval": run.pending_approval,
            "execution_state": run.execution_state,
            "verification": run.verification,
            "evidence_path": run.evidence_path,
            "verified_complete": run.verified_complete,
            "final_message": run.final_message,
            "terminal": run.terminal,
            "source_label": SOURCE_LABEL,
        }

    def start_run(
        self,
        *,
        goal: str | None = None,
        mode: str = "natural_language",
    ) -> dict[str, Any]:
        mode = (mode or "natural_language").strip().lower()
        if mode not in {"natural_language", "validated_plan"}:
            raise OperatorError("mode must be natural_language or validated_plan")

        if mode == "validated_plan":
            if self.demo_task_spec is None:
                raise OperatorError(
                    "Validated Plan Demo Mode is not enabled. "
                    "Start the operator with --demo-plan <path>."
                )
            clean_goal = (goal or "").strip() or "(validated plan demo)"
        else:
            clean_goal = (goal or "").strip()
            if not clean_goal:
                raise OperatorError("goal must not be empty")
            if len(clean_goal) > MAX_GOAL_LENGTH:
                raise OperatorError(f"goal exceeds maximum length ({MAX_GOAL_LENGTH})")

        with self._lock:
            if self._active is not None and not self._active.terminal:
                raise OperatorError(
                    "A run is already active. This local prototype supports one active run at a time."
                )
            run_id = str(uuid.uuid4())
            run = ActiveRun(
                run_id=run_id,
                goal=clean_goal,
                mode=mode,
                run_state=RunState.planning,
            )
            self._active = run
            self._history[run_id] = run

        thread = threading.Thread(
            target=self._worker,
            args=(run_id, mode, clean_goal),
            name=f"tw-operator-{run_id[:8]}",
            daemon=True,
        )
        run.thread = thread
        thread.start()
        return self.snapshot(run_id)

    def pause(self, run_id: str) -> dict[str, Any]:
        run = self._require_active(run_id)
        if run.terminal:
            raise OperatorError("cannot pause a terminal run")
        if run.control is None:
            raise OperatorError("run control is not ready yet")
        run.control.request_pause()
        with self._lock:
            run.pause_requested = True
        self._append_event(
            run,
            ProgressEvent(
                run_state=run.run_state,
                message="Pause requested — will halt at the next safe checkpoint.",
                event_type="control",
            ),
        )
        return self.snapshot(run_id)

    def resume(self, run_id: str) -> dict[str, Any]:
        run = self._require_active(run_id)
        if run.terminal:
            raise OperatorError("cannot resume a terminal run")
        if run.control is None:
            raise OperatorError("run control is not ready yet")
        if not run.pause_requested and run.control.state != RunState.paused:
            raise OperatorError("run is not paused")
        run.control.resume()
        with self._lock:
            run.pause_requested = False
        self._append_event(
            run,
            ProgressEvent(
                run_state=RunState.running,
                message="Resume requested — execution continuing.",
                event_type="control",
            ),
        )
        return self.snapshot(run_id)

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        decision: str,
    ) -> dict[str, Any]:
        run = self._require_active(run_id)
        if run.approval is None:
            raise OperatorError("no approval provider for this run")
        try:
            dec = ApprovalDecision(decision.strip().lower())
        except ValueError as exc:
            raise OperatorError("decision must be approved or rejected") from exc
        try:
            request = run.approval.resolve(approval_id, dec)
        except ApprovalError as exc:
            raise OperatorError(str(exc)) from exc
        self._append_event(
            run,
            ProgressEvent(
                run_state=RunState.running,
                message=(
                    f"Approval {dec.value} for {request.action.value} "
                    f"on {request.candidate_id}."
                ),
                candidate_id=request.candidate_id,
                action=request.action.value,
                event_type="approval",
            ),
        )
        return self.snapshot(run_id)

    def _require_active(self, run_id: str) -> ActiveRun:
        with self._lock:
            if self._active is None or self._active.run_id != run_id:
                # Allow resolving against historical only for read — mutations need active
                raise OperatorError("run is not the active operator run")
            return self._active

    def _append_event(self, run: ActiveRun, event: ProgressEvent) -> None:
        with self._lock:
            run.events.append(_event_to_dict(event))
            # Keep UI run_state loosely aligned with meaningful progress states.
            if not run.terminal and event.run_state in {
                RunState.running,
                RunState.paused,
                RunState.awaiting_approval,
                RunState.recovering,
                RunState.verifying,
                RunState.planning,
            }:
                run.run_state = event.run_state
            if run.control is not None:
                run.pause_requested = run.control.pause_requested

    def _set_pending(self, run: ActiveRun, request: ApprovalRequest | None) -> None:
        with self._lock:
            run.pending_approval = _approval_to_dict(request)

    def _mark_terminal(self, run: ActiveRun, state: RunState, message: str | None = None) -> None:
        with self._lock:
            run.terminal = True
            run.run_state = state
            run.pending_approval = None
            run.pause_requested = False
            if message:
                run.final_message = message
            if run.control is not None:
                run.control.mark_terminal(state)

    def _get_interpreter(self) -> GoalInterpreter:
        if self._interpreter is not None:
            return self._interpreter
        if self._interpreter_factory is not None:
            return self._interpreter_factory()
        return GoalInterpreter.from_env()

    def _worker(self, run_id: str, mode: str, goal: str) -> None:
        run = self.get_run(run_id)
        assert run is not None
        try:
            self._append_event(
                run,
                ProgressEvent(
                    run_state=RunState.planning,
                    message=(
                        "Validated plan demo — skipping live interpretation."
                        if mode == "validated_plan"
                        else "Interpreting plain-English goal…"
                    ),
                    event_type="planning",
                ),
            )

            if mode == "validated_plan":
                assert self.demo_task_spec is not None
                spec = self.demo_task_spec
                with self._lock:
                    run.interpretation_status = InterpretationStatus.ready.value
                    run.task_spec = spec.model_dump(mode="json")
            else:
                try:
                    interpreter = self._get_interpreter()
                except ModelClientError as exc:
                    with self._lock:
                        run.interpretation_status = InterpretationStatus.model_error.value
                        run.error = str(exc)
                    self._append_event(
                        run,
                        ProgressEvent(
                            run_state=RunState.failed,
                            message=str(exc),
                            event_type="error",
                        ),
                    )
                    self._mark_terminal(run, RunState.failed, "Model configuration missing or invalid.")
                    return

                result: InterpretationResult = interpreter.interpret(goal)
                with self._lock:
                    run.interpretation_status = result.status.value
                    run.clarification_question = result.clarification_question
                    run.error = result.error
                    if result.task_spec is not None:
                        run.task_spec = result.task_spec.model_dump(mode="json")

                if result.status is InterpretationStatus.needs_clarification:
                    self._append_event(
                        run,
                        ProgressEvent(
                            run_state=RunState.ready,
                            message=f"Clarification needed: {result.clarification_question}",
                            event_type="clarification",
                        ),
                    )
                    self._mark_terminal(
                        run,
                        RunState.ready,
                        "Clarification required before execution.",
                    )
                    # Use ready as terminal-ish stop — mark terminal so another run can start
                    return

                if result.status is not InterpretationStatus.ready or result.task_spec is None:
                    msg = result.error or f"Interpretation {result.status.value}"
                    self._append_event(
                        run,
                        ProgressEvent(
                            run_state=RunState.failed,
                            message=msg,
                            event_type="error",
                        ),
                    )
                    self._mark_terminal(run, RunState.failed, msg)
                    return

                spec = result.task_spec

            # Preserve authority for final assert / UI
            original_authority = spec.authority.model_copy()

            self._append_event(
                run,
                ProgressEvent(
                    run_state=RunState.running,
                    message="Execution started.",
                    event_type="state",
                ),
            )

            journal = Journal(self.journal_path)
            progress = InMemoryProgressCollector()
            approval = WebApprovalProvider()
            approval.on_pending_changed = lambda req: self._set_pending(run, req)

            def on_state(state: RunState) -> None:
                progress.emit(
                    ProgressEvent(
                        run_state=state,
                        message=f"Run state → {state.value}",
                        event_type="state",
                    )
                )

            control = RunControl(on_state_change=on_state)
            sink = MultiplexProgressSink(
                progress,
                CallbackProgressSink(lambda ev: self._append_event(run, ev)),
            )

            with self._lock:
                run.journal = journal
                run.progress = progress
                run.approval = approval
                run.control = control
                run.run_state = RunState.running

            config, _ = config_from_taskspec(
                spec,
                headed=self.headed,
                base_url=self.base_url,
            )
            config.slow_mo_ms = self.slow_mo_ms

            workflow = RecruitingWorkflow(
                config,
                run_control=control,
                approval_provider=approval,
                progress=sink,
                journal=journal,
                close_journal=False,
                **self._workflow_hooks,
            )
            browser_result = workflow.run()

            with self._lock:
                run.journal_run_id = browser_result.run_id
                run.execution_state = browser_result.run_state.value
                run.task_spec = spec.model_dump(mode="json")
                # Authority must remain unchanged
                assert spec.authority == original_authority

            self._append_event(
                run,
                ProgressEvent(
                    run_state=browser_result.run_state,
                    message=(
                        f"Execution finished ({browser_result.run_state.value}). "
                        "Verifying final state independently…"
                    ),
                    event_type="state",
                ),
            )

            if not browser_result.run_id:
                self._mark_terminal(
                    run,
                    RunState.failed,
                    "Execution finished without a journal run_id; cannot verify.",
                )
                journal.close()
                return

            with self._lock:
                run.run_state = RunState.verifying

            vresult, package = run_verification(
                run_id=browser_result.run_id,
                journal=journal,
                base_url=self.base_url,
                headed=self.headed,
                evidence_root=self.evidence_root,
                source_root=self.source_root,
                progress=progress,
                desk=self._workflow_hooks.get("desk"),
                mail=self._workflow_hooks.get("mail"),
            )

            counts = vresult.to_dict()["counts"]
            rel_path = str(Path(package))
            try:
                rel_path = str(Path(package).resolve().relative_to(Path.cwd().resolve()))
            except ValueError:
                rel_path = str(package)

            verification_payload = {
                "overall_status": vresult.overall_status.value,
                "verified_complete": vresult.verified_complete,
                "counts": counts,
                "expected_candidate_ids": list(vresult.expected_candidate_ids),
                "checks": [c.to_dict() for c in vresult.checks],
            }

            if vresult.verified_complete:
                final_msg = "Goal verified"
                term_state = RunState.completed
            elif vresult.overall_status.value == "incomplete":
                final_msg = "Goal not fully completed"
                term_state = (
                    RunState.partial
                    if browser_result.run_state == RunState.partial
                    else RunState.completed
                )
            elif vresult.overall_status.value == "blocked":
                final_msg = "Completion could not be verified safely"
                term_state = browser_result.run_state
            else:
                final_msg = "Final state did not match requested goal"
                term_state = (
                    browser_result.run_state
                    if browser_result.run_state != RunState.completed
                    else RunState.failed
                )

            # Prefer execution PARTIAL when that was the workflow outcome
            if browser_result.run_state == RunState.partial:
                term_state = RunState.partial

            with self._lock:
                run.verification = verification_payload
                run.evidence_path = rel_path.replace("\\", "/")
                run.verified_complete = vresult.verified_complete
                run.final_message = final_msg

            self._append_event(
                run,
                ProgressEvent(
                    run_state=term_state,
                    message=final_msg,
                    event_type="verification",
                ),
            )
            self._mark_terminal(run, term_state, final_msg)
            journal.close()

        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            msg = f"Operator run failed: {exc}"
            self._append_event(
                run,
                ProgressEvent(
                    run_state=RunState.failed,
                    message=msg,
                    event_type="error",
                ),
            )
            with self._lock:
                run.error = str(exc)
            self._mark_terminal(run, RunState.failed, msg)
