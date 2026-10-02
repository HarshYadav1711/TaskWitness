"""Phase 7 operator UI smoke test (Playwright against local operator; no live LLM)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from taskwitness.browser.talentdesk import VisibleCandidate
from taskwitness.operator.app import create_app
from taskwitness.operator.runtime import OperatorRuntime
from taskwitness.schemas import ActionType, Authority, TaskSpec
from taskwitness.testing.fakes import FakeTalentDesk, FakeTeamMail

ROOT = Path(__file__).resolve().parents[1]
CSV = str(ROOT / "data" / "candidates.csv")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _spec() -> TaskSpec:
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


def _desk() -> FakeTalentDesk:
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


@pytest.fixture()
def operator_server(tmp_path: Path):
    port = _free_port()
    runtime = OperatorRuntime(
        base_url="http://127.0.0.1:9",
        headed=False,
        journal_path=tmp_path / "j.sqlite3",
        evidence_root=tmp_path / "evidence",
        source_root=ROOT,
        demo_task_spec=_spec(),
        workflow_hooks={"desk": _desk(), "mail": FakeTeamMail()},
    )
    app = create_app(runtime)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("operator server failed to start")
    yield {"base_url": f"http://127.0.0.1:{port}", "runtime": runtime, "server": server}
    server.should_exit = True
    try:
        thread.join(timeout=8)
    except Exception:  # noqa: BLE001
        pass


def test_operator_ui_smoke_approval_and_verification(operator_server):
    base = operator_server["base_url"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base + "/operator", wait_until="domcontentloaded")
        assert page.get_by_role("heading", name="Business goal").is_visible()
        assert page.get_by_role("button", name="Run").is_visible()
        assert page.get_by_text("Validated Plan Demo Mode", exact=True).is_visible()

        page.get_by_role("button", name="Start validated plan").click()

        # Reject each approval as it appears until verification settles.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            dialog = page.locator("#approval-dialog:not([hidden])")
            if dialog.count() and dialog.is_visible():
                reject = page.locator("#btn-reject")
                reject.wait_for(state="visible", timeout=5000)
                reject.click(timeout=5000)
                page.wait_for_timeout(250)
                continue
            ver = page.locator("#verify-summary").inner_text().strip()
            if ver == "INCOMPLETE":
                break
            page.wait_for_timeout(100)
        else:
            browser.close()
            raise AssertionError("verification did not become INCOMPLETE")

        assert page.locator("#verify-message").inner_text().strip() != "Goal verified"
        assert page.locator("#evidence-box").is_visible()
        assert "evidence" in page.locator("#evidence-path").inner_text()
        browser.close()
