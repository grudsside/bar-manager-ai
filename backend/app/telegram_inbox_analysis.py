from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from agents import Agent, Runner
from pydantic import BaseModel, Field

from .config import Settings
from .schemas import TaskPriority, VenueCode

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
InboxClassification = Literal[
    "task",
    "task_update",
    "writeoff",
    "preparation",
    "information",
    "unknown",
]


class SuggestedInboxTask(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    priority: TaskPriority = "normal"
    due_at: datetime | None = None
    expected_result: str | None = Field(default=None, max_length=2_000)
    clarification_question: str | None = Field(default=None, max_length=1_000)


class TelegramInboxAnalysis(BaseModel):
    classification: InboxClassification
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=1_000)
    needs_review: bool = False
    suggested_task: SuggestedInboxTask | None = None


INBOX_ANALYSIS_INSTRUCTIONS = """
Ты классифицируешь одно сообщение из рабочего Telegram-чата бара или кофейни.

Допустимые категории:
- task — явное поручение, просьба что-то сделать, проверить, заказать, подготовить или
  проконтролировать в будущем;
- task_update — сообщение сообщает новый статус, результат, проблему или уточнение по
  уже существующей задаче, но само по себе не создаёт новое поручение;
- writeoff — факт списания продукта или товара;
- preparation — факт приготовления заготовки, напитка или производственной партии;
- information — обычная рабочая информация без требуемого действия;
- unknown — недостаточно контекста или сообщение неоднозначно.

Правила:
- не превращай любой факт в задачу;
- suggested_task заполняй только для classification=task;
- title должен быть коротким и содержать одно конкретное действие;
- venue_code используй только если оно задано контекстом чата или явно названо;
- priority critical только при угрозе безопасности, аварии или немедленном простое;
- due_at указывай только при явно названном или однозначном относительном сроке;
- не придумывай исполнителя, срок, количество, заведение или ожидаемый результат;
- confidence ниже 0.75 или unknown должны приводить к needs_review=true;
- summary кратко объясняет смысл сообщения, без технических метаданных.
""".strip()


def build_inbox_analysis_agent(settings: Settings) -> Agent:
    kwargs: dict[str, object] = {
        "name": "Разбор Telegram-входящих",
        "instructions": INBOX_ANALYSIS_INSTRUCTIONS,
        "output_type": TelegramInboxAnalysis,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


async def analyze_telegram_message(
    text: str,
    *,
    settings: Settings,
    chat_title: str,
    chat_purpose: str | None,
    venue_code: VenueCode | None,
    message_date: datetime | None,
) -> TelegramInboxAnalysis:
    if not settings.openai_api_key:
        return fallback_inbox_analysis(text)

    effective_date = message_date or datetime.now(timezone.utc)
    if effective_date.tzinfo is None:
        effective_date = effective_date.replace(tzinfo=timezone.utc)
    local_date = effective_date.astimezone(LOCAL_TIMEZONE)
    prompt = (
        f"Дата и время сообщения по Москве: {local_date.isoformat()}\n"
        f"Название чата: {chat_title}\n"
        f"Назначение чата: {chat_purpose or 'не указано'}\n"
        f"Заведение чата: {venue_code or 'не указано'}\n\n"
        f"Сообщение:\n{text.strip()}"
    )
    result = await Runner.run(build_inbox_analysis_agent(settings), prompt)
    output = result.final_output
    analysis = (
        output
        if isinstance(output, TelegramInboxAnalysis)
        else TelegramInboxAnalysis.model_validate(output)
    )

    task = analysis.suggested_task
    if analysis.classification != "task":
        analysis = analysis.model_copy(update={"suggested_task": None})
    elif task is None:
        analysis = analysis.model_copy(
            update={
                "classification": "unknown",
                "needs_review": True,
                "confidence": min(analysis.confidence, 0.5),
            }
        )
    elif task.due_at is not None and task.due_at.tzinfo is None:
        normalized_task = task.model_copy(
            update={"due_at": task.due_at.replace(tzinfo=LOCAL_TIMEZONE)}
        )
        analysis = analysis.model_copy(update={"suggested_task": normalized_task})

    if analysis.classification == "unknown" or analysis.confidence < 0.75:
        analysis = analysis.model_copy(update={"needs_review": True})
    return analysis


def fallback_inbox_analysis(text: str) -> TelegramInboxAnalysis:
    normalized = " ".join(text.strip().split())
    summary = normalized[:997] + "…" if len(normalized) > 1_000 else normalized
    return TelegramInboxAnalysis(
        classification="unknown",
        confidence=0,
        summary=summary or "Пустое сообщение",
        needs_review=True,
    )
