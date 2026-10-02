"""把一次聊天导出成写 script 的原型。密码不进文件。"""

from __future__ import annotations

import json
from pathlib import Path

from solidus.db import DB


def export_chat(db: DB, chat_id: str, ledger_dir: Path) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    number = 1
    while (ledger_dir / f"practice-{number:03d}.jsonl").exists():
        number += 1
    path = ledger_dir / f"practice-{number:03d}.jsonl"
    rows = db.messages(chat_id)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
