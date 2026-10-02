"""Browser adapters package — Playwright stays inside this boundary."""

from taskwitness.browser.session import BrowserSession
from taskwitness.browser.talentdesk import TalentDeskBrowser, VisibleCandidate
from taskwitness.browser.teammail import SendResult, TeamMailBrowser, VisibleDraft

__all__ = [
    "BrowserSession",
    "SendResult",
    "TalentDeskBrowser",
    "TeamMailBrowser",
    "VisibleCandidate",
    "VisibleDraft",
]
