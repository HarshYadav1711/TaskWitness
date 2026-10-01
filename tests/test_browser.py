"""Playwright browser integration tests against the live demo environment."""

from __future__ import annotations

import inspect
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

from demo_env.seed import reset_environment
from taskwitness.browser.session import BrowserSession
from taskwitness.browser.talentdesk import TalentDeskBrowser
from taskwitness.browser.teammail import TeamMailBrowser
from taskwitness.candidate_source import load_candidates
from taskwitness.workflow import (
    RecruitingWorkflow,
    WorkflowConfig,
    make_operation_id,
)

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def demo_server(tmp_path_factory: pytest.TempPathFactory):
    db_path = tmp_path_factory.mktemp("demo") / "browser.sqlite3"
    reset_environment(db_path=db_path)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["DEMO_ENV_DB"] = str(db_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo_env.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 30
    last_err = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
            raise RuntimeError(f"demo server exited early:\n{out}")
        try:
            with urlopen(base_url + "/", timeout=1) as resp:
                if resp.status < 500:
                    break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError(f"demo server failed to start: {last_err}")

    yield {"base_url": base_url, "db_path": db_path, "proc": proc}

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def reset_demo(demo_server):
    reset_environment(db_path=demo_server["db_path"])
    return demo_server


def test_talentdesk_find_read_and_set_stage(reset_demo):
    base_url = reset_demo["base_url"]
    with BrowserSession(base_url=base_url, headed=False) as session:
        desk = TalentDeskBrowser(session)
        desk.filter_candidates(search="CAND-001", role="AI Engineering")
        desk.open_candidate("CAND-001")
        visible = desk.read_candidate()
        assert visible.candidate_id == "CAND-001"
        assert visible.email == "asha.verma@example.test"
        assert visible.role == "AI Engineering"
        assert visible.status == "Shortlisted"
        stage = desk.set_stage("Interview Ready")
        assert stage == "Interview Ready"
        session.goto("/talentdesk/candidates/CAND-001")
        reloaded = desk.read_candidate()
        assert reloaded.current_stage == "Interview Ready"


def test_teammail_draft_create_reopen_and_persist(reset_demo):
    base_url = reset_demo["base_url"]
    op_id = "op-browser-test-1"
    with BrowserSession(base_url=base_url, headed=False) as session:
        mail = TeamMailBrowser(session)
        mail.open_compose()
        mail.fill_compose(
            recipient="asha.verma@example.test",
            subject="Browser draft",
            body="Persisted body",
            operation_id=op_id,
        )
        message_id = mail.save_draft()
        assert message_id.startswith("MAIL-")
        found = mail.find_draft_by_operation_id(op_id)
        assert found == message_id
        mail.open_draft(message_id)
        draft = mail.read_draft()
        assert draft.recipient == "asha.verma@example.test"
        assert draft.subject == "Browser draft"
        assert draft.body == "Persisted body"
        assert draft.operation_id == op_id


def test_taskwitness_browser_modules_do_not_import_demo_db():
    import taskwitness.browser.session as session_mod
    import taskwitness.browser.talentdesk as desk_mod
    import taskwitness.browser.teammail as mail_mod
    import taskwitness.workflow as workflow_mod

    for mod in (session_mod, desk_mod, mail_mod, workflow_mod):
        source = inspect.getsource(mod)
        assert "demo_env.db" not in source
        assert "demo_env.sqlite3" not in source
        assert "sqlite3.connect" not in source


def test_recruiting_workflow_creates_drafts_not_sends(reset_demo):
    base_url = reset_demo["base_url"]
    result = RecruitingWorkflow(
        WorkflowConfig(
            source_file=str(ROOT / "data" / "candidates.csv"),
            role="AI Engineering",
            candidate_status="Shortlisted",
            prepare_followups=True,
            target_stage="Interview Ready",
            base_url=base_url,
            headed=False,
        )
    ).run()
    assert result.error is None
    assert result.selected_candidate_ids == ["CAND-001", "CAND-002"]
    assert result.ok
    assert all(c.precondition_ok for c in result.candidate_results)
    assert all(c.stage_update and c.stage_update.ok for c in result.candidate_results)
    assert all(c.draft and c.draft.ok for c in result.candidate_results)

    with BrowserSession(base_url=base_url, headed=False) as session:
        mail = TeamMailBrowser(session)
        assert mail.count_sent_rows() == 0
        for cand in load_candidates(ROOT / "data" / "candidates.csv"):
            if cand.candidate_id in result.selected_candidate_ids:
                op = make_operation_id(candidate_id=cand.candidate_id, role=cand.role)
                assert mail.find_draft_by_operation_id(op) is not None


def test_false_authority_set_stage_does_not_mutate_talentdesk(reset_demo):
    from demo_env.db import connect, get_candidate, list_messages
    from taskwitness.schemas import ActionType, Authority, TaskSpec
    from taskwitness.workflow import config_from_taskspec

    base_url = reset_demo["base_url"]
    spec = TaskSpec(
        source_file=str(ROOT / "data" / "candidates.csv"),
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.set_stage, ActionType.send_message],
        target_stage="Interview Ready",
        authority=Authority(send_message=False, change_stage=False),
    )
    config, deferred = config_from_taskspec(spec, headed=False, base_url=base_url)
    assert config.target_stage is None
    assert "set_stage:deferred_until_authority_phase" in deferred
    assert "send_message:deferred_until_authority_phase" in deferred

    result = RecruitingWorkflow(config).run()
    assert result.error is None
    assert "set_stage:deferred_until_authority_phase" in result.deferred_actions
    assert "send_message:deferred_until_authority_phase" in result.deferred_actions
    assert all(c.stage_update is None for c in result.candidate_results)

    # Tests may inspect demo SQLite; TaskWitness production code must not.
    conn = connect(reset_demo["db_path"])
    try:
        assert get_candidate(conn, "CAND-001")["current_stage"] == "Phone Screen"
        assert get_candidate(conn, "CAND-002")["current_stage"] == "Recruiter Review"
        assert list_messages(conn, "sent") == []
    finally:
        conn.close()
