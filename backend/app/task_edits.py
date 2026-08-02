from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents import Agent, Runner
from pydantic import BaseModel, Field, model_validator

from .config import Settings
from .schemas import TaskOut, TaskPriority, TaskUpdate, VenueCode

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")


class ExtractedTaskEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    clear_description: bool = False
    venue_code: VenueCode | None = None
    clear_venue: bool = False
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    clear_due_at: bool = False
    clarification_question: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_clear_flags(self) -> "ExtractedTaskEdit":
        if self.description is not None and self.clear_description:
            raise ValueError("description and clear_description are mutually exclusive")
        if self.venue_code is not None and self.clear_venue:
            raise ValueError("venue_code and clear_venue are mutually exclusive")
        if self.due_at is not None and self.clear_due_at:
            raise ValueError("due_at and clear_due_at are mutually exclusive")
        return self


TASK_EDIT_INSTRUCTIONS = """
Ты извлекаешь только явно запрошенные изменения существующей рабочей задачи
бар-менеджера из русского текста.

Можно изменить:
- title — название задачи;
- description — детали задачи;
- venue_code — только oxford или sovremennik;
- priority — low, normal, high или critical;
- due_at — срок в ISO 8601 с часовым поясом +03:00.

Правила:
- не возвращай поле, которое пользователь не просил менять;
- clear_description=true только при явной просьбе удалить детали;
- clear_venue=true только при явной просьбе убрать привязку к заведению;
- clear_due_at=true только при явной просьбе убрать срок;
- critical используй только при аварии, угрозе безопасности или немедленном простое;
- high используй при явно срочной обязательной задаче; иначе normal;
- относительные даты рассчитывай по московскому времени из текущего времени в запросе;
- если меняется только дата и у задачи уже есть время, сохрани это время;
- если меняется только время и у задачи уже есть дата, сохрани эту дату;
- не придумывай отсутствующие дату, время, заведение или детали;
- если изменение двусмысленно или нельзя определить новый срок, задай один короткий
  clarification_question и не придумывай значение;
- если пользователь не указал ни одного поддерживаемого изменения, задай вопрос,
  что именно нужно изменить.
""".strip()


def build_task_edit_agent(settings: Settings) -> Agent:
    kwargs: dict[str, object] = {
        "name": "Редактирование задачи",
        "instructions": TASK_EDIT_INSTRUCTIONS,
        "output_type": ExtractedTaskEdit,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


async def extract_task_edit(
    text: str,
    task: TaskOut,
    settings: Settings,
) -> ExtractedTaskEdit:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    now = datetime.now(LOCAL_TIMEZONE)
    current_due = (
        _as_aware(task.due_at).astimezone(LOCAL_TIMEZONE).isoformat()
        if task.due_at is not None
        else "не указан"
    )
    prompt = (
        f"Текущее московское время: {now.isoformat()}\n"
        "Текущая задача:\n"
        f"- название: {task.title}\n"
        f"- детали: {task.description or 'не указаны'}\n"
        f"- заведение: {task.venue_code or 'не указано'}\n"
        f"- приоритет: {task.priority}\n"
        f"- срок: {current_due}\n\n"
        "Извлеки только изменения из сообщения:\n"
        f"{text.strip()}"
    )
    result = await Runner.run(build_task_edit_agent(settings), prompt)
    output = result.final_output
    draft = (
        output
        if isinstance(output, ExtractedTaskEdit)
        else ExtractedTaskEdit.model_validate(output)
    )

    if draft.clarification_question:
        return draft
    if not task_update_changes(draft):
        return draft.model_copy(
            update={
                "clarification_question": (
                    "Что именно нужно изменить: название, детали, заведение, "
                    "приоритет или срок?"
                )
            }
        )
    return draft


def task_update_from_edit(draft: ExtractedTaskEdit) -> TaskUpdate:
    return TaskUpdate.model_validate(task_update_changes(draft))


def task_update_changes(draft: ExtractedTaskEdit) -> dict[str, object | None]:
    changes: dict[str, object | None] = {}
    if draft.title is not None:
        changes["title"] = draft.title.strip()
    if draft.clear_description:
        changes["description"] = None
    elif draft.description is not None:
        changes["description"] = draft.description
    if draft.clear_venue:
        changes["venue_code"] = None
    elif draft.venue_code is not None:
        changes["venue_code"] = draft.venue_code
    if draft.priority is not None:
        changes["priority"] = draft.priority
    if draft.clear_due_at:
        changes["due_at"] = None
    elif draft.due_at is not None:
        changes["due_at"] = _as_aware(draft.due_at)
    return changes


def _as_aware(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("datetime is required")
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)
