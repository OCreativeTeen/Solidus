from __future__ import annotations

from solidus.server.cards import Card, is_human_gate, only_choice
from solidus.server.commands import parse_command


def test_card_shape_and_human_mark() -> None:
    card = Card(
        step="表单已提交",
        saw="标题桥，数量 2，城市多伦多，加急 true",
        question="这次提交可以吗",
        options=("可以", "不行，重做", "停下"),
        human_required=True,
    )
    text = card.render()
    assert "步骤：表单已提交" in text
    assert "看到：标题桥，数量 2，城市多伦多，加急 true" in text
    assert "决定：这次提交可以吗（须由人决定）" in text
    assert "\n1 可以\n2 不行，重做\n3 停下" in text
    assert is_human_gate(text)


def test_only_exact_choices() -> None:
    assert only_choice("1") == "1"
    assert only_choice(" 2 ") == "2"
    assert only_choice("1 可以") is None
    assert only_choice("通过") is None


def test_parse_form_note_and_commands() -> None:
    form = parse_command("填表 桥 2 多伦多 true 只要 名字")
    assert form.kind == "form"
    assert form.args["note"] == "只要 名字"
    assert form.args["rush"] == "true"
    assert parse_command("注册 tester 测试员").args == {"name": "tester", "role": "测试员"}
    assert parse_command("登录").kind == "login"
    assert parse_command("打开 Gemini").kind == "gemini"
    assert parse_command("/run practice").args["name"] == "practice"
    assert parse_command("/export@SolidusBot").kind == "export"
    assert parse_command("嗯").kind == "unknown"
    assert parse_command("填表 桥").kind == "form_bad"
