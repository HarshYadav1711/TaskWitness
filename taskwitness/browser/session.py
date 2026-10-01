"""Playwright browser session for TaskWitness computer operation."""

from __future__ import annotations

from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


class BrowserSession:
    """Owns Chromium lifecycle. Always closes on exit."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        headed: bool = True,
        slow_mo_ms: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headed = headed
        self.slow_mo_ms = slow_mo_ms
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("browser session is not started")
        return self._page

    def start(self) -> Page:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=not self.headed,
            slow_mo=self.slow_mo_ms if self.headed else 0,
        )
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        return self._page

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def goto(self, path: str) -> None:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        self.page.goto(url, wait_until="domcontentloaded")
