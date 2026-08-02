from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents import Agent, Runner
from pydantic import BaseModel, Field

from .config import Settings
from .schemas import TaskPriority, VenueCode

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")


class ExtractedTaskDraft(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    priority: TaskPriority = "normal"
    due_at: datetime | None = None
    clarification_question: str | None = Field(default=None, max_length=1_000)


TASK_DRAFT_INSTRUCTIONS = """
Ты извлекаешь проект рабочей задачи бар-менеджера из русского текста.

Правила:
- сформулируй короткий конкретный title с одним ожидаемым действием;
- description добавляй только для полезных деталей, не дублируй title;
- venue_code указывай только если явно назван «Оксфорд» или «Современник»;
- priority: critical только при явной аварии, угрозе безопасности или немедленном простое;
  high — при явно срочном поручении или близком обязательном сроке; иначе normal;
- due_at указывай только если срок назван или однозначно следует из текста;
- не придумывай исполнителя, срок, заведение, цифры или факты;
- если без одного критически важного уточнения задачу нельзя понять, заполни
  clarification_question. В остальных случаях оставь его null.
""".strip()


def build_task_draft_agent(settings: Settings) -> Agent:
    kwargs: dict[str, object] = {
        "name": "Извлечение проекта задачи",
        "instructions": TASK_DRAFT_INSTRUCTIONS,
        "output_type": ExtractedTaskDraft,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


async def extract_task_draft(text: str, settings: Settings) -> ExtractedTaskDraft:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    now = datetime.now(LOCAL_TIMEZONE)
    prompt = (
        f"Текущее местное время: {now.isoformat()}\n"
        "Сформируй проект задачи из сообщения ниже. Относительные сроки "
        "интерпретируй относительно указанного времени.\n\n"
        f"Сообщение:\n{text.strip()}"
    )
    result = await Runner.run(build_task_draft_agent(settings), prompt)
    output = result.final_output
    if isinstance(output, ExtractedTaskDraft):
        draft = output
    else:
        draft = ExtractedTaskDraft.model_validate(output)

    if draft.due_at is not None and draft.due_at.tzinfo is None:
        draft = draft.model_copy(
            update={"due_at": draft.due_at.replace(tzinfo=LOCAL_TIMEZONE)}
        )
    return draft
