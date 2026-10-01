"""SQLite persistence for the synthetic demo environment.

Separate from any future TaskWitness execution journal.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from demo_env import DEFAULT_DB_PATH, PIPELINE_STAGES

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    operation_id TEXT UNIQUE,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('draft', 'sent')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS demo_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO demo_settings (key, value) VALUES (?, ?)",
        ("fail_after_send_commit_once", "0"),
    )
    conn.commit()


@contextmanager
def db_session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def list_candidates(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    role: str = "",
) -> list[dict[str, Any]]:
    sql = (
        "SELECT candidate_id, name, email, role, status, current_stage "
        "FROM candidates WHERE 1=1"
    )
    params: list[str] = []
    if q.strip():
        term = f"%{q.strip()}%"
        sql += (
            " AND (candidate_id LIKE ? OR name LIKE ? OR role LIKE ?"
            " OR email LIKE ? OR status LIKE ? OR current_stage LIKE ?)"
        )
        params.extend([term, term, term, term, term, term])
    if role.strip():
        sql += " AND role = ?"
        params.append(role.strip())
    sql += " ORDER BY candidate_id"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_candidate(conn: sqlite3.Connection, candidate_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT candidate_id, name, email, role, status, current_stage "
        "FROM candidates WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    return row_to_dict(row)


def distinct_roles(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT role FROM candidates ORDER BY role"
    ).fetchall()
    return [r["role"] for r in rows]


def set_candidate_stage(
    conn: sqlite3.Connection, candidate_id: str, stage: str
) -> dict[str, Any]:
    stage = stage.strip()
    if stage not in PIPELINE_STAGES:
        raise ValueError(f"invalid stage: {stage}")
    cand = get_candidate(conn, candidate_id)
    if cand is None:
        raise KeyError(f"unknown candidate: {candidate_id}")
    conn.execute(
        "UPDATE candidates SET current_stage = ? WHERE candidate_id = ?",
        (stage, candidate_id),
    )
    updated = get_candidate(conn, candidate_id)
    assert updated is not None
    return updated


def _next_message_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT message_id FROM messages ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "MAIL-0001"
    last = row["message_id"]
    try:
        n = int(last.split("-", 1)[1])
    except (IndexError, ValueError):
        n = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    return f"MAIL-{n + 1:04d}"


def create_draft(
    conn: sqlite3.Connection,
    *,
    recipient: str,
    subject: str,
    body: str,
    operation_id: str | None = None,
) -> dict[str, Any]:
    recipient = recipient.strip()
    subject = subject.strip()
    body = body if body is not None else ""
    op = operation_id.strip() if operation_id and operation_id.strip() else None
    _validate_recipient(recipient)
    now = utc_now()
    message_id = _next_message_id(conn)
    try:
        conn.execute(
            "INSERT INTO messages "
            "(message_id, operation_id, recipient, subject, body, state, "
            " created_at, updated_at, sent_at) "
            "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, NULL)",
            (message_id, op, recipient, subject, body, now, now),
        )
    except sqlite3.IntegrityError as exc:
        if op is not None and "operation_id" in str(exc).lower():
            raise ValueError(
                f"operation_id already used: {op}"
            ) from exc
        raise
    msg = get_message_by_id(conn, message_id)
    assert msg is not None
    return msg


def update_draft(
    conn: sqlite3.Connection,
    message_id: str,
    *,
    recipient: str,
    subject: str,
    body: str,
    operation_id: str | None = None,
) -> dict[str, Any]:
    msg = get_message_by_id(conn, message_id)
    if msg is None:
        raise KeyError(f"unknown message: {message_id}")
    if msg["state"] != "draft":
        raise ValueError("only drafts can be updated")
    recipient = recipient.strip()
    subject = subject.strip()
    body = body if body is not None else ""
    op = operation_id.strip() if operation_id and operation_id.strip() else None
    _validate_recipient(recipient)
    now = utc_now()
    try:
        conn.execute(
            "UPDATE messages SET recipient = ?, subject = ?, body = ?, "
            "operation_id = ?, updated_at = ? WHERE message_id = ?",
            (recipient, subject, body, op, now, message_id),
        )
    except sqlite3.IntegrityError as exc:
        if op is not None and "operation_id" in str(exc).lower():
            raise ValueError(f"operation_id already used: {op}") from exc
        raise
    updated = get_message_by_id(conn, message_id)
    assert updated is not None
    return updated


def list_messages(conn: sqlite3.Connection, state: str) -> list[dict[str, Any]]:
    if state not in ("draft", "sent"):
        raise ValueError("state must be draft or sent")
    rows = conn.execute(
        "SELECT message_id, operation_id, recipient, subject, body, state, "
        "created_at, updated_at, sent_at "
        "FROM messages WHERE state = ? ORDER BY updated_at DESC, message_id DESC",
        (state,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_message_by_id(conn: sqlite3.Connection, message_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT message_id, operation_id, recipient, subject, body, state, "
        "created_at, updated_at, sent_at "
        "FROM messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    return row_to_dict(row)


def get_sent_by_operation_id(
    conn: sqlite3.Connection, operation_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT message_id, operation_id, recipient, subject, body, state, "
        "created_at, updated_at, sent_at "
        "FROM messages WHERE operation_id = ? AND state = 'sent'",
        (operation_id,),
    ).fetchone()
    return row_to_dict(row)


def _validate_recipient(recipient: str) -> None:
    if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
        raise ValueError("recipient must be a syntactically valid email")
    local, _, domain = recipient.rpartition("@")
    if not local or not domain or " " in recipient:
        raise ValueError("recipient must be a syntactically valid email")
    if domain.lower() != "example.test":
        raise ValueError("recipient domain must be example.test")


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute(
        "SELECT value FROM demo_settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else "0"


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO demo_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def arm_fail_after_send_commit_once(conn: sqlite3.Connection) -> None:
    """TEST-ONLY: next successful send commit returns an interrupted error once."""
    set_setting(conn, "fail_after_send_commit_once", "1")


def fail_after_send_armed(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "fail_after_send_commit_once") == "1"


def clear_fail_after_send(conn: sqlite3.Connection) -> None:
    set_setting(conn, "fail_after_send_commit_once", "0")


class SendInterruptedError(RuntimeError):
    """Raised after a send is committed when the test-only fault is armed."""

    def __init__(self, message: dict[str, Any]):
        super().__init__(
            "TEST-ONLY: send committed but acknowledgement interrupted"
        )
        self.message = message


def send_message(
    conn: sqlite3.Connection,
    message_id: str,
    *,
    operation_id: Optional[str] = None,
) -> dict[str, Any]:
    """Send a draft. No external delivery. Idempotent on non-null operation_id."""
    msg = get_message_by_id(conn, message_id)
    if msg is None:
        raise KeyError(f"unknown message: {message_id}")

    op = None
    if operation_id is not None and operation_id.strip():
        op = operation_id.strip()
    elif msg["operation_id"]:
        op = msg["operation_id"]

    if op:
        existing = get_sent_by_operation_id(conn, op)
        if existing is not None:
            return existing

    if msg["state"] == "sent":
        return msg
    if msg["state"] != "draft":
        raise ValueError(f"cannot send message in state {msg['state']}")

    _validate_recipient(msg["recipient"])
    now = utc_now()

    if op and op != msg["operation_id"]:
        try:
            conn.execute(
                "UPDATE messages SET operation_id = ?, state = 'sent', "
                "updated_at = ?, sent_at = ? WHERE message_id = ?",
                (op, now, now, message_id),
            )
        except sqlite3.IntegrityError:
            existing = get_sent_by_operation_id(conn, op)
            if existing is not None:
                return existing
            raise
    else:
        if op is None:
            # Generate a stable operation_id for manual UI sends when not supplied.
            op = f"op-{message_id.lower()}"
            try:
                conn.execute(
                    "UPDATE messages SET operation_id = ?, state = 'sent', "
                    "updated_at = ?, sent_at = ? WHERE message_id = ?",
                    (op, now, now, message_id),
                )
            except sqlite3.IntegrityError:
                existing = get_sent_by_operation_id(conn, op)
                if existing is not None:
                    return existing
                raise
        else:
            conn.execute(
                "UPDATE messages SET state = 'sent', updated_at = ?, sent_at = ? "
                "WHERE message_id = ?",
                (now, now, message_id),
            )

    conn.commit()
    sent = get_message_by_id(conn, message_id)
    assert sent is not None
    assert sent["state"] == "sent"
    assert sent["sent_at"] is not None

    if fail_after_send_armed(conn):
        clear_fail_after_send(conn)
        conn.commit()
        raise SendInterruptedError(sent)

    return sent


def clear_messages(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM messages")


def clear_candidates(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM candidates")
