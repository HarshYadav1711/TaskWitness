"""Phase 7 operator runtime and API tests (fakes; no live model / Chromium)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taskwitness.browser.talentdesk import VisibleCandidate
from taskwitness.control.approval import ApprovalDecision, ApprovalRequest, new_approval_id
from taskwitness.interpretation.types import InterpretationResult, InterpretationStatus
from taskwitness.operator.app import create_app
from taskwitness.operator.approval import ApprovalError, WebApprovalProvider
from taskwitness.operator.runtime import OperatorError, OperatorRuntime
from taskwitness.schemas import ActionType, Authority, RunState, TaskSpec
from taskwitness.testing.fakes import FakeTalentDesk, FakeTeamMail

ROOT = Path(__file__).resolve().parents[1]
CSV = str(ROOT / "data" / "candidates.csv")


def _base_spec() -> TaskSpec:
    return TaskSpec(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[
            ActionType.prepare_followup,
            ActionType.set_stage,
            ActionType.send_message,
        ],
        target_stage="Interview Ready",
        authority=Authority(send_message=False, change_stage=True),
    )


class FakeInterpreter:
    def __init__(self, result: InterpretationResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def interpret(self, goal: str) -> InterpretationResult:
        self.calls.append(goal)
        return self.result


def _seed_desk() -> FakeTalentDesk:
    desk = FakeTalentDesk()
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-001",
            name="Asha Verma",
            email="asha.verma@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Phone Screen",
        )
    )
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-002",
            name="Jordan Lee",
            email="jordan.lee@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Recruiter Review",
        )
    )
    return desk


def _runtime(tmp_path: Path, interpreter=None, demo_spec=None, **hooks) -> OperatorRuntime:
    desk = hooks.pop("desk", _seed_desk())
    mail = hooks.pop("mail", FakeTeamMail())
    return OperatorRuntime(
        base_url="http://127.0.0.1:9",
        headed=False,
        journal_path=tmp_path / "journal.sqlite3",
        evidence_root=tmp_path / "evidence",
        source_root=ROOT,
        demo_task_spec=demo_spec,
        interpreter=interpreter,
        workflow_hooks={"desk": desk, "mail": mail, **hooks},
    )


def _wait_until(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


# --- WebApprovalProvider -------------------------------------------------


def test_web_approval_resolves_once():
    provider = WebApprovalProvider()
    req = ApprovalRequest(
        approval_id=new_approval_id(),
        action=ActionType.send_message,
        candidate_id="CAND-001",
        target="asha.verma@example.test",
        reason="authority false",
        operation_id="op-1",
    )
    box: dict = {}

    def worker():
        box["decision"] = provider.request_approval(req)

    t = threading.Thread(target=worker)
    t.start()
    _wait_until(lambda: provider.pending is not None)
    provider.resolve(req.approval_id, ApprovalDecision.APPROVED)
    t.join(timeout=2)
    assert box["decision"] is ApprovalDecision.APPROVED
    with pytest.raises(ApprovalError):
        provider.resolve(req.approval_id, ApprovalDecision.APPROVED)


def test_web_approval_rejects_wrong_id():
    provider = WebApprovalProvider()
    req = ApprovalRequest(
        approval_id="apr-real",
        action=ActionType.send_message,
        candidate_id="CAND-001",
        target="x",
        reason="r",
    )

    def worker():
        provider.request_approval(req)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    _wait_until(lambda: provider.pending is not None)
    with pytest.raises(ApprovalError):
        provider.resolve("apr-wrong", ApprovalDecision.REJECTED)
    provider.resolve("apr-real", ApprovalDecision.REJECTED)
    t.join(timeout=2)


# --- Runtime -------------------------------------------------------------


def test_empty_goal_rejected(tmp_path: Path):
    rt = _runtime(tmp_path, interpreter=FakeInterpreter(
        InterpretationResult(status=InterpretationStatus.ready, original_goal="", task_spec=_base_spec())
    ))
    with pytest.raises(OperatorError, match="empty"):
        rt.start_run(goal="  ", mode="natural_language")


def test_one_active_run_limit(tmp_path: Path):
    # Hold approval so the first run stays active.
    rt = _runtime(
        tmp_path,
        demo_spec=_base_spec(),
    )
    snap = rt.start_run(mode="validated_plan")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.snapshot(run_id)["pending_approval"] is not None, timeout=10)
    with pytest.raises(OperatorError, match="already active"):
        rt.start_run(mode="validated_plan")
    # Resolve to finish.
    apr = rt.snapshot(run_id)["pending_approval"]
    rt.resolve_approval(run_id, apr["approval_id"], "approved")
    # Second candidate will also need approval — keep resolving until terminal
    def drain():
        while True:
            s = rt.snapshot(run_id)
            if s["terminal"]:
                return
            if s["pending_approval"]:
                rt.resolve_approval(run_id, s["pending_approval"]["approval_id"], "approved")
            time.sleep(0.05)
    drain()
    _wait_until(lambda: rt.snapshot(run_id)["terminal"])


def test_ready_interpretation_starts_workflow(tmp_path: Path):
    interp = FakeInterpreter(
        InterpretationResult(
            status=InterpretationStatus.ready,
            original_goal="do the thing",
            task_spec=_base_spec(),
        )
    )
    rt = _runtime(tmp_path, interpreter=interp)
    snap = rt.start_run(goal="do the thing")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.snapshot(run_id)["pending_approval"] is not None, timeout=10)
    assert interp.calls == ["do the thing"]
    assert rt.snapshot(run_id)["task_spec"]["authority"]["send_message"] is False


def test_needs_clarification_does_not_start_workflow(tmp_path: Path):
    interp = FakeInterpreter(
        InterpretationResult(
            status=InterpretationStatus.needs_clarification,
            original_goal="???",
            clarification_question="Which role?",
        )
    )
    rt = _runtime(tmp_path, interpreter=interp)
    snap = rt.start_run(goal="???")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.snapshot(run_id)["terminal"])
    final = rt.snapshot(run_id)
    assert final["clarification_question"] == "Which role?"
    assert final["pending_approval"] is None
    assert final["verification"] is None


def test_model_error_does_not_start_workflow(tmp_path: Path):
    interp = FakeInterpreter(
        InterpretationResult(
            status=InterpretationStatus.model_error,
            original_goal="g",
            error="LLM_API_KEY is not configured",
        )
    )
    rt = _runtime(tmp_path, interpreter=interp)
    snap = rt.start_run(goal="g")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.snapshot(run_id)["terminal"])
    final = rt.snapshot(run_id)
    assert final["run_state"] == "failed"
    assert "LLM_API_KEY" in (final["error"] or "")
    assert final["verification"] is None


def test_progress_and_approval_in_snapshot(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    snap = rt.start_run(mode="validated_plan")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.snapshot(run_id)["pending_approval"] is not None, timeout=10)
    s = rt.snapshot(run_id)
    assert s["event_count"] >= 1
    assert s["pending_approval"]["action"] == "send_message"
    assert s["pending_approval"]["candidate_id"]
    assert s["pending_approval"]["reason"]


def test_pause_resume_call_run_control(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    snap = rt.start_run(mode="validated_plan")
    run_id = snap["run_id"]
    _wait_until(lambda: rt.get_run(run_id).control is not None, timeout=10)
    rt.pause(run_id)
    assert rt.get_run(run_id).control.pause_requested is True
    # Still may be awaiting approval — resume clears pause request
    rt.resume(run_id)
    assert rt.get_run(run_id).control.pause_requested is False
    # Drain approvals so suite does not leak threads
    def drain():
        while True:
            s = rt.snapshot(run_id)
            if s["terminal"]:
                return
            if s["pending_approval"]:
                rt.resolve_approval(run_id, s["pending_approval"]["approval_id"], "rejected")
            time.sleep(0.05)
    drain()


def test_verified_result_exposed(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    snap = rt.start_run(mode="validated_plan")
    run_id = snap["run_id"]

    def drain_approve():
        while True:
            s = rt.snapshot(run_id)
            if s["terminal"]:
                return s
            if s["pending_approval"]:
                rt.resolve_approval(run_id, s["pending_approval"]["approval_id"], "approved")
            time.sleep(0.05)

    final = drain_approve()
    assert final["verification"] is not None
    assert final["verified_complete"] is True
    assert final["final_message"] == "Goal verified"
    assert final["evidence_path"]
    assert final["task_spec"]["authority"]["send_message"] is False


def test_incomplete_verification_no_goal_verified_wording(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    snap = rt.start_run(mode="validated_plan")
    run_id = snap["run_id"]

    def drain_reject():
        while True:
            s = rt.snapshot(run_id)
            if s["terminal"]:
                return s
            if s["pending_approval"]:
                rt.resolve_approval(run_id, s["pending_approval"]["approval_id"], "rejected")
            time.sleep(0.05)

    final = drain_reject()
    assert final["verified_complete"] is False
    assert final["final_message"] != "Goal verified"
    assert "Goal verified" not in (final["final_message"] or "")
    assert final["verification"]["overall_status"] == "incomplete"


def test_terminal_run_allows_next(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    first = rt.start_run(mode="validated_plan")
    run_id = first["run_id"]

    def drain():
        while True:
            s = rt.snapshot(run_id)
            if s["terminal"]:
                return
            if s["pending_approval"]:
                rt.resolve_approval(run_id, s["pending_approval"]["approval_id"], "rejected")
            time.sleep(0.05)

    drain()
    second = rt.start_run(mode="validated_plan")
    assert second["run_id"] != run_id


# --- API -----------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path):
    rt = _runtime(tmp_path, demo_spec=_base_spec())
    app = create_app(rt)
    with TestClient(app) as c:
        c.app.state.runtime = rt  # type: ignore[attr-defined]
        yield c, rt


def test_operator_page_loads(client):
    c, _ = client
    res = c.get("/operator")
    assert res.status_code == 200
    assert "TaskWitness" in res.text
    assert "Business goal" in res.text
    assert "Execution trace" in res.text


def test_api_start_validation(client):
    c, _ = client
    res = c.post("/api/runs", json={"goal": "", "mode": "natural_language"})
    assert res.status_code == 400


def test_api_pause_resume_approval(client):
    c, rt = client
    start = c.post("/api/runs", json={"mode": "validated_plan"})
    assert start.status_code == 200
    run_id = start.json()["run_id"]
    _wait_until(lambda: c.get(f"/api/runs/{run_id}").json()["pending_approval"] is not None)

    pause = c.post(f"/api/runs/{run_id}/pause")
    assert pause.status_code == 200
    assert pause.json()["pause_requested"] is True

    resume = c.post(f"/api/runs/{run_id}/resume")
    assert resume.status_code == 200

    snap = c.get(f"/api/runs/{run_id}").json()
    apr = snap["pending_approval"]
    bad = c.post(
        f"/api/runs/{run_id}/approvals/not-real",
        json={"decision": "approved"},
    )
    assert bad.status_code == 400

    ok = c.post(
        f"/api/runs/{run_id}/approvals/{apr['approval_id']}",
        json={"decision": "rejected"},
    )
    assert ok.status_code == 200
    # replay
    replay = c.post(
        f"/api/runs/{run_id}/approvals/{apr['approval_id']}",
        json={"decision": "approved"},
    )
    assert replay.status_code == 400

    # finish remaining approvals
    while True:
        s = c.get(f"/api/runs/{run_id}").json()
        if s["terminal"]:
            break
        if s["pending_approval"]:
            c.post(
                f"/api/runs/{run_id}/approvals/{s['pending_approval']['approval_id']}",
                json={"decision": "rejected"},
            )
        time.sleep(0.05)

    final = c.get(f"/api/runs/{run_id}").json()
    assert final["verified_complete"] is False
    assert final["final_message"] != "Goal verified"


def test_api_rejects_extra_fields(client):
    c, _ = client
    res = c.post(
        "/api/runs",
        json={"goal": "x", "source_file": "evil.csv", "mode": "natural_language"},
    )
    assert res.status_code == 422
