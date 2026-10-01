"""Synthetic TalentDesk / TeamMail environment tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_env.db import (
    SendInterruptedError,
    arm_fail_after_send_commit_once,
    connect,
    create_draft,
    get_candidate,
    get_message_by_id,
    get_sent_by_operation_id,
    init_db,
    list_candidates,
    list_messages,
    send_message,
    set_candidate_stage,
)
from demo_env.seed import reset_environment


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "demo.sqlite3"
    monkeypatch.setenv("DEMO_ENV_DB", str(path))
    reset_environment(db_path=path)
    return path


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    # Import after DEMO_ENV_DB is set so routes use the temp DB.
    from demo_env.app import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_seed_imports_six_candidates(db_path: Path):
    conn = connect(db_path)
    try:
        rows = list_candidates(conn)
    finally:
        conn.close()
    assert len(rows) == 6
    assert {r["candidate_id"] for r in rows} == {
        "CAND-001",
        "CAND-002",
        "CAND-003",
        "CAND-004",
        "CAND-005",
        "CAND-006",
    }


def test_candidate_list_accessible(client: TestClient):
    response = client.get("/talentdesk")
    assert response.status_code == 200
    assert "TalentDesk" in response.text
    assert "CAND-001" in response.text
    assert "Asha Verma" in response.text


def test_candidate_retrieved_by_stable_id(client: TestClient, db_path: Path):
    response = client.get("/talentdesk/candidates/CAND-002")
    assert response.status_code == 200
    assert "Jordan Lee" in response.text
    assert "AI Engineering" in response.text
    conn = connect(db_path)
    try:
        cand = get_candidate(conn, "CAND-002")
    finally:
        conn.close()
    assert cand is not None
    assert cand["candidate_id"] == "CAND-002"


def test_candidate_stage_can_be_changed_and_persists(client: TestClient, db_path: Path):
    response = client.post(
        "/talentdesk/candidates/CAND-001/stage",
        data={"stage": "Interview Ready"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]
    conn = connect(db_path)
    try:
        cand = get_candidate(conn, "CAND-001")
    finally:
        conn.close()
    assert cand["current_stage"] == "Interview Ready"
    detail = client.get(response.headers["location"])
    assert "Interview Ready" in detail.text
    assert "Stage updated." in detail.text


def test_invalid_stage_rejected(db_path: Path):
    conn = connect(db_path)
    try:
        with pytest.raises(ValueError, match="invalid stage"):
            set_candidate_stage(conn, "CAND-001", "Promoted To CEO")
    finally:
        conn.close()


def test_reset_restores_original_stage(db_path: Path):
    conn = connect(db_path)
    try:
        original = get_candidate(conn, "CAND-001")["current_stage"]
        set_candidate_stage(conn, "CAND-001", "Interview Ready")
        conn.commit()
        assert get_candidate(conn, "CAND-001")["current_stage"] == "Interview Ready"
    finally:
        conn.close()

    reset_environment(db_path=db_path)
    conn = connect(db_path)
    try:
        assert get_candidate(conn, "CAND-001")["current_stage"] == original
    finally:
        conn.close()


def test_compose_draft_created_and_persists(client: TestClient, db_path: Path):
    response = client.post(
        "/teammail/drafts",
        data={
            "recipient": "asha.verma@example.test",
            "subject": "Interview follow-up",
            "body": "Hello Asha",
            "operation_id": "",
            "intent": "save",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    conn = connect(db_path)
    try:
        drafts = list_messages(conn, "draft")
    finally:
        conn.close()
    assert len(drafts) == 1
    assert drafts[0]["subject"] == "Interview follow-up"
    assert drafts[0]["state"] == "draft"

    listing = client.get("/teammail/drafts")
    assert "MAIL-0001" in listing.text
    assert "Interview follow-up" in listing.text


def test_example_test_recipient_accepted_and_non_example_rejected(db_path: Path):
    conn = connect(db_path)
    try:
        ok = create_draft(
            conn,
            recipient="priya.nair@example.test",
            subject="Hello",
            body="Body",
        )
        assert ok["recipient"] == "priya.nair@example.test"
        with pytest.raises(ValueError, match="example.test"):
            create_draft(
                conn,
                recipient="someone@gmail.com",
                subject="Nope",
                body="x",
            )
    finally:
        conn.close()


def test_successful_send_creates_one_sent_with_timestamp_and_operation_id(
    db_path: Path,
):
    conn = connect(db_path)
    try:
        draft = create_draft(
            conn,
            recipient="jordan.lee@example.test",
            subject="Follow-up",
            body="Please reply",
            operation_id="op-followup-jordan",
        )
        conn.commit()
        sent = send_message(conn, draft["message_id"])
        assert sent["state"] == "sent"
        assert sent["sent_at"]
        assert sent["operation_id"] == "op-followup-jordan"
        assert len(list_messages(conn, "sent")) == 1
        assert list_messages(conn, "draft") == []
    finally:
        conn.close()


def test_duplicate_operation_id_does_not_create_second_sent(db_path: Path):
    conn = connect(db_path)
    try:
        draft = create_draft(
            conn,
            recipient="elena.rossi@example.test",
            subject="One",
            body="Body",
            operation_id="op-unique-1",
        )
        conn.commit()
        first = send_message(conn, draft["message_id"])
        second = send_message(conn, draft["message_id"], operation_id="op-unique-1")
        assert first["message_id"] == second["message_id"]
        assert len(list_messages(conn, "sent")) == 1

        # A second draft attempting the same operation_id must not send again.
        with pytest.raises(ValueError, match="operation_id already used"):
            create_draft(
                conn,
                recipient="elena.rossi@example.test",
                subject="Two",
                body="Body",
                operation_id="op-unique-1",
            )
    finally:
        conn.close()


def test_sent_message_can_be_inspected(client: TestClient, db_path: Path):
    conn = connect(db_path)
    try:
        draft = create_draft(
            conn,
            recipient="marcus.chen@example.test",
            subject="Inspect me",
            body="Visible body",
            operation_id="op-inspect-1",
        )
        conn.commit()
        sent = send_message(conn, draft["message_id"])
    finally:
        conn.close()

    response = client.get(f"/teammail/sent/{sent['message_id']}")
    assert response.status_code == 200
    assert "Inspect me" in response.text
    assert "op-inspect-1" in response.text
    assert "Visible body" in response.text
    assert "marcus.chen@example.test" in response.text


def test_reset_removes_drafts_and_sent(db_path: Path):
    conn = connect(db_path)
    try:
        draft = create_draft(
            conn,
            recipient="sam.okonkwo@example.test",
            subject="Temp",
            body="x",
            operation_id="op-temp",
        )
        conn.commit()
        send_message(conn, draft["message_id"])
        assert list_messages(conn, "sent")
    finally:
        conn.close()

    reset_environment(db_path=db_path)
    conn = connect(db_path)
    try:
        assert list_messages(conn, "draft") == []
        assert list_messages(conn, "sent") == []
        assert len(list_candidates(conn)) == 6
    finally:
        conn.close()


def test_fail_after_send_commit_once_behavior(db_path: Path):
    conn = connect(db_path)
    try:
        draft = create_draft(
            conn,
            recipient="asha.verma@example.test",
            subject="Ambiguous",
            body="Body",
            operation_id="op-ambiguous-1",
        )
        conn.commit()
        arm_fail_after_send_commit_once(conn)
        conn.commit()

        with pytest.raises(SendInterruptedError) as excinfo:
            send_message(conn, draft["message_id"])

        interrupted = excinfo.value.message
        assert interrupted["state"] == "sent"
        assert interrupted["operation_id"] == "op-ambiguous-1"
        assert len(list_messages(conn, "sent")) == 1
        assert get_sent_by_operation_id(conn, "op-ambiguous-1") is not None

        # One-shot: next send succeeds normally.
        draft2 = create_draft(
            conn,
            recipient="jordan.lee@example.test",
            subject="Normal after fault",
            body="Body",
            operation_id="op-after-fault",
        )
        conn.commit()
        sent2 = send_message(conn, draft2["message_id"])
        assert sent2["state"] == "sent"
        assert len(list_messages(conn, "sent")) == 2
    finally:
        conn.close()


def test_role_filter_on_list(client: TestClient):
    response = client.get("/talentdesk", params={"role": "AI Engineering"})
    assert response.status_code == 200
    assert "CAND-001" in response.text
    assert "CAND-002" in response.text
    assert "CAND-003" not in response.text


def test_talentdesk_filter_form_is_get_submit_and_combines_controls(client: TestClient):
    """Filter UI must be a normal GET form with a real submit control."""
    page = client.get("/talentdesk")
    assert page.status_code == 200
    html = page.text
    assert 'id="talentdesk-filters"' in html
    assert 'method="get"' in html
    assert 'action="/talentdesk"' in html
    assert 'id="candidate-search"' in html
    assert 'name="q"' in html
    assert 'id="role-filter"' in html
    assert 'name="role"' in html
    assert 'id="apply-filters"' in html
    assert 'type="submit"' in html
    assert 'for="candidate-search"' in html
    assert 'for="role-filter"' in html

    filtered = client.get(
        "/talentdesk",
        params={"q": "Asha", "role": "AI Engineering", "apply": "Apply"},
    )
    assert filtered.status_code == 200
    assert "CAND-001" in filtered.text
    assert "CAND-002" not in filtered.text
    assert "CAND-003" not in filtered.text
    assert 'data-testid="filter-result"' in filtered.text
    assert "AI Engineering" in filtered.text
    assert "Asha" in filtered.text
