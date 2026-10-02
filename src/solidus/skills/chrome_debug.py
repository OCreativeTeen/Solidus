"""接上人已经打开的调试 Chrome。不新开浏览器，不登录 Google。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ChromeError(Exception):
    def __init__(self, saw: str) -> None:
        super().__init__(saw)
        self.saw = saw


@dataclass
class ChromeConnection:
    playwright: Any
    browser: Any

    def disconnect(self) -> None:
        # 不要 browser.close()。CDP 连上之后 close 会把人正在用的 Chrome 关掉。
        self.playwright.stop()


class ChromeDebug:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        self.cdp_url = cdp_url

    def connect(self, starter: Any | None = None) -> ChromeConnection:
        if starter is None:
            from playwright.sync_api import sync_playwright

            starter = sync_playwright
        playwright = starter().start()
        try:
            browser = playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as exc:
            playwright.stop()
            raise ChromeError("没接上 9222 上已经开着的 Chrome。这里不会新开一个浏览器。") from exc
        return ChromeConnection(playwright=playwright, browser=browser)
