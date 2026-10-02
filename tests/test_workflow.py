from __future__ import annotations

import inspect

from solidus.agent.companion import Companion
from solidus.config import find_root
from solidus.db import DB
from solidus.server.workflow import Workflow
from solidus.skills.gemini_prompt import GeminiResult
from solidus.skills.loader import SkillLoader
from tests.conftest import PASSWORD


class FakeGemini:
    def __init__(self, result: GeminiResult | None = None) -> None:
        self.calls = 0
        self.result = result or GeminiResult(
            status="saved",
            saw="已写入 ledger/gemini-streets.json，三条街道。",
            count=3,
        )

    def run(self) -> GeminiResult:
        self.calls += 1
        return self.result


def build(settings, practice, gemini=None, agent=None):
    loader = SkillLoader(settings.promoted_dir, settings.drafts_dir)
    if agent is None:
        agent = Companion(_Silent(), settings.drafts_dir, settings.secrets)
    return Workflow(
        settings,
        DB(settings.db_path),
        practice,
        gemini or FakeGemini(),
        agent,
        loader,
    )


class _Silent:
    def complete(self, system: str, user: str) -> str:
        raise AssertionError("这一步不该调用模型")


def test_handle_ignores_sender() -> None:
    params = inspect.signature(Workflow.handle).parameters
    assert list(params) == ["self", "chat_id", "text"]


def test_practice_prototype(settings, practice) -> None:
    gemini = FakeGemini()
    workflow = build(settings, practice, gemini)
    chat = "local"

    first = workflow.handle(chat, "/run practice")
    assert "从注册开始" in first[0]
    assert "须由人决定" not in first[0]

    assert workflow.handle(chat, "1") == ["已打开注册页。"]
    registered = workflow.handle(chat, "注册 tester 测试员")[0]
    assert "已提交注册。姓名 tester，角色测试员。" in registered
    assert "须由人决定" not in registered

    assert workflow.handle(chat, "1") == ["已打开登录页。"]
    assert "已登录。" in workflow.handle(chat, "登录")[0]
    assert workflow.handle(chat, "1") == ["已打开表单。"]

    form = workflow.handle(chat, "填表 桥 2 多伦多 true 只要名字")[0]
    assert "标题桥，数量 2，城市多伦多，加急 true" in form
    assert "须由人决定" in form
    assert gemini.calls == 0

    again = workflow.handle(chat, "可以")[0]
    assert again.startswith("请只回复 1、2 或 3。")
    assert gemini.calls == 0

    permission = workflow.handle(chat, "1")[0]
    assert "调试 Chrome" in permission
    assert "须由人决定" in permission
    assert gemini.calls == 0

    saved = workflow.handle(chat, "1")[0]
    assert "三条街道" in saved
    assert gemini.calls == 1

    done = workflow.handle(chat, "1")
    assert done == ["已记下你的选择：这份可以用。"]
    assert "通过" not in done[0]
    assert "失败" not in done[0]

    from solidus.ledger.export import export_chat

    path = export_chat(workflow.db, chat, settings.ledger_dir)
    text = path.read_text(encoding="utf-8")
    assert PASSWORD not in text
    assert "decision" in text
    assert "gemini-streets" not in PASSWORD


def test_stop_does_not_call_gemini(settings, practice) -> None:
    gemini = FakeGemini()
    workflow = build(settings, practice, gemini)
    _reach_form(workflow)
    assert "须由人决定" in workflow.handle("local", "填表 桥 2 多伦多 true 只要名字")[0]
    stopped = workflow.handle("local", "3")
    assert stopped == ["已停下。聊天交给你。"]
    assert gemini.calls == 0


def test_missing_browser_is_a_human_card(settings, practice) -> None:
    gemini = FakeGemini(
        GeminiResult(
            status="no_browser",
            saw="没接上 9222 上已经开着的 Chrome。这里不会新开一个浏览器。",
        )
    )
    workflow = build(settings, practice, gemini)
    workflow.handle("local", "打开 gemini")
    assert gemini.calls == 0
    card = workflow.handle("local", "1")[0]
    assert "不会新开一个浏览器" in card
    assert "须由人决定" in card
    assert gemini.calls == 1


def test_chrome_only_connects() -> None:
    source = (find_root() / "src" / "solidus" / "skills" / "chrome_debug.py").read_text(encoding="utf-8")
    gemini = (find_root() / "src" / "solidus" / "skills" / "gemini_prompt.py").read_text(encoding="utf-8")
    assert "connect_over_cdp" in source
    assert ".launch(" not in source
    assert ".launch(" not in gemini


def test_password_is_not_stored(settings, practice) -> None:
    workflow = build(settings, practice)
    reply = workflow.handle("local", f"密码是 {PASSWORD}")
    assert PASSWORD not in reply[0]
    exported = workflow.db.messages("local")
    assert all(PASSWORD not in row["text"] for row in exported)


def _reach_form(workflow: Workflow) -> None:
    workflow.handle("local", "/run practice")
    workflow.handle("local", "1")
    workflow.handle("local", "注册 tester 测试员")
    workflow.handle("local", "1")
    workflow.handle("local", "登录")
    workflow.handle("local", "1")
