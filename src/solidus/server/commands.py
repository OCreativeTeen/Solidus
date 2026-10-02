"""服务器认的文本就这些，避免聊天变成填空。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from solidus.server.cards import only_choice


@dataclass
class Command:
    kind: str
    raw: str
    args: dict[str, Any] = field(default_factory=dict)


def _strip_bot_suffix(text: str) -> str:
    if not text.startswith("/"):
        return text
    head, sep, tail = text.partition(" ")
    head = head.split("@", 1)[0]
    if sep:
        return f"{head} {tail}".strip()
    return head


def parse_command(text: str) -> Command:
    raw = _strip_bot_suffix(text.strip())
    choice = only_choice(raw)
    if choice:
        return Command("choice", raw, {"value": choice})
    if raw == "/help":
        return Command("help", raw)
    if raw == "/skills":
        return Command("skills", raw)
    if raw == "/export":
        return Command("export", raw)
    if raw == "/run" or raw.startswith("/run "):
        name = raw[4:].strip()
        return Command("run", raw, {"name": name})
    if raw.lower() == "打开 gemini":
        return Command("gemini", raw)
    if raw == "登录":
        return Command("login", raw)
    if raw.startswith("登录"):
        return Command("login_bad", raw)
    if raw == "注册" or raw.startswith("注册 "):
        body = raw[2:].strip()
        parts = body.split()
        if len(parts) == 2:
            return Command("register", raw, {"name": parts[0], "role": parts[1]})
        return Command("register_bad", raw)
    if raw == "填表" or raw.startswith("填表 "):
        body = raw[2:].strip()
        parts = body.split()
        if len(parts) >= 4 and parts[1].isdigit() and parts[3].lower() in {"true", "false"}:
            title, qty, city, rush, *note = parts
            return Command(
                "form",
                raw,
                {
                    "title": title,
                    "quantity": qty,
                    "city": city,
                    "rush": rush.lower(),
                    "note": " ".join(note),
                },
            )
        return Command("form_bad", raw)
    return Command("unknown", raw)
