from __future__ import annotations

import json

from solidus.client.runner import ServerBatch, run_script
from solidus.client.script import assert_accepted, check_script, content_hash
from solidus.config import find_root
from solidus.skills.chrome_debug import ChromeDebug, ChromeError
from solidus.skills.gemini_prompt import (
    drive_gemini,
    extract_json_array,
    needs_login,
    write_streets,
)
from tests.test_workflow import FakeGemini, build

FORM = "填表 桥 2 多伦多 true 只要名字"


def test_shipped_script_checks() -> None:
    text = (find_root() / "clients" / "scripts" / "practice.txt").read_text(encoding="utf-8")
    assert check_script(text) == []


def test_auto_answer_is_rejected() -> None:
    errors = check_script("send 填表 桥 2 多伦多 true 只要名字\nwait human\nsend 1\n")
    assert any("不能由脚本回复" in item for item in errors)
    assert any("不能发送 3" in item for item in check_script("send 3\n"))
    assert any("重做行不能是" in item for item in check_script("wait human\nredo 1\n"))


def test_runner_stops_for_the_human(settings, practice, db) -> None:
    gemini = FakeGemini()
    workflow = build(settings, practice, gemini)
    script = settings.scripts_dir / "practice.txt"
    script.write_text(
        (find_root() / "clients" / "scripts" / "practice.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    db.accept("script", "clients/scripts/practice.txt", content_hash(script.read_text(encoding="utf-8")))
    ops = assert_accepted(script, settings.root, db)
    transport = LoopTransport(workflow, ["1", "1", "1"])
    result = run_script(ops, transport, server_timeout=1, human_timeout=1, echo=lambda *_: None)
    assert result.status == "finished"
    assert transport.sent[-1] == FORM
    assert transport.sent.count(FORM) == 1
    assert gemini.calls == 1
    assert "1" in transport.sent
    assert transport.human == ["1", "1", "1"]


def test_runner_redo_then_continue(settings, practice) -> None:
    gemini = FakeGemini()
    workflow = build(settings, practice, gemini)
    from solidus.client.script import parse_script

    text = (find_root() / "clients" / "scripts" / "practice.txt").read_text(encoding="utf-8")
    ops, errors = parse_script(text)
    assert errors == []
    transport = LoopTransport(workflow, ["2", "1", "1", "1"])
    result = run_script(ops, transport, server_timeout=1, human_timeout=1, echo=lambda *_: None)
    assert result.status == "finished"
    first = transport.sent.index(FORM)
    assert transport.sent[first + 1 :] == [FORM]
    assert gemini.calls == 1


def test_unaccepted_script_is_refused(settings, db) -> None:
    script = settings.scripts_dir / "practice.txt"
    script.write_text("send /run practice\n", encoding="utf-8")
    try:
        assert_accepted(script, settings.root, db)
    except Exception as exc:
        assert "还没有人接受" in str(exc)
    else:
        raise AssertionError("未接受的脚本不能交给客户端")


def test_extract_and_write_streets(tmp_path) -> None:
    raw = "好的\n```json\n[{\"name\": \"桥\", \"city\": \"多伦多\"}]\n```"
    rows = extract_json_array(raw)
    assert rows == [{"name": "桥", "city": "多伦多"}]
    assert extract_json_array("没有数组") is None
    path = tmp_path / "gemini-streets.json"
    write_streets(path, rows or [])
    assert json.loads(path.read_text(encoding="utf-8")) == rows


def test_login_detection_and_drive(tmp_path) -> None:
    assert needs_login("https://accounts.google.com/signin", "")
    assert not needs_login("https://gemini.google.com/", "<div>hello</div>")
    page = _FakePage(
        html="<div>gemini</div>",
        response=(
            '[{"name": "一", "city": "渥太华"}, '
            '{"name": "二", "city": "多伦多"}, '
            '{"name": "三", "city": "蒙特利尔"}]'
        ),
    )
    result = drive_gemini(page, "只返回 JSON", tmp_path / "gemini-streets.json", timeout=1)
    assert result.status == "saved"
    assert result.count == 3
    assert page.filled == "只返回 JSON"


def test_chrome_connect_does_not_launch() -> None:
    playwright = _FakePlaywright()
    connection = ChromeDebug("http://127.0.0.1:9222").connect(starter=lambda: playwright)
    assert playwright.chromium.cdp == "http://127.0.0.1:9222"
    assert playwright.chromium.launched is False
    connection.disconnect()
    assert playwright.stopped
    assert playwright.browser.closed is False

    down = _FakePlaywright(fail=True)
    try:
        ChromeDebug("http://127.0.0.1:9222").connect(starter=lambda: down)
    except ChromeError as exc:
        assert "不会新开" in exc.saw
    else:
        raise AssertionError("连不上时应该告诉人")
    assert down.stopped


class LoopTransport:
    def __init__(self, workflow, answers: list[str]) -> None:
        self.workflow = workflow
        self.answers = list(answers)
        self.sent: list[str] = []
        self.human: list[str] = []
        self.server: list[tuple[int, str]] = []
        self.seq = 0

    def send(self, text: str) -> int:
        self.sent.append(text)
        self.seq += 1
        mid = self.seq
        for reply in self.workflow.handle("chat", text):
            self.seq += 1
            self.server.append((self.seq, reply))
        return mid

    def wait_server(self, after_id: int, timeout: float) -> ServerBatch | None:
        del timeout
        messages = [(index, text) for index, text in self.server if index > after_id]
        if not messages:
            return None
        return ServerBatch(tuple(text for _, text in messages), messages[-1][0])

    def wait_human_choice(self, after_id: int, timeout: float) -> tuple[str, int] | None:
        del after_id, timeout
        if not self.answers:
            return None
        choice = self.answers.pop(0)
        self.human.append(choice)
        self.seq += 1
        hid = self.seq
        for reply in self.workflow.handle("chat", choice):
            self.seq += 1
            self.server.append((self.seq, reply))
        return choice, hid


class _FakePage:
    def __init__(self, html: str, response: str) -> None:
        self.html = html
        self.response = response
        self.url = "https://gemini.google.com/"
        self.body = "还没有回复"
        self.filled = None

    def goto(self, url: str, wait_until: str | None = None) -> None:
        del wait_until
        self.url = url

    def content(self) -> str:
        return self.html

    def inner_text(self, selector: str) -> str:
        del selector
        return self.body

    def locator(self, selector: str):
        return _FakeLocator(self, selector == "textarea")


class _FakeLocator:
    def __init__(self, page: _FakePage, ok: bool) -> None:
        self.page = page
        self.ok = ok
        self.first = self

    def count(self) -> int:
        return 1 if self.ok else 0

    def fill(self, text: str) -> None:
        self.page.filled = text

    def press(self, key: str) -> None:
        if key == "Enter":
            self.page.body = self.page.response


class _FakePlaywright:
    def __init__(self, fail: bool = False) -> None:
        self.chromium = _FakeChromium(fail)
        self.browser = self.chromium.browser
        self.stopped = False

    def start(self):
        return self

    def stop(self) -> None:
        self.stopped = True


class _FakeChromium:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.cdp = None
        self.launched = False
        self.browser = _FakeBrowser()

    def connect_over_cdp(self, url: str):
        if self.fail:
            raise RuntimeError("down")
        self.cdp = url
        return self.browser

    def launch(self) -> None:
        self.launched = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True
