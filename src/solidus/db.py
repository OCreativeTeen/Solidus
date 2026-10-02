"""一个聊天一条运行记录。SQLite，不上 Redis。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Session(BaseModel):
    chat_id: str
    phase: str = "idle"
    pending: dict[str, Any] | None = None
    bag: dict[str, Any] = Field(default_factory=dict)


class DB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              chat_id TEXT PRIMARY KEY,
              phase TEXT NOT NULL,
              pending_json TEXT,
              bag_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL,
              ts TEXT NOT NULL,
              sender TEXT NOT NULL,
              text TEXT NOT NULL,
              phase TEXT NOT NULL,
              kind TEXT NOT NULL,
              human_required INTEGER NOT NULL DEFAULT 0,
              step TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS acceptances (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              accepted_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def load(self, chat_id: str) -> Session:
        with self._lock:
            row = self._conn.execute(
                "SELECT phase, pending_json, bag_json FROM sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return Session(chat_id=chat_id)
        import json

        pending = json.loads(row["pending_json"]) if row["pending_json"] else None
        bag = json.loads(row["bag_json"]) if row["bag_json"] else {}
        return Session(chat_id=chat_id, phase=row["phase"], pending=pending, bag=bag)

    def save(self, session: Session) -> None:
        import json

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (chat_id, phase, pending_json, bag_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  phase = excluded.phase,
                  pending_json = excluded.pending_json,
                  bag_json = excluded.bag_json,
                  updated_at = excluded.updated_at
                """,
                (
                    session.chat_id,
                    session.phase,
                    json.dumps(session.pending, ensure_ascii=False) if session.pending else None,
                    json.dumps(session.bag, ensure_ascii=False),
                    utc_now(),
                ),
            )
            self._conn.commit()

    def add_message(
        self,
        *,
        chat_id: str,
        sender: str,
        text: str,
        phase: str,
        kind: str,
        human_required: bool = False,
        step: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO messages (chat_id, ts, sender, text, phase, kind, human_required, step)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, utc_now(), sender, text, phase, kind, int(human_required), step),
            )
            self._conn.commit()

    def messages(self, chat_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, ts, sender, text, phase, kind, human_required, step
                FROM messages WHERE chat_id = ? ORDER BY id
                """,
                (chat_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "sender": row["sender"],
                "text": row["text"],
                "phase": row["phase"],
                "kind": row["kind"],
                "human_required": bool(row["human_required"]),
                "step": row["step"],
            }
            for row in rows
        ]

    def accept(self, kind: str, name: str, content_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO acceptances (kind, name, content_hash, accepted_at)
                VALUES (?, ?, ?, ?)
                """,
                (kind, name, content_hash, utc_now()),
            )
            self._conn.commit()

    def latest_acceptance(self, kind: str, name: str) -> dict[str, str] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT kind, name, content_hash, accepted_at
                FROM acceptances WHERE kind = ? AND name = ?
                ORDER BY id DESC LIMIT 1
                """,
                (kind, name),
            ).fetchone()
        if row is None:
            return None
        return {
            "kind": row["kind"],
            "name": row["name"],
            "content_hash": row["content_hash"],
            "accepted_at": row["accepted_at"],
        }

    def list_acceptances(self) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT a.kind, a.name, a.content_hash, a.accepted_at
                FROM acceptances a
                JOIN (
                  SELECT kind, name, MAX(id) AS id
                  FROM acceptances GROUP BY kind, name
                ) latest ON latest.id = a.id
                ORDER BY a.accepted_at, a.name
                """
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "name": row["name"],
                "content_hash": row["content_hash"],
                "accepted_at": row["accepted_at"],
            }
            for row in rows
        ]
