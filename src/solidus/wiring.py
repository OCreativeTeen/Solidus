"""把各块接上。测试可以自己换掉练习页、Gemini 和模型。"""

from __future__ import annotations

from solidus.agent.companion import Companion, OpenAIModel
from solidus.config import Settings
from solidus.db import DB
from solidus.server.workflow import Workflow
from solidus.skills.chrome_debug import ChromeDebug
from solidus.skills.gemini_prompt import GeminiPrompt
from solidus.skills.loader import SkillLoader
from solidus.skills.practice_browser import PlaywrightPractice
from solidus.skills.practice_page import HttpPractice


def build_workflow(settings: Settings) -> Workflow:
    settings.ledger_dir.mkdir(parents=True, exist_ok=True)
    settings.drafts_dir.mkdir(parents=True, exist_ok=True)
    settings.promoted_dir.mkdir(parents=True, exist_ok=True)
    if settings.practice_driver == "playwright":
        practice = PlaywrightPractice(
            password=settings.practice_password,
            base_url=settings.practice_base_url,
            auto_start=True,
        )
    else:
        practice = HttpPractice(
            password=settings.practice_password,
            base_url=settings.practice_base_url,
            auto_start=True,
        )
    gemini = GeminiPrompt(ChromeDebug(settings.chrome_cdp_url), settings.streets_path)
    model = OpenAIModel(settings.openai_api_key, settings.openai_base_url, settings.openai_model)
    agent = Companion(model, settings.drafts_dir, settings.secrets)
    loader = SkillLoader(settings.promoted_dir, settings.drafts_dir)
    return Workflow(settings, DB(settings.db_path), practice, gemini, agent, loader)
