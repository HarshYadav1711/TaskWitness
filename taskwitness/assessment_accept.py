"""Phase 8 assessment acceptance harness.

Exercises finished TaskWitness through the operator UI (Validated Plan Demo Mode
by default). Does not redesign product subsystems.

Live natural-language mode is optional and skipped without credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from playwright.sync_api import sync_playwright

from demo_env.db import (
    arm_fail_after_send_commit_once,
    connect,
    get_candidate,
    list_messages,
)
from demo_env.seed import reset_environment
from taskwitness.candidate_source import filter_candidates, load_candidates
from taskwitness.journal import ActionState, Journal
from taskwitness.operator.app import create_app
from taskwitness.operator.runtime import OperatorRuntime
from taskwitness.schemas import ActionType, TaskSpec
from taskwitness.verification.evidence import validate_manifest_hashes
from taskwitness.workflow import make_operation_id

ROOT = Path(__file__).resolve().parents[1]

BASE_PLAN = ROOT / "examples" / "base-plan.json"
VARIATION_PLAN = ROOT / "examples" / "variation-plan.json"

SCENARIOS = ("base", "variation", "recovery", "rejection", "pause", "all")


@dataclass
class ScenarioResult:
    name: str
    status: str  # PASS | FAIL | SKIPPED
    run_id: Optional[str] = None
    journal_run_id: Optional[str] = None
    execution_state: Optional[str] = None
    verification_status: Optional[str] = None
    verified_complete: Optional[bool] = None
    evidence_path: Optional[str] = None
    assertions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0
    error: Optional[str] = None
    mode_note: str = "Validated Plan Demo Mode (not live NL interpretation)"

    def fail(self, msg: str) -> "ScenarioResult":
        self.status = "FAIL"
        self.error = msg
        self.assertions.append(f"FAIL: {msg}")
        return self

    def ok(self, msg: str) -> None:
        self.assertions.append(f"PASS: {msg}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, *, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.15)
    raise RuntimeError(f"service not ready at {url}: {last}")


def _terminate(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class ProcessBundle:
    """Owns demo_env + in-process operator for one scenario."""

    def __init__(
        self,
        *,
        work_dir: Path,
        headed: bool,
        slow_mo_ms: int,
        demo_plan: Path,
        evidence_root: Path | None = None,
    ) -> None:
        self.work_dir = work_dir
        self.headed = headed
        self.slow_mo_ms = slow_mo_ms
        self.demo_plan = demo_plan
        self.evidence_root = evidence_root or (work_dir / "evidence")
        self.db_path = work_dir / "demo.sqlite3"
        self.journal_path = work_dir / "journal.sqlite3"
        self.demo_port = _free_port()
        self.op_port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.demo_port}"
        self.op_url = f"http://127.0.0.1:{self.op_port}"
        self.demo_proc: subprocess.Popen | None = None
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.runtime: OperatorRuntime | None = None

    def start(self, *, arm_fault: bool = False) -> None:
        reset_environment(db_path=self.db_path)
        if self.journal_path.exists():
            self.journal_path.unlink()
        self.evidence_root.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["DEMO_ENV_DB"] = str(self.db_path)
        self.demo_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "demo_env.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.demo_port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http(self.base_url + "/")

        if arm_fault:
            conn = connect(self.db_path)
            try:
                arm_fail_after_send_commit_once(conn)
                conn.commit()
            finally:
                conn.close()

        spec = TaskSpec.model_validate_json(self.demo_plan.read_text(encoding="utf-8"))
        self.runtime = OperatorRuntime(
            base_url=self.base_url,
            headed=self.headed,
            slow_mo_ms=self.slow_mo_ms,
            journal_path=self.journal_path,
            evidence_root=self.evidence_root,
            source_root=ROOT,
            demo_task_spec=spec,
        )
        app = create_app(self.runtime)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.op_port, log_level="warning"
        )
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("operator server failed to start")
        _wait_http(self.op_url + "/operator")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.server_thread is not None:
            self.server_thread.join(timeout=8)
        _terminate(self.demo_proc)
        self.demo_proc = None
        if self.runtime and self.runtime._active and self.runtime._active.journal:
            try:
                self.runtime._active.journal.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "ProcessBundle":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _drive_operator_ui(
    *,
    op_url: str,
    headed: bool,
    decision: str,
    pause_once: bool = False,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Drive Validated Plan Demo Mode through the operator page."""
    out: dict[str, Any] = {
        "run_id": None,
        "snapshot": None,
        "pause_observed": False,
        "resume_observed": False,
        "approval_seen": False,
        "events": [],
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        try:
            page.goto(op_url + "/operator", wait_until="domcontentloaded")
            page.get_by_role("button", name="Start validated plan").click()

            paused_once = False
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                dialog = page.locator("#approval-dialog")
                pause_btn = page.locator("#btn-pause")
                resume_btn = page.locator("#btn-resume")

                if pause_once and not paused_once and not dialog.is_visible():
                    if pause_btn.is_visible():
                        pause_btn.click()
                        for _ in range(50):
                            label = page.locator("#run-state-label").inner_text()
                            if resume_btn.is_visible() or "PAUSED" in label.upper():
                                out["pause_observed"] = True
                                break
                            page.wait_for_timeout(150)
                        if resume_btn.is_visible():
                            resume_btn.click()
                            out["resume_observed"] = True
                            paused_once = True

                if dialog.is_visible():
                    out["approval_seen"] = True
                    btn_id = "btn-approve" if decision == "approved" else "btn-reject"
                    try:
                        dialog.locator(f"#{btn_id}").click(force=True, timeout=3000)
                    except Exception:  # noqa: BLE001
                        page.evaluate(f"document.getElementById('{btn_id}')?.click()")
                    page.wait_for_timeout(350)
                    continue

                ver = page.locator("#verify-summary").inner_text().strip()
                if ver and ver not in {"—", "VERIFYING…"}:
                    run_id = page.locator("#meta-run-id").inner_text().strip()
                    out["run_id"] = run_id
                    snap = _fetch_json(f"{op_url}/api/runs/{run_id}")
                    out["snapshot"] = snap
                    out["events"] = list(snap.get("events") or [])
                    break
                page.wait_for_timeout(150)
            else:
                raise TimeoutError("operator UI did not reach verification")
        finally:
            browser.close()
    return out


def _evidence_checks(path: Path | None, result: ScenarioResult) -> None:
    if path is None:
        result.fail("evidence path missing")
        return
    pkg = Path(path)
    if not pkg.is_absolute():
        pkg = (ROOT / pkg).resolve()
    if not pkg.is_dir():
        result.fail(f"evidence directory missing: {pkg}")
        return
    for name in (
        "summary.md",
        "verification.json",
        "task_spec.json",
        "journal.json",
        "manifest.json",
    ):
        if not (pkg / name).is_file():
            result.fail(f"missing evidence artifact {name}")
            return
        text = (pkg / name).read_text(encoding="utf-8", errors="ignore")
        if "LLM_API_KEY" in text or "OPENAI_API_KEY" in text:
            result.fail("evidence contains API key material")
            return
    mismatches = validate_manifest_hashes(pkg)
    if mismatches:
        result.fail(f"manifest hash mismatch: {mismatches}")
        return
    result.ok("evidence package + manifest hashes valid")
    result.evidence_path = str(pkg.relative_to(ROOT)).replace("\\", "/") if pkg.is_relative_to(ROOT) else str(pkg)


def _journal_send_actions(journal_path: Path, journal_run_id: str) -> list[Any]:
    journal = Journal(journal_path)
    try:
        return [
            a
            for a in journal.list_actions(journal_run_id)
            if a.action_type == ActionType.send_message.value
        ]
    finally:
        journal.close()


def _expected_candidates(spec: TaskSpec) -> list[str]:
    path = ROOT / spec.source_file if not Path(spec.source_file).is_file() else Path(spec.source_file)
    return [
        c.candidate_id
        for c in filter_candidates(
            load_candidates(path),
            role=spec.role,
            candidate_status=spec.candidate_status,
        )
    ]


def _assert_common_snapshot(result: ScenarioResult, snap: dict[str, Any]) -> None:
    result.run_id = snap.get("run_id")
    result.journal_run_id = snap.get("journal_run_id")
    result.execution_state = snap.get("execution_state") or snap.get("run_state")
    ver = snap.get("verification") or {}
    result.verification_status = ver.get("overall_status")
    result.verified_complete = snap.get("verified_complete")
    result.evidence_path = snap.get("evidence_path")
    auth = (snap.get("task_spec") or {}).get("authority") or {}
    if auth.get("send_message") is True and "send_message" in (
        (snap.get("task_spec") or {}).get("actions") or []
    ):
        # only fail if authority flipped unexpectedly from false plans
        pass


def run_base_scenario(
    *,
    work_dir: Path,
    headed: bool = False,
    slow_mo_ms: int = 0,
    evidence_root: Path | None = None,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(name="base", status="PASS")
    bundle = ProcessBundle(
        work_dir=work_dir,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        demo_plan=BASE_PLAN,
        evidence_root=evidence_root,
    )
    try:
        bundle.start(arm_fault=False)
        ui = _drive_operator_ui(
            op_url=bundle.op_url,
            headed=headed,
            decision="approved",
            pause_once=False,
        )
        snap = ui["snapshot"]
        assert snap is not None
        _assert_common_snapshot(result, snap)
        spec = TaskSpec.model_validate(snap["task_spec"])
        expected = _expected_candidates(spec)
        if expected != ["CAND-001", "CAND-002"]:
            return result.fail(f"unexpected candidates {expected}")
        result.ok(f"candidates {expected}")

        if not ui["approval_seen"]:
            return result.fail("approval dialog never appeared before send")
        result.ok("approval surfaced before send")

        if snap.get("execution_state") != "completed":
            return result.fail(f"execution_state={snap.get('execution_state')}")
        result.ok("execution COMPLETED")

        if snap.get("verified_complete") is not True:
            return result.fail("verified_complete is not true")
        if (snap.get("verification") or {}).get("overall_status") != "passed":
            return result.fail(f"verification={(snap.get('verification') or {}).get('overall_status')}")
        result.ok("verification VERIFIED")

        auth = spec.authority
        if auth.send_message is not False or auth.change_stage is not True:
            return result.fail(f"authority mutated: {auth}")
        result.ok("TaskSpec authority unchanged (send_message=false)")

        # Target-state assertions via demo DB (assertion-only).
        conn = connect(bundle.db_path)
        try:
            for cid in expected:
                row = get_candidate(conn, cid)
                if row is None or row["current_stage"] != "Interview Ready":
                    return result.fail(f"{cid} stage not Interview Ready")
                op = make_operation_id(candidate_id=cid, role="AI Engineering")
                sent = [m for m in list_messages(conn, "sent") if m.get("operation_id") == op]
                if len(sent) != 1:
                    return result.fail(f"{cid} sent_count={len(sent)} for {op}")
            drafts = list_messages(conn, "draft")
            # drafts may be empty after send transition
            result.details["sent_ops"] = {
                cid: make_operation_id(candidate_id=cid, role="AI Engineering")
                for cid in expected
            }
            result.details["draft_count_after"] = len(drafts)
        finally:
            conn.close()
        result.ok("stages + exactly-one Sent per operation")

        _evidence_checks(
            Path(snap["evidence_path"]) if snap.get("evidence_path") else None,
            result,
        )
        if result.status == "FAIL":
            return result
        result.details["candidate_count"] = len(expected)
        result.details["mode"] = "validated_plan"
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    finally:
        bundle.stop()
        result.elapsed_s = time.monotonic() - started
    return result


def run_variation_scenario(
    *,
    work_dir: Path,
    headed: bool = False,
    slow_mo_ms: int = 0,
    evidence_root: Path | None = None,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(name="variation", status="PASS")
    # Capture baseline stages from CSV semantics after reset.
    baseline = {
        "CAND-003": "Phone Screen",
        "CAND-005": "Technical Screen",
    }
    bundle = ProcessBundle(
        work_dir=work_dir,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        demo_plan=VARIATION_PLAN,
        evidence_root=evidence_root,
    )
    try:
        bundle.start(arm_fault=False)
        ui = _drive_operator_ui(
            op_url=bundle.op_url,
            headed=headed,
            decision="approved",  # no send approvals expected
        )
        snap = ui["snapshot"]
        assert snap is not None
        _assert_common_snapshot(result, snap)
        spec = TaskSpec.model_validate(snap["task_spec"])
        expected = _expected_candidates(spec)
        if expected != ["CAND-003", "CAND-005"]:
            return result.fail(f"unexpected Backend candidates {expected}")
        result.ok(f"Backend candidates {expected}")

        if ActionType.send_message in spec.actions or ActionType.set_stage in spec.actions:
            return result.fail("variation TaskSpec unexpectedly includes stage/send")
        result.ok("same product path; prepare_followup only")

        if snap.get("verified_complete") is not True:
            return result.fail("verified_complete is not true")
        result.ok("verification VERIFIED")

        conn = connect(bundle.db_path)
        try:
            for cid, stage in baseline.items():
                row = get_candidate(conn, cid)
                if row is None or row["current_stage"] != stage:
                    return result.fail(
                        f"{cid} stage changed: expected {stage}, got {row and row['current_stage']}"
                    )
                op = make_operation_id(candidate_id=cid, role="Backend Engineering")
                sent = [m for m in list_messages(conn, "sent") if m.get("operation_id") == op]
                if sent:
                    return result.fail(f"unexpected send for {cid}: {len(sent)}")
                drafts = [m for m in list_messages(conn, "draft") if m.get("operation_id") == op]
                if len(drafts) != 1:
                    return result.fail(f"{cid} draft_count={len(drafts)}")
            result.details["messages_sent"] = 0
        finally:
            conn.close()
        result.ok("stages unchanged; drafts present; sent=0")

        if ui["approval_seen"]:
            # Variation should not request send approval.
            return result.fail("unexpected approval dialog on variation")
        result.ok("no send approval required")

        _evidence_checks(
            Path(snap["evidence_path"]) if snap.get("evidence_path") else None,
            result,
        )
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    finally:
        bundle.stop()
        result.elapsed_s = time.monotonic() - started
    return result


def run_recovery_scenario(
    *,
    work_dir: Path,
    headed: bool = False,
    slow_mo_ms: int = 0,
    evidence_root: Path | None = None,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(name="recovery", status="PASS")
    bundle = ProcessBundle(
        work_dir=work_dir,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        demo_plan=BASE_PLAN,
        evidence_root=evidence_root,
    )
    try:
        bundle.start(arm_fault=True)
        ui = _drive_operator_ui(
            op_url=bundle.op_url,
            headed=headed,
            decision="approved",
        )
        snap = ui["snapshot"]
        assert snap is not None
        _assert_common_snapshot(result, snap)

        events = ui.get("events") or []
        recovering = any(
            (e.get("run_state") == "recovering")
            or ("uncertain" in (e.get("message") or "").lower())
            or ("recovered" in (e.get("message") or "").lower())
            for e in events
        )
        if not recovering:
            return result.fail("no recovering/uncertain/recovered progress observed")
        result.ok("recovery progress observed")

        jid = snap.get("journal_run_id")
        if not jid:
            return result.fail("missing journal_run_id")
        sends = _journal_send_actions(bundle.journal_path, jid)
        recovered = [a for a in sends if a.state is ActionState.recovered]
        if not recovered:
            return result.fail(f"no RECOVERED send actions; states={[a.state.value for a in sends]}")
        for a in recovered:
            if a.attempt_count != 1:
                return result.fail(f"attempt_count={a.attempt_count} for recovered {a.candidate_id}")
        result.ok(f"RECOVERED send(s) with attempt_count=1 ({len(recovered)})")

        # Exactly one Sent for recovered operation.
        conn = connect(bundle.db_path)
        try:
            for a in recovered:
                op = a.operation_id
                assert op
                matches = [m for m in list_messages(conn, "sent") if m.get("operation_id") == op]
                if len(matches) != 1:
                    return result.fail(f"sent matches for {op}: {len(matches)}")
                result.details["recovered_operation_id"] = op
                result.details["attempt_count"] = a.attempt_count
                result.details["sent_matches"] = 1
        finally:
            conn.close()
        result.ok("exactly one Sent artifact for recovered operation_id")

        if snap.get("verified_complete") is not True:
            return result.fail("verified_complete is not true after recovery")
        result.ok("final verification VERIFIED")

        # Evidence journal should mention recovered.
        epath = snap.get("evidence_path")
        if epath:
            pkg = Path(epath)
            if not pkg.is_absolute():
                pkg = (ROOT / pkg).resolve()
            journal_export = json.loads((pkg / "journal.json").read_text(encoding="utf-8"))
            states = [a.get("state") for a in journal_export.get("actions", [])]
            if "recovered" not in states:
                return result.fail("evidence journal.json missing recovered action")
            result.ok("evidence includes recovery history")
        _evidence_checks(Path(epath) if epath else None, result)
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    finally:
        bundle.stop()
        result.elapsed_s = time.monotonic() - started
    return result


def run_rejection_scenario(
    *,
    work_dir: Path,
    headed: bool = False,
    slow_mo_ms: int = 0,
    evidence_root: Path | None = None,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(name="rejection", status="PASS")
    bundle = ProcessBundle(
        work_dir=work_dir,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        demo_plan=BASE_PLAN,
        evidence_root=evidence_root,
    )
    try:
        bundle.start(arm_fault=False)
        ui = _drive_operator_ui(
            op_url=bundle.op_url,
            headed=headed,
            decision="rejected",
        )
        snap = ui["snapshot"]
        assert snap is not None
        _assert_common_snapshot(result, snap)

        if not ui["approval_seen"]:
            return result.fail("approval never appeared")
        result.ok("approval requested")

        if snap.get("execution_state") != "partial":
            return result.fail(f"execution_state={snap.get('execution_state')} expected partial")
        result.ok("execution PARTIAL")

        ver = snap.get("verification") or {}
        if ver.get("overall_status") != "incomplete" or snap.get("verified_complete") is not False:
            return result.fail("expected INCOMPLETE / verified_complete=false")
        result.ok("verification INCOMPLETE")

        spec = TaskSpec.model_validate(snap["task_spec"])
        if spec.authority.send_message is not False:
            return result.fail("authority.send_message mutated")
        result.ok("authority.send_message remains false")

        jid = snap.get("journal_run_id")
        sends = _journal_send_actions(bundle.journal_path, jid)
        if not sends or any(a.state is not ActionState.rejected for a in sends):
            return result.fail(f"send states={[a.state.value for a in sends]}")
        if any(a.attempt_count != 0 for a in sends):
            return result.fail("rejected send attempt_count != 0")
        result.ok("journal REJECTED with attempt_count=0")

        conn = connect(bundle.db_path)
        try:
            unintended = 0
            for a in sends:
                op = a.operation_id
                sent = [m for m in list_messages(conn, "sent") if m.get("operation_id") == op]
                unintended += len(sent)
                drafts = [m for m in list_messages(conn, "draft") if m.get("operation_id") == op]
                if len(drafts) != 1:
                    return result.fail(f"draft missing for rejected {a.candidate_id}")
            if unintended != 0:
                return result.fail(f"unintended sends={unintended}")
            result.details["unintended_sends"] = 0
        finally:
            conn.close()
        result.ok("draft remains; Sent=0")

        # Evidence incomplete work
        epath = snap.get("evidence_path")
        if epath:
            pkg = Path(epath)
            if not pkg.is_absolute():
                pkg = (ROOT / pkg).resolve()
            summary = (pkg / "summary.md").read_text(encoding="utf-8")
            if "INCOMPLETE" not in summary:
                return result.fail("summary.md missing INCOMPLETE")
            result.ok("evidence summary shows incomplete work")
        _evidence_checks(Path(epath) if epath else None, result)
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    finally:
        bundle.stop()
        result.elapsed_s = time.monotonic() - started
    return result


def run_pause_scenario(
    *,
    work_dir: Path,
    headed: bool = False,
    slow_mo_ms: int = 120,
    evidence_root: Path | None = None,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(name="pause", status="PASS")
    # Need pacing so Pause can land between side effects.
    if slow_mo_ms < 80:
        slow_mo_ms = 80
    bundle = ProcessBundle(
        work_dir=work_dir,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        demo_plan=BASE_PLAN,
        evidence_root=evidence_root,
    )
    try:
        bundle.start(arm_fault=False)
        ui = _drive_operator_ui(
            op_url=bundle.op_url,
            headed=headed,
            decision="approved",
            pause_once=True,
            timeout_s=240.0,
        )
        snap = ui["snapshot"]
        assert snap is not None
        _assert_common_snapshot(result, snap)

        events = ui.get("events") or []
        pause_event = any(
            "pause" in (e.get("message") or "").lower() or e.get("run_state") == "paused"
            for e in events
        )
        if not (ui.get("pause_observed") or pause_event):
            return result.fail("PAUSED state/event not observed")
        result.ok("pause reached RunControl / UI")

        resume_event = any(
            "resume" in (e.get("message") or "").lower() for e in events
        )
        if not (ui.get("resume_observed") or resume_event):
            return result.fail("resume not observed")
        result.ok("resume continued execution")

        if snap.get("verified_complete") is not True:
            return result.fail("run did not verify after resume")
        result.ok("run completed and verified after resume")
        _evidence_checks(
            Path(snap["evidence_path"]) if snap.get("evidence_path") else None,
            result,
        )
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    finally:
        bundle.stop()
        result.elapsed_s = time.monotonic() - started
    return result


def run_live_model_check() -> ScenarioResult:
    """Optional live NL check. Skip without credentials; never invent results."""
    result = ScenarioResult(
        name="live_model",
        status="SKIPPED",
        mode_note="live natural-language interpretation",
    )
    if not (os.environ.get("LLM_API_KEY") or "").strip() or not (
        os.environ.get("LLM_MODEL") or ""
    ).strip():
        result.error = "live model configuration unavailable"
        result.assertions.append("SKIPPED — live model configuration unavailable")
        return result
    try:
        from taskwitness.interpretation.interpreter import GoalInterpreter

        interpreter = GoalInterpreter.from_env()
        base_goal = (
            "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. "
            "Prepare an interview follow-up, move each matching candidate to Interview Ready, "
            "and ask me before sending any message."
        )
        variation_goal = (
            "Process shortlisted Backend Engineering candidates from candidates.csv. "
            "Prepare follow-ups only. Do not send messages and do not change candidate stages."
        )
        for label, goal in (("base", base_goal), ("variation", variation_goal)):
            ir = interpreter.interpret(goal)
            if ir.status.value != "ready" or ir.task_spec is None:
                return result.fail(f"{label} interpret status={ir.status.value} error={ir.error}")
            result.ok(f"{label} → READY TaskSpec")
        result.status = "PASS"
        result.details["note"] = (
            "Live interpretation produced READY TaskSpecs only; "
            "full live operator e2e not required for Phase 8 automated completion."
        )
    except Exception as exc:  # noqa: BLE001
        result.fail(str(exc))
    return result


def format_report(results: list[ScenarioResult]) -> str:
    lines = [
        "TaskWitness Assessment Acceptance",
        "",
        "Mode: Validated Plan Demo Mode for deterministic scenarios",
        "(does not prove live LLM interpretation quality)",
        "",
    ]
    for r in results:
        lines.append(r.name.upper())
        lines.append(r.status)
        if r.execution_state:
            lines.append(f"Execution: {r.execution_state.upper()}")
        if r.verification_status:
            vlabel = {
                "passed": "VERIFIED",
                "incomplete": "INCOMPLETE",
                "failed": "FAILED",
                "blocked": "BLOCKED",
            }.get(r.verification_status, r.verification_status.upper())
            lines.append(f"Verification: {vlabel}")
        if r.verified_complete is not None:
            lines.append(f"verified_complete: {r.verified_complete}")
        if r.name == "base" and r.details.get("candidate_count"):
            lines.append(f"Candidates: {r.details['candidate_count']}")
        if r.name == "variation":
            lines.append(f"Messages sent: {r.details.get('messages_sent', 0)}")
        if r.name == "recovery":
            if r.details.get("recovered_operation_id"):
                lines.append(f"Recovered operation: {r.details['recovered_operation_id']}")
            if "attempt_count" in r.details:
                lines.append(f"Attempts: {r.details['attempt_count']}")
            if "sent_matches" in r.details:
                lines.append(f"Sent matches: {r.details['sent_matches']}")
        if r.name == "rejection":
            lines.append(f"Unintended sends: {r.details.get('unintended_sends', '?')}")
        if r.evidence_path:
            lines.append(f"Evidence: {r.evidence_path}")
        if r.run_id:
            lines.append(f"Run: {r.run_id}")
        if r.journal_run_id:
            lines.append(f"Journal run: {r.journal_run_id}")
        if r.error and r.status != "PASS":
            lines.append(f"Error: {r.error}")
        if r.elapsed_s:
            lines.append(f"Elapsed: {r.elapsed_s:.1f}s")
        lines.append("")
    failed = [r for r in results if r.status == "FAIL"]
    if failed:
        lines.append(f"FAILED scenarios: {', '.join(r.name for r in failed)}")
    else:
        deterministic = [r for r in results if r.name != "live_model"]
        if deterministic and all(r.status == "PASS" for r in deterministic):
            lines.append("DETERMINISTIC SCENARIOS: ALL PASSED")
    return "\n".join(lines) + "\n"


def run_scenarios(
    names: list[str],
    *,
    headed: bool = False,
    slow_mo_ms: int = 0,
    work_root: Path | None = None,
    include_live: bool = False,
    verbose: bool = False,
) -> list[ScenarioResult]:
    root = work_root or (ROOT / ".taskwitness" / "assessment")
    root.mkdir(parents=True, exist_ok=True)
    results: list[ScenarioResult] = []
    runners = {
        "base": run_base_scenario,
        "variation": run_variation_scenario,
        "recovery": run_recovery_scenario,
        "rejection": run_rejection_scenario,
        "pause": run_pause_scenario,
    }
    for name in names:
        work = root / f"{name}-{int(time.time())}-{os.getpid()}"
        work.mkdir(parents=True, exist_ok=True)
        evidence = work / "evidence"
        runner = runners[name]
        kwargs: dict[str, Any] = {
            "work_dir": work,
            "headed": headed,
            "evidence_root": evidence,
        }
        if name == "pause":
            kwargs["slow_mo_ms"] = max(slow_mo_ms, 100)
        elif slow_mo_ms:
            kwargs["slow_mo_ms"] = slow_mo_ms
        results.append(runner(**kwargs))
    if include_live:
        results.append(run_live_model_check())
    if verbose:
        for r in results:
            print(json.dumps({
                "name": r.name,
                "status": r.status,
                "assertions": r.assertions,
                "details": r.details,
                "error": r.error,
            }, indent=2))
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "TaskWitness Phase-8 assessment acceptance harness. "
            "Deterministic scenarios use Validated Plan Demo Mode."
        )
    )
    p.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="all",
        help="Scenario to run (default: all deterministic).",
    )
    p.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Show Chromium (default: headless for automated mode).",
    )
    p.add_argument("--slow-mo", type=int, default=0)
    p.add_argument(
        "--live-model",
        action="store_true",
        help="Also attempt optional live NL interpretation check if credentials exist.",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--work-root",
        default=None,
        help="Working root for journals/evidence (default: .taskwitness/assessment).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.scenario == "all":
        names = ["base", "variation", "recovery", "rejection", "pause"]
    else:
        names = [args.scenario]
    print("TaskWitness Assessment Acceptance")
    print(f"  scenarios={', '.join(names)}")
    print(f"  headed={args.headed} slow_mo={args.slow_mo}")
    print("  input=Validated Plan Demo Mode (not live NL unless --live-model)")
    print()

    results = run_scenarios(
        names,
        headed=args.headed,
        slow_mo_ms=args.slow_mo,
        work_root=Path(args.work_root) if args.work_root else None,
        include_live=args.live_model,
        verbose=args.verbose,
    )
    print(format_report(results))
    if any(r.status == "FAIL" for r in results):
        return 1
    if args.live_model and any(
        r.name == "live_model" and r.status == "FAIL" for r in results
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
