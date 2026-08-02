from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .task_history import format_task_card
from .task_store import get_task_store

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
ARCHIVE_STATUSES = {"done", "cancelled"}
ARCHIVE_LIST_COMMANDS = {"/archive", "/completed", "/closed"}
ARCHIVE_INFO_COMMANDS = {"/archive_info", "/closed_info"}
ARCHIVE_COMMANDS = ARCHIVE_LIST_COMMANDS | ARCHIVE_INFO_COMMANDS
ARCHIVE_LIMIT = 10

STATUS_LABELS = {
    "done": "Завершена",
    "cancelled": "Отменена",
}
VENUE_LABELS = {
    "oxford": "Оксфорд",
    "sovremennik": "Современник",
    None: "Не указано",
}


def archived_tasks(tasks: list[Any]) -> list[Any]:
    archived = [task for task in tasks if task.status in ARCHIVE_STATUSES]
    return sorted(archived, key=_archive_sort_key, reverse=True)


def select_archive_task(tasks: list[Any], number: int) -> Any | None:
    archive = archived_tasks(tasks)
    if number < 1 or number > len(archive):
        return None
    return archive[number - 1]


def format_archive_list(tasks: list[Any], filter_name: str = "all") -> str:
    archive = archived_tasks(tasks)
    normalized_filter = _normalize_filter(filter_name)
    filtered = [
        (index, task)
        for index, task in enumerate(archive, start=1)
        if _matches_filter(task, normalized_filter)
    ]

    if not filtered:
        return f"В архиве нет задач по фильтру: {_filter_label(normalized_filter)}."

    lines = [f"Архив задач · {_filter_label(normalized_filter)}:"]
    for index, task in filtered[:ARCHIVE_LIMIT]:
        venue = VENUE_LABELS.get(task.venue_code, "Не указано")
        status = STATUS_LABELS.get(task.status, task.status)
        closed_at = task.completed_at or task.updated_at
        lines.append(
            f"{index}. {task.title}\n"
            f"   {venue} · {status} · {_format_datetime(closed_at)}"
        )

    if len(filtered) > ARCHIVE_LIMIT:
        lines.append(f"Показаны первые {ARCHIVE_LIMIT} из {len(filtered)} задач.")

    lines.extend(
        [
            "",
            "Номера относятся к общему архиву и не меняются при фильтрации.",
            "/archive_info N — открыть карточку, историю и результат",
            "Фильтры: /archive done, /archive cancelled, /archive oxford, "
            "/archive sovremennik",
        ]
    )
    return "\n".join(lines)


async def maybe_handle_task_archive_command(
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
    if command not in ARCHIVE_COMMANDS:
        return False

    argument = parts[1].strip() if len(parts) > 1 else ""
    task_store = get_task_store(settings.database_url)
    tasks = await task_store.list_tasks()

    if command in ARCHIVE_INFO_COMMANDS:
        number = _parse_number(argument)
        task = select_archive_task(tasks, number)
        if task is None:
            message = (
                "Не удалось определить архивную задачу. Сначала отправьте /archive, "
                "затем укажите номер, например /archive_info 1."
            )
        else:
            events = await task_store.list_task_events(task.id, limit=15)
            message = format_task_card(task, events)
    else:
        filter_name = "done" if command == "/completed" else argument or "all"
        normalized_filter = _normalize_filter(filter_name)
        if normalized_filter == "invalid":
            message = (
                "Неизвестный фильтр архива. Используйте:\n"
                "/archive\n"
                "/archive done\n"
                "/archive cancelled\n"
                "/archive oxford\n"
                "/archive sovremennik"
            )
        else:
            message = format_archive_list(tasks, normalized_filter)

    await send_text(
        settings,
        chat_id,
        message,
        store=conversation_store,
        reply_to_message_id=source_message_id,
    )
    return True


def _normalize_filter(value: str) -> str:
    normalized = value.strip().lower().replace("ё", "е")
    aliases = {
        "": "all",
        "all": "all",
        "все": "all",
        "done": "done",
        "completed": "done",
        "готово": "done",
        "завершенные": "done",
        "завершенные задачи": "done",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "отмененные": "cancelled",
        "отмененные задачи": "cancelled",
        "oxford": "oxford",
        "оксфорд": "oxford",
        "sovremennik": "sovremennik",
        "современник": "sovremennik",
    }
    return aliases.get(normalized, "invalid")


def _matches_filter(task: Any, filter_name: str) -> bool:
    if filter_name == "all":
        return True
    if filter_name in ARCHIVE_STATUSES:
        return task.status == filter_name
    if filter_name in {"oxford", "sovremennik"}:
        return task.venue_code == filter_name
    return False


def _filter_label(filter_name: str) -> str:
    return {
        "all": "все",
        "done": "завершённые",
        "cancelled": "отменённые",
        "oxford": "Оксфорд",
        "sovremennik": "Современник",
    }.get(filter_name, filter_name)


def _archive_sort_key(task: Any) -> datetime:
    value = task.completed_at or task.updated_at or task.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "дата не указана"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(LOCAL_TIMEZONE).strftime("%d.%m.%Y %H:%M")


def _parse_number(value: str) -> int:
    try:
        number = int(value.strip())
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0
