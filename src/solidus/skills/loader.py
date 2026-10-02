"""只加载已晋升的 skill。drafts 里的文件不导入。"""

from __future__ import annotations

import ast
import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from solidus.redact import redact


class LoaderError(Exception):
    pass


class DraftError(Exception):
    pass


@dataclass
class LoadedSkill:
    name: str
    summary: str
    path: Path
    module: Any

    def match(self, command: str) -> bool:
        return bool(self.module.match(command))

    def run(self, command: str, ctx: dict[str, Any]) -> dict[str, Any]:
        result = self.module.run(command, ctx)
        if not isinstance(result, dict):
            raise LoaderError("skill 没有返回字典。")
        return result


def validate_skill_source(source: str, secrets: list[str] | None = None) -> dict[str, str]:
    cleaned, leaked = redact(source, secrets or [])
    if leaked or cleaned != source:
        raise DraftError("草稿里出现了不该出现的密钥，已丢弃。")
    if "skills/promoted" in source or "skills\\promoted" in source:
        raise DraftError("草稿不能自己晋升。")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise DraftError("草稿不是一份能解析的 Python。") from exc
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "match" not in functions or "run" not in functions:
        raise DraftError("草稿需要 match 和 run 两个函数。")
    name = _assigned_str(tree, "NAME")
    summary = _assigned_str(tree, "SUMMARY") or ""
    if not name:
        raise DraftError("草稿需要 NAME。")
    return {"name": name, "summary": summary}


def _assigned_str(tree: ast.AST, target: str) -> str:
    for node in tree.body:  # type: ignore[attr-defined]
        if not isinstance(node, ast.Assign):
            continue
        for item in node.targets:
            if isinstance(item, ast.Name) and item.id == target and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    return node.value.value
    return ""


class SkillLoader:
    def __init__(self, promoted_dir: Path, drafts_dir: Path) -> None:
        self.promoted_dir = promoted_dir
        self.drafts_dir = drafts_dir

    def load(self) -> list[LoadedSkill]:
        self.promoted_dir.mkdir(parents=True, exist_ok=True)
        skills: list[LoadedSkill] = []
        for path in sorted(self.promoted_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            loaded = self._import(path)
            if loaded is not None:
                skills.append(loaded)
        return skills

    def match(self, command: str) -> LoadedSkill | None:
        for skill in self.load():
            try:
                if skill.match(command):
                    return skill
            except Exception:
                continue
        return None

    def promote(self, draft: Path, secrets: list[str] | None = None) -> Path:
        draft = draft.resolve()
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.promoted_dir.mkdir(parents=True, exist_ok=True)
        if draft.parent != self.drafts_dir.resolve():
            raise LoaderError("只能晋升 drafts 里的文件。")
        source = draft.read_text(encoding="utf-8")
        validate_skill_source(source, secrets)
        dest = self.promoted_dir / draft.name
        shutil.copyfile(draft, dest)
        return dest

    def _import(self, path: Path) -> LoadedSkill | None:
        module_name = f"solidus_promoted_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            return None
        if not hasattr(module, "match") or not hasattr(module, "run"):
            return None
        name = str(getattr(module, "NAME", path.stem))
        summary = str(getattr(module, "SUMMARY", ""))
        return LoadedSkill(name=name, summary=summary, path=path, module=module)
