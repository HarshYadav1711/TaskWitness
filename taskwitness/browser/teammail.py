"""TeamMail browser adapter — domain operations only. No SQLite access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

from taskwitness.browser.session import BrowserSession


@dataclass(frozen=True)
class VisibleDraft:
    message_id: str
    recipient: str
    subject: str
    body: str
    operation_id: str


@dataclass(frozen=True)
class SendResult:
    """Immediate execution observation for a TeamMail send.

    This is not Phase-6 independent verification. Ambiguous outcomes
    (e.g. synthetic acknowledgement interrupt) are reported as ok=False
    with unknown=True — callers must not blindly retry.
    """

    ok: bool
    message_id: str
    operation_id: str
    detail: str = ""
    unknown: bool = False


class TeamMailBrowser:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def page(self) -> Page:
        return self._session.page

    def open_compose(self) -> None:
        self._session.goto("/teammail/compose")
        expect(self.page.get_by_role("heading", name="Compose")).to_be_visible()
        expect(self.page.locator("#compose-form")).to_be_visible()

    def open_compose_nav(self) -> None:
        self.page.get_by_test_id("nav-compose").click()
        expect(self.page.locator("#compose-form")).to_be_visible()

    def fill_compose(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        operation_id: str = "",
    ) -> None:
        self.page.get_by_label("Recipient").fill(recipient)
        self.page.get_by_label("Subject").fill(subject)
        self.page.get_by_label("Body").fill(body)
        op_field = self.page.get_by_label("Operation ID (optional)")
        op_field.fill(operation_id)

    def save_draft(self) -> str:
        self.page.get_by_test_id("save-draft").click()
        expect(self.page.locator('[data-testid="notice"]')).to_contain_text("Draft saved")
        message_id = self._message_id_from_url()
        if not message_id:
            raise RuntimeError("draft save succeeded but message_id missing from URL")
        return message_id

    def open_drafts(self) -> None:
        self._session.goto("/teammail/drafts")
        expect(self.page.get_by_role("heading", name="Drafts")).to_be_visible()
        expect(self.page.locator("#drafts-table")).to_be_visible()

    def find_draft_by_operation_id(self, operation_id: str) -> str | None:
        self.open_drafts()
        row = self.page.locator(
            f'[data-testid="draft-row"][data-operation-id="{operation_id}"]'
        )
        if row.count() == 0:
            return None
        return row.first.get_attribute("data-message-id")

    def open_draft(self, message_id: str) -> None:
        self.open_drafts()
        link = self.page.get_by_test_id(f"draft-link-{message_id}")
        expect(link).to_be_visible()
        link.click()
        expect(self.page.locator("#compose-form")).to_be_visible()
        expect(self.page).to_have_url(
            re.compile(rf".*[?&]message_id={re.escape(message_id)}(?:&|$)")
        )

    def read_draft(self) -> VisibleDraft:
        expect(self.page.locator("#compose-form")).to_be_visible()
        message_id = self._message_id_from_url() or ""
        return VisibleDraft(
            message_id=message_id,
            recipient=self.page.get_by_label("Recipient").input_value(),
            subject=self.page.get_by_label("Subject").input_value(),
            body=self.page.get_by_label("Body").input_value(),
            operation_id=self.page.get_by_label("Operation ID (optional)").input_value(),
        )

    def open_sent(self) -> None:
        self._session.goto("/teammail/sent")
        expect(self.page.get_by_role("heading", name="Sent")).to_be_visible()
        expect(self.page.locator("#sent-table")).to_be_visible()

    def inspect_sent(self, message_id: str) -> dict[str, str]:
        self.open_sent()
        link = self.page.get_by_test_id(f"sent-link-{message_id}")
        expect(link).to_be_visible()
        link.click()
        expect(self.page.locator('[data-testid="sent-detail"]')).to_be_visible()
        return {
            "message_id": self.page.locator('[data-testid="sent-message-id"]').inner_text().strip(),
            "operation_id": self.page.locator('[data-testid="sent-operation-id"]').inner_text().strip(),
            "recipient": self.page.locator('[data-testid="sent-recipient"]').inner_text().strip(),
            "subject": self.page.locator('[data-testid="sent-subject"]').inner_text().strip(),
            "body": self.page.locator('[data-testid="sent-body"]').inner_text().strip(),
        }

    def count_sent_rows(self) -> int:
        self.open_sent()
        return self.page.locator('[data-testid="sent-row"]').count()

    def find_sent_by_operation_id(self, operation_id: str) -> str | None:
        self.open_sent()
        row = self.page.locator(
            f'[data-testid="sent-row"][data-operation-id="{operation_id}"]'
        )
        if row.count() == 0:
            return None
        return row.first.get_attribute("data-message-id")

    def count_sent_by_operation_id(self, operation_id: str) -> int:
        """Count Sent rows with the exact operation_id through the visible UI."""
        self.open_sent()
        return self.page.locator(
            f'[data-testid="sent-row"][data-operation-id="{operation_id}"]'
        ).count()

    def send_draft(
        self,
        message_id: str,
        *,
        expected_operation_id: str | None = None,
        expected_recipient: str | None = None,
    ) -> SendResult:
        """Send an existing draft through the visible TeamMail Send control.

        Preserves the draft's operation_id (does not generate a new one).
        Does not retry on ambiguous acknowledgement failures.
        """
        self.open_draft(message_id)
        draft = self.read_draft()
        if draft.message_id and draft.message_id != message_id:
            raise RuntimeError(
                f"opened draft {draft.message_id!r} but expected {message_id!r}"
            )
        if expected_operation_id is not None and draft.operation_id != expected_operation_id:
            raise RuntimeError(
                "draft operation_id mismatch: "
                f"expected {expected_operation_id!r}, got {draft.operation_id!r}"
            )
        if expected_recipient is not None and draft.recipient != expected_recipient:
            raise RuntimeError(
                "draft recipient mismatch: "
                f"expected {expected_recipient!r}, got {draft.recipient!r}"
            )
        operation_id = draft.operation_id
        self.page.get_by_test_id("send-message").click()
        # Wait for post-submit navigation / UI settlement.
        self.page.wait_for_load_state("domcontentloaded")

        # Normal success lands on sent detail with a notice.
        # Synthetic ambiguous-send fault may land on sent detail with an error
        # banner after the message was already persisted — do not retry.
        error = self.page.locator('[data-testid="mail-error"]')
        if error.count() > 0 and error.first.is_visible():
            err_text = error.first.inner_text().strip()
            # Compose-page validation error vs sent-page ambiguous ack.
            if "/teammail/compose" in self.page.url:
                return SendResult(
                    ok=False,
                    message_id=message_id,
                    operation_id=operation_id,
                    detail=f"send rejected by TeamMail: {err_text}",
                    unknown=False,
                )
            sent_id = self._sent_message_id_from_url() or message_id
            return SendResult(
                ok=False,
                message_id=sent_id,
                operation_id=operation_id,
                detail=f"send acknowledgement ambiguous/failed: {err_text}",
                unknown=True,
            )

        expect(self.page.locator('[data-testid="sent-detail"]')).to_be_visible()
        sent_id = self.page.locator('[data-testid="sent-message-id"]').inner_text().strip()
        sent_op = self.page.locator('[data-testid="sent-operation-id"]').inner_text().strip()
        if sent_op in {"—", "-"}:
            sent_op = ""
        if expected_operation_id is not None and sent_op and sent_op != expected_operation_id:
            return SendResult(
                ok=False,
                message_id=sent_id,
                operation_id=operation_id,
                detail=(
                    "sent operation_id mismatch: "
                    f"expected {expected_operation_id!r}, got {sent_op!r}"
                ),
            )
        notice = self.page.locator('[data-testid="notice"]')
        detail = "message sent"
        if notice.count() > 0 and notice.first.is_visible():
            detail = notice.first.inner_text().strip() or detail
        return SendResult(
            ok=True,
            message_id=sent_id,
            operation_id=operation_id or sent_op,
            detail=detail,
        )

    def _sent_message_id_from_url(self) -> str | None:
        path = urlparse(self.page.url).path.rstrip("/")
        marker = "/teammail/sent/"
        if marker not in path:
            return None
        return path.split(marker, 1)[1] or None

    def _message_id_from_url(self) -> str | None:
        query = parse_qs(urlparse(self.page.url).query)
        values = query.get("message_id")
        if not values:
            return None
        return values[0]
