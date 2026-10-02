"""缺 skill 时起草。不能晋升自己。"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from solidus.skills.loader import DraftError, validate_skill_source

logger = logging.getLogger(__name__)

SYSTEM = """你在为 Solidus 起草一个 skill 文件。只输出一个 Python 代码块。

约束：
- 定义 NAME（短字符串）、SUMMARY（一句人话）、match(command: str) -> bool、run(command: str, ctx: dict) -> dict。
- run 返回 {"saw": "一句测试人员能看懂的话", "data": {}}。
- saw 里不要写通过、失败、Pass、Fail，不要打分。
- 不要读取环境变量，不要写密钥，不要导入 telegram。
- 不要写入 skills/promoted，不要调用晋升。晋升是人的事，你只起草。
- 如需写文件，只写 ctx["ledger"] 目录。
- match 为真时才会调用 run。
- 不要在 import 时产生副作用。
"""


class ConfigError(Exception):
    pass


class Model(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class Drafted:
    path: Path
    name: str
    summary: str


class OpenAIModel:
    """OpenAI 兼容接口。DeepSeek 只换 base_url、模型和 key。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise ConfigError("还没有 OPENAI_API_KEY。")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                max_tokens=2500,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                ],
            )
        except ConfigError:
            raise
        except Exception as exc:
            logger.error("model call failed: %s", type(exc).__name__)
            raise DraftError("模型接口没有返回草稿。") from exc
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise DraftError("模型接口没有返回草稿。")
        return content


class Companion:
    def __init__(self, model: Model, drafts_dir: Path, secrets: list[str] | None = None) -> None:
        self.model = model
        self.drafts_dir = drafts_dir
        self.secrets = secrets or []

    def draft(self, command: str) -> Drafted:
        raw = self.model.complete(SYSTEM, f"请为下面这句话起草 skill：\n{command}")
        return self._write(command, raw)

    def rewrite(self, path: Path, command: str) -> Drafted:
        previous = path.read_text(encoding="utf-8") if path.exists() else ""
        raw = self.model.complete(
            SYSTEM,
            "上一份草稿被退回。请重写整份文件。\n"
            f"原命令：{command}\n"
            f"上一份：\n{previous}",
        )
        return self._write(command, raw, preferred=path)

    def _write(self, command: str, raw: str, preferred: Path | None = None) -> Drafted:
        source = _extract_code(raw)
        meta = validate_skill_source(source, self.secrets)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = preferred if preferred is not None else self.drafts_dir / f"{_slug(command)}.py"
        if path.parent.resolve() != self.drafts_dir.resolve():
            raise DraftError("草稿只能写在 skills/drafts。")
        path.write_text(source + "\n", encoding="utf-8")
        return Drafted(path=path, name=meta["name"], summary=meta["summary"])


def _extract_code(raw: str) -> str:
    import re

    match = re.search(r"```(?:python)?\s*(.*?)```", raw, re.S)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _slug(command: str) -> str:
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()[:8]
    return f"draft_{digest}"
