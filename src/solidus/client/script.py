"""script 只有 send、wait human、redo。wait human 后面不能代答。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from solidus.db import DB
from solidus.server.cards import only_choice


class ScriptError(Exception):
    pass


@dataclass
class Op:
    kind: str
    text: str = ""
    redo: str | None = None


def content_hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_script(text: str) -> tuple[list[Op], list[str]]:
    errors: list[str] = []
    ops: list[Op] = []
    pending_wait = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "wait human":
            ops.append(Op("wait"))
            pending_wait = True
            continue
        if line.startswith("redo "):
            body = line[5:].strip()
            if not pending_wait or not ops or ops[-1].kind != "wait" or ops[-1].redo:
                errors.append(f"第 {lineno} 行：redo 只能紧跟在 wait human 后面，并且只能有一行。")
                continue
            if only_choice(body):
                errors.append(f"第 {lineno} 行：重做行不能是 1、2 或 3。")
                continue
            ops[-1].redo = body
            pending_wait = True
            continue
        if line.startswith("send "):
            body = line[5:].strip()
            if not body:
                errors.append(f"第 {lineno} 行：send 后面是空的。")
                continue
            if body == "3":
                errors.append(f"第 {lineno} 行：停下只能由人回复，脚本不能发送 3。")
            elif only_choice(body) and pending_wait:
                errors.append(f"第 {lineno} 行：须由人决定的步骤不能由脚本回复 {body}。")
            ops.append(Op("send", body))
            pending_wait = False
            continue
        errors.append(f"第 {lineno} 行：看不懂。只能是 send、wait human、redo。")
    return ops, errors


def check_script(text: str) -> list[str]:
    _ops, errors = parse_script(text)
    return errors


def assert_accepted(path: Path, root: Path, db: DB) -> list[Op]:
    resolved = path.resolve()
    scripts = (root / "clients" / "scripts").resolve()
    if resolved.parent != scripts:
        raise ScriptError("正式脚本要放在 clients/scripts，并且由人接受。模型草稿不能直接交给客户端。")
    text = resolved.read_text(encoding="utf-8")
    errors = check_script(text)
    if errors:
        raise ScriptError("\n".join(errors))
    relative = resolved.relative_to(root).as_posix()
    record = db.latest_acceptance("script", relative)
    digest = content_hash(text)
    if record is None:
        raise ScriptError(f"{relative} 还没有人接受。先运行：solidus script accept {relative}")
    if record["content_hash"] != digest:
        raise ScriptError(f"{relative} 已经改过，需要人重新接受。")
    ops, _errors = parse_script(text)
    return ops
