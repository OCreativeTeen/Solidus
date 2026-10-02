"""把固定提示词送进已经打开的 Gemini，抽出 JSON，写到账本。不判断对不对。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from solidus.skills.chrome_debug import ChromeDebug, ChromeError

PROMPT = "只返回 JSON 数组，三个对象，字段是 name 和 city，城市用多伦多、渥太华、蒙特利尔。"

_SELECTORS = (
    "rich-textarea .ql-editor",
    "div.ql-editor[contenteditable='true']",
    "div[contenteditable='true'][aria-label]",
    "textarea",
    "div[contenteditable='true']",
)

_COUNT_WORDS = {1: "一", 2: "二", 3: "三"}


class GeminiResult(BaseModel):
    status: str
    saw: str
    count: int = 0


def extract_json_array(text: str) -> list[dict[str, Any]] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "[":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, list) or not value:
            continue
        if all(isinstance(item, dict) and "name" in item and "city" in item for item in value):
            return value
    return None


def needs_login(url: str, html: str) -> bool:
    lowered = url.lower()
    if "accounts.google.com" in lowered or "servicelogin" in lowered or "signin" in lowered:
        return True
    if 'id="identifierId"' in html or "identifierId" in html:
        return True
    return False


def count_phrase(count: int) -> str:
    return _COUNT_WORDS.get(count, str(count))


def write_streets(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    temporary.replace(path)


def find_prompt_box(page: Any) -> Any | None:
    for selector in _SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            return locator.first
    return None


def drive_gemini(page: Any, prompt: str, ledger_path: Path, timeout: float = 90) -> GeminiResult:
    page.goto("https://gemini.google.com/", wait_until="domcontentloaded")
    url = getattr(page, "url", "") or ""
    html = page.content()
    if needs_login(url, html):
        return GeminiResult(status="need_login", saw="这个 Chrome 里还没登录 Gemini。")
    box = find_prompt_box(page)
    if box is None:
        return GeminiResult(status="failed", saw="打开了 Gemini，但没找到输入框。")
    box.fill(prompt)
    box.press("Enter")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = page.inner_text("body")
        rows = extract_json_array(body)
        if rows:
            write_streets(ledger_path, rows)
            phrase = count_phrase(len(rows))
            saw = f"已写入 ledger/gemini-streets.json，{phrase}条街道。"
            return GeminiResult(status="saved", saw=saw, count=len(rows))
        time.sleep(0.2 if timeout < 5 else 1)
    return GeminiResult(status="no_json", saw="没拿到数组。")


class GeminiPrompt:
    def __init__(self, chrome: ChromeDebug, ledger_path: Path, prompt: str = PROMPT) -> None:
        self.chrome = chrome
        self.ledger_path = ledger_path
        self.prompt = prompt

    def run(self) -> GeminiResult:
        try:
            connection = self.chrome.connect()
        except ChromeError as exc:
            return GeminiResult(status="no_browser", saw=exc.saw)
        try:
            browser = connection.browser
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            return drive_gemini(page, self.prompt, self.ledger_path)
        except Exception:
            return GeminiResult(status="failed", saw="接上了 Chrome，但 Gemini 这一步没有做完。")
        finally:
            connection.disconnect()
