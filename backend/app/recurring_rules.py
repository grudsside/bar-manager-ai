from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal

from agents import Agent, Runner
from pydantic import BaseModel, Field

from .config import Settings
from .schemas import TaskPriority, VenueCode

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
RecurrenceFrequency = Literal["daily", "weekly"]
WeekdayCode = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

WEEKDAY_INDEX = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}
WEEKDAY_LABELS = {
    "MO": "понедельник",
    "TU": "вторник",
    "WE": "среда",
    "TH": "четверг",
    "FR": "пятница",
    "SA": "суббота",
    "SU": "воскресенье",
}


class ExtractedRecurringRule(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    priority: TaskPriority = "normal"
    frequency: RecurrenceFrequency
    weekdays: list[WeekdayCode] = Field(default_factory=list)
    due_time: time | None = None
    clarification_question: str | None = Field(default=None, max_length=1_000)


RECURRING_RULE_INSTRUCTIONS = """
Ты извлекаешь правило повторяющейся рабочей задачи бар-менеджера из русского текста.

Поддерживаются только два режима:
- daily — каждый день;
- weekly — один или несколько конкретных дней недели.

Правила:
- сформулируй короткий конкретный title с одним ожидаемым действием;
- description добавляй только для полезных деталей, не дублируй title;
- venue_code указывай только если явно назван «Оксфорд» или «Современник»;
- priority: critical только при аварии, угрозе безопасности или немедленном простое;
  high — при явно срочном обязательном процессе; иначе normal;
- для weekly верни weekdays кодами MO, TU, WE, TH, FR, SA, SU;
- для daily верни пустой список weekdays;
- due_time обязателен: извлеки местное московское время выполнения;
- не придумывай время, день недели, заведение, цифры или факты;
- если не указано время или для weekly неясен день недели, задай один короткий
  clarification_question. В остальных случаях оставь его null.
""".strip()


def build_recurring_rule_agent(settings: Settings) -> Agent:
    kwargs: dict[str, object] = {
        "name": "Извлечение повторяющейся задачи",
        "instructions": RECURRING_RULE_INSTRUCTIONS,
        "output_type": ExtractedRecurringRule,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


async def extract_recurring_rule(
    text: str,
    settings: Settings,
) -> ExtractedRecurringRule:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    now = datetime.now(LOCAL_TIMEZONE)
    prompt = (
        f"Текущее местное время: {now.isoformat()}\n"
        "Сформируй правило повторяющейся задачи из сообщения ниже.\n\n"
        f"Сообщение:\n{text.strip()}"
    )
    result = await Runner.run(build_recurring_rule_agent(settings), prompt)
    output = result.final_output
    if isinstance(output, ExtractedRecurringRule):
        draft = output
    else:
        draft = ExtractedRecurringRule.model_validate(output)

    if draft.clarification_question:
        return draft
    if draft.due_time is None:
        return draft.model_copy(
            update={"clarification_question": "В какое время должна выполняться эта задача?"}
        )
    if draft.frequency == "weekly" and not draft.weekdays:
        return draft.model_copy(
            update={"clarification_question": "В какие дни недели должна выполняться эта задача?"}
        )
    if draft.frequency == "daily" and draft.weekdays:
        draft = draft.model_copy(update={"weekdays": []})
    return draft


def first_due_at(
    draft: ExtractedRecurringRule,
    *,
    now: datetime,
) -> datetime:
    if draft.due_time is None:
        raise ValueError("Recurring rule due_time is required")

    local_now = _as_aware(now).astimezone(LOCAL_TIMEZONE)
    if draft.frequency == "daily":
        candidate = datetime.combine(
            local_now.date(),
            draft.due_time,
            tzinfo=LOCAL_TIMEZONE,
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    weekday_indexes = {WEEKDAY_INDEX[code] for code in draft.weekdays}
    if not weekday_indexes:
        raise ValueError("Weekly recurring rule requires weekdays")
    for offset in range(8):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in weekday_indexes:
            continue
        candidate = datetime.combine(
            candidate_date,
            draft.due_time,
            tzinfo=LOCAL_TIMEZONE,
        )
        if candidate > local_now:
            return candidate.astimezone(timezone.utc)
    raise RuntimeError("Could not determine first recurring due date")


def next_due_at(
    current_due_at: datetime,
    *,
    frequency: RecurrenceFrequency,
    weekdays: list[WeekdayCode],
    due_time: time,
) -> datetime:
    current_local = _as_aware(current_due_at).astimezone(LOCAL_TIMEZONE)
    if frequency == "daily":
        next_date = current_local.date() + timedelta(days=1)
        return datetime.combine(
            next_date,
            due_time,
            tzinfo=LOCAL_TIMEZONE,
        ).astimezone(timezone.utc)

    weekday_indexes = {WEEKDAY_INDEX[code] for code in weekdays}
    if not weekday_indexes:
        raise ValueError("Weekly recurring rule requires weekdays")
    for offset in range(1, 8):
        candidate_date = current_local.date() + timedelta(days=offset)
        if candidate_date.weekday() in weekday_indexes:
            return datetime.combine(
                candidate_date,
                due_time,
                tzinfo=LOCAL_TIMEZONE,
            ).astimezone(timezone.utc)
    raise RuntimeError("Could not determine next recurring due date")


def schedule_rrule(
    frequency: RecurrenceFrequency,
    weekdays: list[WeekdayCode],
) -> str:
    if frequency == "daily":
        return "FREQ=DAILY"
    normalized = sorted(set(weekdays), key=lambda code: WEEKDAY_INDEX[code])
    if not normalized:
        raise ValueError("Weekly recurring rule requires weekdays")
    return "FREQ=WEEKLY;BYDAY=" + ",".join(normalized)


def format_recurrence(
    frequency: RecurrenceFrequency,
    weekdays: list[WeekdayCode],
    due_time: time,
) -> str:
    clock = due_time.strftime("%H:%M")
    if frequency == "daily":
        return f"каждый день в {clock}"
    labels = [WEEKDAY_LABELS[code] for code in sorted(set(weekdays), key=lambda code: WEEKDAY_INDEX[code])]
    return f"{', '.join(labels)} в {clock}"


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
