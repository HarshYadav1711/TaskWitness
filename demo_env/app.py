"""FastAPI host for TalentDesk and TeamMail synthetic applications.

One local process, two distinct application surfaces.
Not the TaskWitness operator API.
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from demo_env import DEFAULT_DB_PATH, PACKAGE_DIR, PIPELINE_STAGES
from demo_env.db import (
    SendInterruptedError,
    connect,
    create_draft,
    distinct_roles,
    get_candidate,
    get_message_by_id,
    init_db,
    list_candidates,
    list_messages,
    send_message,
    set_candidate_stage,
    update_draft,
)
from demo_env.seed import reset_environment

STATIC_DIR = PACKAGE_DIR / "static"


def get_db_path() -> Path:
    override = os.environ.get("DEMO_ENV_DB")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


def ensure_seeded() -> None:
    path = get_db_path()
    conn = connect(path)
    try:
        init_db(conn)
        count = conn.execute("SELECT COUNT(*) AS c FROM candidates").fetchone()["c"]
        if count == 0:
            conn.close()
            reset_environment(db_path=path)
            return
        conn.commit()
    finally:
        conn.close()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        ensure_seeded()
        yield

    app = FastAPI(
        title="TaskWitness Demo Environment",
        description="Synthetic TalentDesk and TeamMail only. Not the TaskWitness operator.",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_page(
            "Demo Environment",
            "base",
            """
            <main class="shell">
              <h1>Controlled demo environment</h1>
              <p class="lede">Two synthetic business applications for TaskWitness assessment scenarios.
              No external email. All candidate data is fictional.</p>
              <ul class="app-links">
                <li><a id="link-talentdesk" href="/talentdesk">TalentDesk</a> — synthetic ATS</li>
                <li><a id="link-teammail" href="/teammail">TeamMail</a> — synthetic mailbox</li>
              </ul>
              <p class="note">Reset state with: <code>python -m demo_env.seed --reset</code></p>
            </main>
            """,
        ))

    # --- TalentDesk -------------------------------------------------

    @app.get("/talentdesk", response_class=HTMLResponse)
    def talentdesk_list(
        q: str = Query(""),
        role: str = Query(""),
        notice: str = Query(""),
    ) -> HTMLResponse:
        conn = connect(get_db_path())
        try:
            init_db(conn)
            candidates = list_candidates(conn, q=q, role=role)
            roles = distinct_roles(conn)
        finally:
            conn.close()

        role_options = ['<option value="">All roles</option>']
        for r in roles:
            selected = " selected" if r == role else ""
            role_options.append(
                f'<option value="{_esc(r)}"{selected}>{_esc(r)}</option>'
            )

        rows = []
        for c in candidates:
            rows.append(
                f"""
                <tr data-testid="candidate-row" data-candidate-id="{_esc(c['candidate_id'])}">
                  <td><a href="/talentdesk/candidates/{_esc(c['candidate_id'])}"
                         data-testid="candidate-link-{_esc(c['candidate_id'])}">
                         {_esc(c['candidate_id'])}</a></td>
                  <td>{_esc(c['name'])}</td>
                  <td>{_esc(c['email'])}</td>
                  <td><span class="cell-role">{_esc(c['role'])}</span></td>
                  <td><span class="cell-status" data-status="{_esc(c['status'])}">{_esc(c['status'])}</span></td>
                  <td><span class="cell-stage" data-testid="stage-{_esc(c['candidate_id'])}">{_esc(c['current_stage'])}</span></td>
                </tr>
                """
            )
        body_rows = "\n".join(rows) if rows else (
            '<tr><td colspan="6" class="empty">No candidates match.</td></tr>'
        )
        banner = _notice(notice) if notice else ""
        filter_active = bool(q.strip() or role.strip())
        if filter_active:
            parts = []
            if q.strip():
                parts.append(f"search “{_esc(q.strip())}”")
            if role.strip():
                parts.append(f"role “{_esc(role.strip())}”")
            result_line = (
                f'<p class="filter-result" data-testid="filter-result" '
                f'id="filter-result">{len(candidates)} candidate(s) matching '
                f'{", ".join(parts)}.</p>'
            )
        else:
            result_line = (
                f'<p class="filter-result" data-testid="filter-result" '
                f'id="filter-result">{len(candidates)} candidate(s).</p>'
            )

        content = f"""
        <header class="app-header talentdesk-header">
          <div>
            <p class="app-name">TalentDesk</p>
            <h1 id="talentdesk-heading">Candidates</h1>
          </div>
          <nav><a href="/">Demo home</a> · <a href="/teammail">TeamMail</a></nav>
        </header>
        <main class="app-main">
          {banner}
          <form method="get" action="/talentdesk" class="filter-bar" id="talentdesk-filters"
                data-testid="talentdesk-filters">
            <div class="filter-field">
              <label for="candidate-search">Search</label>
              <input id="candidate-search" name="q" type="search"
                     value="{_esc(q)}" placeholder="ID, name, or role"
                     data-testid="candidate-search" />
            </div>
            <div class="filter-field">
              <label for="role-filter">Role</label>
              <select id="role-filter" name="role" data-testid="role-filter">
                {''.join(role_options)}
              </select>
            </div>
            <div class="filter-actions">
              <input type="submit" id="apply-filters" name="apply" value="Apply"
                     form="talentdesk-filters"
                     data-testid="apply-filters" />
            </div>
          </form>
          {result_line}
          <table class="data-table" id="candidate-table" data-testid="candidate-table">
            <thead>
              <tr>
                <th>Candidate</th><th>Name</th><th>Email</th>
                <th>Role</th><th>Status</th><th>Stage</th>
              </tr>
            </thead>
            <tbody>
              {body_rows}
            </tbody>
          </table>
        </main>
        """
        return HTMLResponse(_page("TalentDesk — Candidates", "talentdesk", content))

    @app.get("/talentdesk/candidates/{candidate_id}", response_class=HTMLResponse)
    def talentdesk_detail(
        candidate_id: str,
        notice: str = Query(""),
        error: str = Query(""),
    ) -> HTMLResponse:
        conn = connect(get_db_path())
        try:
            init_db(conn)
            cand = get_candidate(conn, candidate_id)
        finally:
            conn.close()
        if cand is None:
            return HTMLResponse(
                _page(
                    "TalentDesk — Not found",
                    "talentdesk",
                    f"""
                    <header class="app-header talentdesk-header">
                      <p class="app-name">TalentDesk</p>
                      <nav><a href="/talentdesk">Back to candidates</a></nav>
                    </header>
                    <main class="app-main"><p class="error">Unknown candidate {_esc(candidate_id)}.</p></main>
                    """,
                ),
                status_code=404,
            )

        stage_options = []
        current = cand["current_stage"]
        if current not in PIPELINE_STAGES:
            stage_options.append(
                '<option value="" selected disabled>Select a pipeline stage</option>'
            )
        for stage in PIPELINE_STAGES:
            selected = " selected" if stage == current else ""
            stage_options.append(
                f'<option value="{_esc(stage)}"{selected}>{_esc(stage)}</option>'
            )

        banners = ""
        if notice:
            banners += _notice(notice)
        if error:
            banners += f'<p class="error" data-testid="stage-error">{_esc(error)}</p>'

        content = f"""
        <header class="app-header talentdesk-header">
          <div>
            <p class="app-name">TalentDesk</p>
            <h1 id="candidate-detail-heading">Candidate {_esc(cand['candidate_id'])}</h1>
          </div>
          <nav><a href="/talentdesk" data-testid="back-to-list">Candidates</a></nav>
        </header>
        <main class="app-main">
          {banners}
          <section class="detail-panel" data-testid="candidate-detail"
                   data-candidate-id="{_esc(cand['candidate_id'])}">
            <dl class="detail-grid">
              <dt>Candidate ID</dt><dd data-testid="detail-id">{_esc(cand['candidate_id'])}</dd>
              <dt>Name</dt><dd data-testid="detail-name">{_esc(cand['name'])}</dd>
              <dt>Email</dt><dd data-testid="detail-email">{_esc(cand['email'])}</dd>
              <dt>Role</dt><dd data-testid="detail-role">{_esc(cand['role'])}</dd>
              <dt>Status</dt><dd data-testid="detail-status">{_esc(cand['status'])}</dd>
              <dt>Current stage</dt>
              <dd data-testid="detail-stage">{_esc(cand['current_stage'])}</dd>
            </dl>
            <form method="post" action="/talentdesk/candidates/{_esc(cand['candidate_id'])}/stage"
                  id="stage-form" class="stage-form" data-testid="stage-form">
              <label for="stage-select">Change stage</label>
              <select id="stage-select" name="stage" data-testid="stage-select" required>
                {''.join(stage_options)}
              </select>
              <button type="submit" data-testid="save-stage">Save stage</button>
            </form>
          </section>
        </main>
        """
        return HTMLResponse(_page(f"TalentDesk — {cand['candidate_id']}", "talentdesk", content))

    @app.post("/talentdesk/candidates/{candidate_id}/stage")
    def talentdesk_set_stage(candidate_id: str, stage: str = Form(...)):
        conn = connect(get_db_path())
        try:
            init_db(conn)
            try:
                set_candidate_stage(conn, candidate_id, stage)
                conn.commit()
            except ValueError as exc:
                conn.rollback()
                return RedirectResponse(
                    url=(
                        f"/talentdesk/candidates/{quote(candidate_id)}"
                        f"?error={quote(str(exc))}"
                    ),
                    status_code=303,
                )
            except KeyError:
                conn.rollback()
                return HTMLResponse("Unknown candidate", status_code=404)
        finally:
            conn.close()
        return RedirectResponse(
            url=(
                f"/talentdesk/candidates/{quote(candidate_id)}"
                f"?notice={quote('Stage updated.')}"
            ),
            status_code=303,
        )

    # --- TeamMail ---------------------------------------------------

    @app.get("/teammail", response_class=HTMLResponse)
    def teammail_home() -> RedirectResponse:
        return RedirectResponse(url="/teammail/compose", status_code=303)

    @app.get("/teammail/compose", response_class=HTMLResponse)
    def teammail_compose(
        notice: str = Query(""),
        error: str = Query(""),
        message_id: str = Query(""),
    ) -> HTMLResponse:
        conn = connect(get_db_path())
        draft = None
        try:
            init_db(conn)
            if message_id:
                draft = get_message_by_id(conn, message_id)
                if draft is not None and draft["state"] != "draft":
                    draft = None
        finally:
            conn.close()

        recipient = draft["recipient"] if draft else ""
        subject = draft["subject"] if draft else ""
        body = draft["body"] if draft else ""
        operation_id = draft["operation_id"] if draft and draft["operation_id"] else ""
        editing_id = draft["message_id"] if draft else ""
        action = (
            f"/teammail/drafts/{quote(editing_id)}"
            if editing_id
            else "/teammail/drafts"
        )
        title_bit = f"Edit {editing_id}" if editing_id else "Compose"

        banners = ""
        if notice:
            banners += _notice(notice)
        if error:
            banners += f'<p class="error" data-testid="mail-error">{_esc(error)}</p>'

        content = f"""
        {_teammail_header(title_bit)}
        <main class="app-main">
          {banners}
          <form method="post" action="{action}" class="compose-form" id="compose-form"
                data-testid="compose-form">
            <label for="recipient">Recipient
              <input id="recipient" name="recipient" type="email" required
                     value="{_esc(recipient)}" placeholder="name@example.test"
                     data-testid="recipient" />
            </label>
            <label for="subject">Subject
              <input id="subject" name="subject" type="text" required
                     value="{_esc(subject)}" data-testid="subject" />
            </label>
            <label for="body">Body
              <textarea id="body" name="body" rows="10" data-testid="body">{_esc(body)}</textarea>
            </label>
            <label for="operation_id">Operation ID (optional)
              <input id="operation_id" name="operation_id" type="text"
                     value="{_esc(operation_id)}"
                     placeholder="stable logical send key"
                     data-testid="operation-id" />
            </label>
            <div class="form-actions">
              <button type="submit" name="intent" value="save" data-testid="save-draft">
                Save draft
              </button>
              <button type="submit" name="intent" value="send" data-testid="send-message">
                Send
              </button>
            </div>
            <p class="note">Sends stay inside TeamMail. Only @example.test recipients are accepted.
            No SMTP / external delivery.</p>
          </form>
        </main>
        """
        return HTMLResponse(_page(f"TeamMail — {title_bit}", "teammail", content))

    def _save_or_send(
        *,
        message_id: Optional[str],
        recipient: str,
        subject: str,
        body: str,
        operation_id: str,
        intent: str,
    ):
        conn = connect(get_db_path())
        try:
            init_db(conn)
            try:
                if message_id:
                    msg = update_draft(
                        conn,
                        message_id,
                        recipient=recipient,
                        subject=subject,
                        body=body,
                        operation_id=operation_id or None,
                    )
                else:
                    msg = create_draft(
                        conn,
                        recipient=recipient,
                        subject=subject,
                        body=body,
                        operation_id=operation_id or None,
                    )
                conn.commit()
            except ValueError as exc:
                conn.rollback()
                target = "/teammail/compose"
                if message_id:
                    target += f"?message_id={quote(message_id)}"
                sep = "&" if "?" in target else "?"
                return RedirectResponse(
                    url=f"{target}{sep}error={quote(str(exc))}",
                    status_code=303,
                )

            if intent != "send":
                return RedirectResponse(
                    url=(
                        f"/teammail/compose?message_id={quote(msg['message_id'])}"
                        f"&notice={quote('Draft saved.')}"
                    ),
                    status_code=303,
                )

            try:
                sent = send_message(
                    conn,
                    msg["message_id"],
                    operation_id=operation_id or None,
                )
                # send_message commits internally when successful / interrupted
            except SendInterruptedError as exc:
                return RedirectResponse(
                    url=(
                        f"/teammail/sent/{quote(exc.message['message_id'])}"
                        f"?error={quote(str(exc))}"
                    ),
                    status_code=303,
                )
            except ValueError as exc:
                return RedirectResponse(
                    url=(
                        f"/teammail/compose?message_id={quote(msg['message_id'])}"
                        f"&error={quote(str(exc))}"
                    ),
                    status_code=303,
                )
            return RedirectResponse(
                url=(
                    f"/teammail/sent/{quote(sent['message_id'])}"
                    f"?notice={quote('Message sent.')}"
                ),
                status_code=303,
            )
        finally:
            conn.close()

    @app.post("/teammail/drafts")
    def teammail_create_draft(
        recipient: str = Form(...),
        subject: str = Form(...),
        body: str = Form(""),
        operation_id: str = Form(""),
        intent: str = Form("save"),
    ):
        return _save_or_send(
            message_id=None,
            recipient=recipient,
            subject=subject,
            body=body,
            operation_id=operation_id,
            intent=intent,
        )

    @app.post("/teammail/drafts/{message_id}")
    def teammail_update_draft(
        message_id: str,
        recipient: str = Form(...),
        subject: str = Form(...),
        body: str = Form(""),
        operation_id: str = Form(""),
        intent: str = Form("save"),
    ):
        return _save_or_send(
            message_id=message_id,
            recipient=recipient,
            subject=subject,
            body=body,
            operation_id=operation_id,
            intent=intent,
        )

    @app.get("/teammail/drafts", response_class=HTMLResponse)
    def teammail_drafts() -> HTMLResponse:
        conn = connect(get_db_path())
        try:
            init_db(conn)
            drafts = list_messages(conn, "draft")
        finally:
            conn.close()
        rows = []
        for m in drafts:
            rows.append(
                f"""
                <tr data-testid="draft-row" data-message-id="{_esc(m['message_id'])}">
                  <td><a href="/teammail/compose?message_id={_esc(m['message_id'])}"
                         data-testid="draft-link-{_esc(m['message_id'])}">
                         {_esc(m['message_id'])}</a></td>
                  <td>{_esc(m['recipient'])}</td>
                  <td>{_esc(m['subject'])}</td>
                  <td>draft</td>
                  <td>{_esc(m['updated_at'])}</td>
                </tr>
                """
            )
        body_rows = "\n".join(rows) if rows else (
            '<tr><td colspan="5" class="empty">No drafts.</td></tr>'
        )
        content = f"""
        {_teammail_header('Drafts')}
        <main class="app-main">
          <table class="data-table" id="drafts-table" data-testid="drafts-table">
            <thead>
              <tr>
                <th>Message ID</th><th>Recipient</th><th>Subject</th>
                <th>Status</th><th>Updated</th>
              </tr>
            </thead>
            <tbody>{body_rows}</tbody>
          </table>
        </main>
        """
        return HTMLResponse(_page("TeamMail — Drafts", "teammail", content))

    @app.get("/teammail/sent", response_class=HTMLResponse)
    def teammail_sent_list() -> HTMLResponse:
        conn = connect(get_db_path())
        try:
            init_db(conn)
            sent = list_messages(conn, "sent")
        finally:
            conn.close()
        rows = []
        for m in sent:
            op = m["operation_id"] or "—"
            rows.append(
                f"""
                <tr data-testid="sent-row" data-message-id="{_esc(m['message_id'])}"
                    data-operation-id="{_esc(m['operation_id'] or '')}">
                  <td><a href="/teammail/sent/{_esc(m['message_id'])}"
                         data-testid="sent-link-{_esc(m['message_id'])}">
                         {_esc(m['message_id'])}</a></td>
                  <td>{_esc(m['recipient'])}</td>
                  <td>{_esc(m['subject'])}</td>
                  <td>{_esc(m['sent_at'] or '')}</td>
                  <td data-testid="operation-id-cell">{_esc(op)}</td>
                </tr>
                """
            )
        body_rows = "\n".join(rows) if rows else (
            '<tr><td colspan="5" class="empty">No sent messages.</td></tr>'
        )
        content = f"""
        {_teammail_header('Sent')}
        <main class="app-main">
          <table class="data-table" id="sent-table" data-testid="sent-table">
            <thead>
              <tr>
                <th>Message ID</th><th>Recipient</th><th>Subject</th>
                <th>Sent</th><th>Operation ID</th>
              </tr>
            </thead>
            <tbody>{body_rows}</tbody>
          </table>
        </main>
        """
        return HTMLResponse(_page("TeamMail — Sent", "teammail", content))

    @app.get("/teammail/sent/{message_id}", response_class=HTMLResponse)
    def teammail_sent_detail(
        message_id: str,
        notice: str = Query(""),
        error: str = Query(""),
    ) -> HTMLResponse:
        conn = connect(get_db_path())
        try:
            init_db(conn)
            msg = get_message_by_id(conn, message_id)
        finally:
            conn.close()
        if msg is None or msg["state"] != "sent":
            return HTMLResponse(
                _page(
                    "TeamMail — Not found",
                    "teammail",
                    f"""
                    {_teammail_header('Sent')}
                    <main class="app-main"><p class="error">Sent message not found.</p></main>
                    """,
                ),
                status_code=404,
            )
        banners = ""
        if notice:
            banners += _notice(notice)
        if error:
            banners += f'<p class="error" data-testid="mail-error">{_esc(error)}</p>'
        content = f"""
        {_teammail_header('Sent')}
        <main class="app-main">
          {banners}
          <section class="detail-panel" data-testid="sent-detail"
                   data-message-id="{_esc(msg['message_id'])}">
            <dl class="detail-grid">
              <dt>Message ID</dt><dd data-testid="sent-message-id">{_esc(msg['message_id'])}</dd>
              <dt>Operation ID</dt>
              <dd data-testid="sent-operation-id">{_esc(msg['operation_id'] or '—')}</dd>
              <dt>Recipient</dt><dd data-testid="sent-recipient">{_esc(msg['recipient'])}</dd>
              <dt>Subject</dt><dd data-testid="sent-subject">{_esc(msg['subject'])}</dd>
              <dt>Sent at</dt><dd data-testid="sent-at">{_esc(msg['sent_at'] or '')}</dd>
              <dt>Body</dt><dd><pre class="body-pre" data-testid="sent-body">{_esc(msg['body'])}</pre></dd>
            </dl>
            <p><a href="/teammail/sent">Back to Sent</a></p>
          </section>
        </main>
        """
        return HTMLResponse(_page(f"TeamMail — {message_id}", "teammail", content))

    return app


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _notice(text: str) -> str:
    return f'<p class="notice" data-testid="notice">{_esc(text)}</p>'


def _teammail_header(section: str) -> str:
    return f"""
    <header class="app-header teammail-header">
      <div>
        <p class="app-name">TeamMail</p>
        <h1 id="teammail-heading">{_esc(section)}</h1>
      </div>
      <nav class="mail-nav" data-testid="mail-nav">
        <a href="/teammail/compose" data-testid="nav-compose">Compose</a>
        <a href="/teammail/drafts" data-testid="nav-drafts">Drafts</a>
        <a href="/teammail/sent" data-testid="nav-sent">Sent</a>
        <a href="/">Demo home</a>
      </nav>
    </header>
    """


def _page(title: str, skin: str, body: str) -> str:
    css_links = [
        '<link rel="stylesheet" href="/static/base.css" />',
    ]
    if skin == "talentdesk":
        css_links.append('<link rel="stylesheet" href="/static/talentdesk.css" />')
    elif skin == "teammail":
        css_links.append('<link rel="stylesheet" href="/static/teammail.css" />')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(title)}</title>
  {''.join(css_links)}
</head>
<body class="skin-{_esc(skin)}">
{body}
</body>
</html>
"""


app = create_app()
