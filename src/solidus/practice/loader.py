"""加载练习页应用。页面本身不依赖 Telegram。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from solidus.config import find_root


def practice_app_path(root: Path | None = None) -> Path:
    base = root or find_root()
    return base / "fixtures" / "practice" / "app.py"


def load_practice_app(root: Path | None = None):
    path = practice_app_path(root)
    spec = importlib.util.spec_from_file_location("solidus_practice_app", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"找不到练习页：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.app
