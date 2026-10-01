"""TalentDesk browser adapter — domain operations only."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Page, expect

from taskwitness.browser.session import BrowserSession


@dataclass(frozen=True)
class VisibleCandidate:
    candidate_id: str
    name: str
    email: str
    role: str
    status: str
    current_stage: str


class TalentDeskBrowser:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def page(self) -> Page:
        return self._session.page

    def open_list(self) -> None:
        self._session.goto("/talentdesk")
        expect(self.page.get_by_role("heading", name="Candidates")).to_be_visible()

    def filter_candidates(self, *, search: str = "", role: str = "") -> None:
        """Use visible TalentDesk search/role/Apply controls — never craft filtered URLs."""
        self.open_list()
        search_box = self.page.get_by_label("Search")
        search_box.fill(search)
        role_select = self.page.get_by_label("Role")
        if role:
            role_select.select_option(label=role)
        else:
            role_select.select_option(value="")
        self.page.get_by_role("button", name="Apply").click()
        expect(self.page.locator("#filter-result")).to_be_visible()

    def open_candidate(self, candidate_id: str) -> None:
        link = self.page.get_by_role("link", name=candidate_id, exact=True)
        expect(link).to_be_visible()
        link.click()
        expect(self.page.locator('[data-testid="candidate-detail"]')).to_be_visible()
        expect(self.page.locator('[data-testid="detail-id"]')).to_have_text(candidate_id)

    def read_candidate(self) -> VisibleCandidate:
        detail = self.page.locator('[data-testid="candidate-detail"]')
        expect(detail).to_be_visible()
        return VisibleCandidate(
            candidate_id=self.page.locator('[data-testid="detail-id"]').inner_text().strip(),
            name=self.page.locator('[data-testid="detail-name"]').inner_text().strip(),
            email=self.page.locator('[data-testid="detail-email"]').inner_text().strip(),
            role=self.page.locator('[data-testid="detail-role"]').inner_text().strip(),
            status=self.page.locator('[data-testid="detail-status"]').inner_text().strip(),
            current_stage=self.page.locator('[data-testid="detail-stage"]').inner_text().strip(),
        )

    def set_stage(self, stage: str) -> str:
        select = self.page.locator("#stage-select")
        expect(select).to_be_visible()
        select.select_option(value=stage)
        self.page.get_by_role("button", name="Save stage").click()
        expect(self.page.locator('[data-testid="notice"]')).to_contain_text("Stage updated")
        expect(self.page.locator('[data-testid="detail-stage"]')).to_have_text(stage)
        return self.page.locator('[data-testid="detail-stage"]').inner_text().strip()
