"""卡片只有四样东西：步骤、看到的人话、要决定的事、三个选项。"""

from __future__ import annotations

from pydantic import BaseModel, Field

HUMAN_MARK = "须由人决定"


class Card(BaseModel):
    step: str
    saw: str
    question: str
    options: tuple[str, str, str]
    human_required: bool = False

    def render(self) -> str:
        question = self.question
        if self.human_required and HUMAN_MARK not in question:
            question = f"{question}（{HUMAN_MARK}）"
        first, second, third = self.options
        return (
            f"步骤：{self.step}\n"
            f"看到：{self.saw}\n"
            f"决定：{question}\n"
            f"1 {first}\n"
            f"2 {second}\n"
            f"3 {third}"
        )


def only_choice(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned in {"1", "2", "3"}:
        return cleaned
    return None


def is_human_gate(text: str) -> bool:
    return HUMAN_MARK in text


class ActionResult(BaseModel):
    saw: str
    proceeded: bool = False
    data: dict[str, str] = Field(default_factory=dict)
