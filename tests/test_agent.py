from __future__ import annotations

from solidus.agent.companion import Companion, ConfigError, OpenAIModel
from solidus.skills.loader import SkillLoader
from tests.test_workflow import FakeGemini, build

CODE = """
NAME = "echo"
SUMMARY = "把命令复述成人话"

def match(command: str) -> bool:
    return command.startswith("回声")

def run(command: str, ctx: dict) -> dict:
    return {"saw": "你说的是一句话", "data": {}}
"""


class FakeModel:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.text


class BrokenModel:
    def complete(self, system: str, user: str) -> str:
        raise ConfigError("还没有 OPENAI_API_KEY。")


def test_draft_is_not_promoted_until_human_says_so(settings) -> None:
    model = FakeModel(f"```python\n{CODE}\n```")
    agent = Companion(model, settings.drafts_dir, settings.secrets)
    workflow = build(settings, _UnusedPractice(), FakeGemini(), agent)

    card = workflow.handle("local", "回声 你好")[0]
    assert "要起草一份 skill 吗" in card
    assert "须由人决定" in card
    assert model.calls == 0

    drafted = workflow.handle("local", "1")[0]
    assert "skills/drafts/" in drafted
    assert list(settings.promoted_dir.glob("*.py")) == []
    assert model.calls == 1
    assert not hasattr(Companion, "promote")

    promoted = workflow.handle("local", "1")[0]
    assert "已晋升" in promoted
    assert list(settings.promoted_dir.glob("*.py"))
    names = [item["name"] for item in workflow.db.list_acceptances()]
    assert any(name.startswith("draft_") and name.endswith(".py") for name in names)

    result = workflow.handle("local", "回声 你好")[0]
    assert "你说的是一句话" in result
    assert "须由人决定" in result
    assert workflow.handle("local", "1") == ["已记下你的选择：可以。"]


def test_hold_does_not_load_draft(settings) -> None:
    agent = Companion(FakeModel(f"```python\n{CODE}\n```"), settings.drafts_dir)
    workflow = build(settings, _UnusedPractice(), FakeGemini(), agent)
    workflow.handle("local", "回声 你好")
    workflow.handle("local", "1")
    held = workflow.handle("local", "3")
    assert held == ["草稿先放着。还在 skills/drafts，没有晋升。"]
    assert SkillLoader(settings.promoted_dir, settings.drafts_dir).load() == []


def test_missing_key_does_not_write_a_draft(settings) -> None:
    agent = Companion(BrokenModel(), settings.drafts_dir)
    workflow = build(settings, _UnusedPractice(), FakeGemini(), agent)
    workflow.handle("local", "做点别的")
    reply = workflow.handle("local", "1")[0]
    assert "OPENAI_API_KEY" in reply
    assert list(settings.drafts_dir.glob("*.py")) == []


def test_openai_model_is_the_default_adapter() -> None:
    model = OpenAIModel("", "https://api.deepseek.com", "deepseek-chat")
    try:
        model.complete("系统", "用户")
    except ConfigError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("空 key 应该停在配置，而不是发请求")


def test_loader_ignores_drafts(settings) -> None:
    boom = settings.drafts_dir / "boom.py"
    boom.write_text("raise SystemExit('不应该导入草稿')\n", encoding="utf-8")
    promoted = settings.promoted_dir / "echo.py"
    promoted.write_text(CODE, encoding="utf-8")
    loaded = SkillLoader(settings.promoted_dir, settings.drafts_dir).load()
    assert [item.name for item in loaded] == ["echo"]


class _UnusedPractice:
    def ensure(self) -> None:
        raise AssertionError("起草不该打开练习页")

    def reset(self) -> None:
        raise AssertionError("起草不该打开练习页")
