from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .schemas import TaskOut
from .task_store import get_task_store
from .telegram_task_commands import (
    PRIORITY_LABELS,
    STATUS_LABELS,
    VENUE_LABELS,
    active_tasks,
)

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
SEARCH_COMMANDS = {"/find"}
TASK_FILTERS = {
    "today": "на сегодня",
    "сегодня": "на сегодня",
    "overdue": "просроченные",
    "просроченные": "просроченные",
    "oxford": "Оксфорд",
    "оксфорд": "Оксфорд",
    "sovremennik": "Современник",
    "современник": "Современник",
    "high": "высокого приоритета",
    "важные": "высокого приоритета",
    "critical": "критические",
    "критические": "критические",
    "waiting": "в ожидании",
    "ожидание": "в ожидании",
}


async def maybe_handle_task_search_command(
    text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    settings: Settings,
    send_text: Any,
    conversation_store: Any,
) -> bool:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""

    is_filtered_tasks = command == "/tasks" and bool(argument)
    if command not in SEARCH_COMMANDS and not is_filtered_tasks:
        return False

    task_store = get_task_store(settings.database_url)
    tasks = await task_store.list_tasks()
    indexed = list(enumerate(active_tasks(tasks), start=1))

    if command in SEARCH_COMMANDS:
        if not argument:
            message = "Укажите текст для поиска. Например:\n/find сиропы"
        else:
            matches = _search(indexed, argument)
            message = _format_results(
                matches,
                title=f"Результаты поиска: {argument}",
                empty="По вашему запросу активных задач не найдено.",
            )
    else:
        filter_key = argument.casefold()
        if filter_key not in TASK_FILTERS:
            message = (
                "Неизвестный фильтр. Доступны:\n"
                "/tasks today — задачи на сегодня\n"
                "/tasks overdue — просроченные\n"
                "/tasks oxford — Оксфорд\n"
                "/tasks sovremennik — Современник\n"
                "/tasks high — высокий приоритет\n"
                "/tasks waiting — ожидание"
            )
        else:
            matches = _filter(indexed, filter_key, now=datetime.now(timezone.utc))
            label = TASK_FILTERS[filter_key]
            message = _format_results(
                matches,
                title=f"Задачи: {label}",
                empty=f"Активных задач в категории «{label}» нет.",
            )

    await send_text(
        settings,
        chat_id,
        message,
        store=conversation_store,
        reply_to_message_id=source_message_id,
    )
    return True


def _filter(
    indexed: list[tuple[int, TaskOut]],
    filter_key: str,
    *,
    now: datetime,
) -> list[tuple[int, TaskOut]]:
    local_today = now.astimezone(LOCAL_TIMEZONE).date()

    def matches(task: TaskOut) -> bool:
        if filter_key in {"today", "сегодня"}:
            return (
                task.due_at is not None
                and _aware(task.due_at) >= now
                and _aware(task.due_at).astimezone(LOCAL_TIMEZONE).date() == local_today
            )
        if filter_key in {"overdue", "просроченные"}:
            return task.due_at is not None and _aware(task.due_at) < now
        if filter_key in {"oxford", "оксфорд"}:
            return task.venue_code == "oxford"
        if filter_key in {"sovremennik", "современник"}:
            return task.venue_code == "sovremennik"
        if filter_key in {"high", "важные"}:
            return task.priority in {"high", "critical"}
        if filter_key in {"critical", "критические"}:
            return task.priority == "critical"
        if filter_key in {"waiting", "ожидание"}:
            return task.status == "waiting"
        return False

    return [(number, task) for number, task in indexed if matches(task)]


def _search(
    indexed: list[tuple[int, TaskOut]],
    query: str,
) -> list[tuple[int, TaskOut]]:
    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return []

    result: list[tuple[int, TaskOut]] = []
    for number, task in indexed:
        haystack = " ".join(
            part
            for part in (
                task.title,
                task.description or "",
                task.original_text or "",
                VENUE_LABELS.get(task.venue_code, ""),
            )
            if part
        ).casefold()
        if all(term in haystack for term in terms):
            result.append((number, task))
    return result


def _format_results(
    indexed: list[tuple[int, TaskOut]],
    *,
    title: str,
    empty: str,
) -> str:
    if not indexed:
        return empty

    lines = [title]
    for number, task in indexed[:10]:
        venue = VENUE_LABELS.get(task.venue_code, "Не указано")
        status = STATUS_LABELS.get(task.status, task.status)
        priority = PRIORITY_LABELS.get(task.priority, task.priority)
        due = _format_datetime(task.due_at)
        lines.append(
            f"{number}. {task.title}\n"
            f"   {venue} · {status} · {priority} · срок: {due}"
        )
    if len(indexed) > 10:
        lines.append(f"Показаны первые 10 из {len(indexed)} задач.")
    lines.extend(
        [
            "",
            "Номера совпадают с общим списком /tasks.",
            "Используйте /task_info N, /work N, /edit N и другие команды.",
        ]
    )
    return "\n".join(lines)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Не указан"
    return _aware(value).astimezone(LOCAL_TIMEZONE).strftime("%d.%m.%Y %H:%M")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
