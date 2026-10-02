"""路径和本机配置。密钥只从环境变量来，不进聊天。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_PASSWORD_LEN = 8


def find_root() -> Path:
    env = os.environ.get("SOLIDUS_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "fixtures").is_dir():
            return candidate
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_chat_id: str = ""
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    practice_password: str = ""
    practice_base_url: str = "http://127.0.0.1:8765"
    practice_driver: str = "http"
    chrome_cdp_url: str = "http://127.0.0.1:9222"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    solidus_root: str = ""

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def _empty_int(cls, value: object) -> object:
        if value is None or value == "":
            return 0
        return value

    @property
    def root(self) -> Path:
        if self.solidus_root:
            return Path(self.solidus_root).resolve()
        return find_root()

    @property
    def ledger_dir(self) -> Path:
        return self.root / "ledger"

    @property
    def db_path(self) -> Path:
        return self.ledger_dir / "solidus.sqlite"

    @property
    def drafts_dir(self) -> Path:
        return self.root / "skills" / "drafts"

    @property
    def promoted_dir(self) -> Path:
        return self.root / "skills" / "promoted"

    @property
    def scripts_dir(self) -> Path:
        return self.root / "clients" / "scripts"

    @property
    def session_base(self) -> str:
        return str(self.ledger_dir / "solidus")

    @property
    def streets_path(self) -> Path:
        return self.ledger_dir / "gemini-streets.json"

    @property
    def secrets(self) -> list[str]:
        values = [
            self.practice_password,
            self.telegram_bot_token,
            self.openai_api_key,
            self.telegram_api_hash,
        ]
        unique = sorted({item for item in values if len(item) >= MIN_PASSWORD_LEN}, key=len, reverse=True)
        return unique

    @property
    def password_ready(self) -> bool:
        return len(self.practice_password) >= MIN_PASSWORD_LEN


def load_settings() -> Settings:
    root = find_root()
    load_dotenv(root / ".env", override=False)
    settings = Settings()
    if not settings.solidus_root:
        settings.solidus_root = str(root)
    return settings
