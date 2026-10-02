from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from solidus.config import Settings
from solidus.db import DB
from solidus.practice.loader import load_practice_app
from solidus.skills.practice_page import HttpPractice

PASSWORD = "test-secret-value"


@pytest.fixture
def practice_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRACTICE_PASSWORD", PASSWORD)
    return load_practice_app()


@pytest.fixture
def practice(practice_app) -> HttpPractice:
    client = TestClient(practice_app, follow_redirects=True)
    driver = HttpPractice(password=PASSWORD, client=client, auto_start=False)
    driver.reset()
    return driver


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "skills" / "drafts").mkdir(parents=True)
    (tmp_path / "skills" / "promoted").mkdir(parents=True)
    (tmp_path / "clients" / "scripts").mkdir(parents=True)
    (tmp_path / "ledger").mkdir(parents=True)
    return Settings(
        practice_password=PASSWORD,
        solidus_root=str(tmp_path),
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )


@pytest.fixture
def db(settings: Settings) -> DB:
    return DB(settings.db_path)
