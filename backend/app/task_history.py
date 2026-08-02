from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import TaskOut
from .task_store import TaskEventOut

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")

VENUE_LABELS = {
    "oxford": "Оксфорд",
    "sovremennik": "Современник",
    None: "Не указано",
}
STATUS_LABELS = {
    "new": "Новая",
    "planned": "Запланирована",
    "work": "В работе",
    "waiting": "Ожидание",
    "done": "Завершена",
    "cancelled": "Отменена",
}
PRIORITY_LABELS = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Критический",
}
SOURCE_LABELS = {
    "manual": "Ручное создание",
    "telegram": "Telegram",
    "recurring": "Повторяющееся правило",
    "agent": "AI-агент",
    "file": "Файл",
}
ACTOR_LABELS = {
    "owner": "Владелец",
    "telegram": "Telegram",
    "agent": "AI-агент",
    "system": "Система",
}
FIELD_LABELS = {
    "title": "Название",
    "description": "Детали",
    "venue_code": "Заведение",
    "status": "Статус",
    "priority": "Приоритет",
    "due_at": "Срок",
    "waiting_until": "Ожидание до",
}
FIELD_ORDER = (
    "title",
    "description",
    "venue_code",
    "status",
    "priority",
    "due_at",
    "waiting_until",
)


def format_task_card(task: TaskOut, events: list[TaskEventOut]) -> str:
    lines = [
        "Карточка задачи",
        "",
        f"Задача: {task.title}",
        f"Статус: {STATUS_LABELS.get(task.status, task.status)}",
        f"Приоритет: {PRIORITY_LABELS.get(task.priority, task.priority)}",
        f"Заведение: {VENUE_LABELS.get(task.venue_code, 'Не указано')}",
        f"Срок: {_format_datetime(task.due_at)}",
        f"Источник: {SOURCE_LABELS.get(task.source_type, task.source_type)}",
        f"Создана: {_format_datetime(task.created_at)}",
        f"Изменена: {_format_datetime(task.updated_at)}",
    ]
    if task.description:
        lines.extend(["", f"Детали: {_short(task.description, 500)}"])
    if task.completed_at:
        lines.append(f"Завершена: {_format_datetime(task.completed_at)}")

    lines.extend(["", "История:"])
    if not events:
        lines.append("История изменений пока пуста.")
    else:
        for event in events:
            lines.append(_format_event(event))

    return "\n".join(lines)


def _format_event(event: TaskEventOut) -> str:
    stamp = _format_datetime(event.created_at, include_year=False)
    actor = ACTOR_LABELS.get(event.actor_type, event.actor_type)

    if event.event_type == "created":
        return f"• {stamp} — создана · {actor}"
    if event.event_type == "generated_from_recurring_rule":
        return f"• {stamp} — создана повторяющимся правилом · {actor}"
    if event.event_type == "note_added":
        note = _short(event.payload.get("text") or "Пустая заметка", 500)
        return f"• {stamp} — заметка: {note} · {actor}"
    if event.event_type == "updated":
        changes = _format_changes(event.payload)
        suffix = f": {changes}" if changes else ""
        return f"• {stamp} — изменена{suffix} · {actor}"
    return f"• {stamp} — {event.event_type} · {actor}"


def _format_changes(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in FIELD_ORDER:
        if field not in payload:
            continue
        label = FIELD_LABELS[field]
        parts.append(f"{label.lower()} → {_format_field_value(field, payload[field])}")
    return "; ".join(parts)


def _format_field_value(field: str, value: Any) -> str:
    if field == "venue_code":
        return VENUE_LABELS.get(value, "Не указано")
    if field == "status":
        return STATUS_LABELS.get(value, str(value))
    if field == "priority":
        return PRIORITY_LABELS.get(value, str(value))
    if field in {"due_at", "waiting_until"}:
        if value is None:
            return "не указан"
        try:
            return _format_datetime(datetime.fromisoformat(str(value)))
        except ValueError:
            return _short(value)
    if value in {None, ""}:
        return "не указаны"
    return _short(value)


def _format_datetime(
    value: datetime | None,
    *,
    include_year: bool = True,
) -> str:
    if value is None:
        return "Не указан"
    if value.tzinfo is None:
        localized = value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE)
    else:
        localized = value.astimezone(LOCAL_TIMEZONE)
    pattern = "%d.%m.%Y %H:%M" if include_year else "%d.%m %H:%M"
    return localized.strftime(pattern)


def _short(value: object, limit: int = 180) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
