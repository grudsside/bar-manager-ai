from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .pending_action_store import get_pending_action_store
from .schemas import TaskCreate, TaskOut
from .task_drafts import extract_task_draft
from .task_store import get_task_store

LOCAL_TIMEZONE = ZoneInfo("Europe/Moscow")
ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
TASK_COMMANDS = {"/task", "/new"}

VENUE_LABELS = {
    "oxford": "Оксфорд",
    "sovremennik": "Современник",
    None: "Не указано",
}
PRIORITY_LABELS = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Критический",
}
STATUS_LABELS = {
    "new": "Новая",
    "planned": "Запланирована",
    "work": "В работе",
    "waiting": "Ожидание",
}


def parse_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


def format_task_preview(payload: TaskCreate) -> str:
    lines = [
        "Проект задачи",
        f"Задача: {payload.title}",
        f"Заведение: {VENUE_LABELS.get(payload.venue_code, 'Не указано')}",
        f"Приоритет: {PRIORITY_LABELS.get(payload.priority, payload.priority)}",
        f"Срок: {_format_datetime(payload.due_at)}",
    ]
    if payload.description:
        lines.append(f"Детали: {payload.description}")
    lines.extend(
        [
            "",
            "Для создания отправьте /confirm.",
            "Для отмены отправьте /cancel.",
        ]
    )
    return "\n".join(lines)


def format_task_list(tasks: list[TaskOut]) -> str:
    active = [task for task in tasks if task.status in ACTIVE_STATUSES][:10]
    if not active:
        return "Актуальных задач пока нет."

    lines = ["Актуальные задачи:"]
    for index, task in enumerate(active, start=1):
        venue = VENUE_LABELS.get(task.venue_code, "Не указано")
        due = _format_datetime(task.due_at)
        status = STATUS_LABELS.get(task.status, task.status)
        lines.append(f"{index}. {task.title}\n   {venue} · {status} · срок: {due}")
    if len([task for task in tasks if task.status in ACTIVE_STATUSES]) > len(active):
        lines.append("Показаны первые 10 задач.")
    return "\n".join(lines)


async def maybe_handle_task_command(
    text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    settings: Settings,
    send_text: Any,
    conversation_store: Any,
) -> bool:
    command, argument = parse_command(text)
    if command not in TASK_COMMANDS | {"/tasks", "/confirm", "/cancel"}:
        return False

    pending_store = get_pending_action_store(settings.database_url)
    task_store = get_task_store(settings.database_url)

    async def reply(message: str) -> None:
        await send_text(
            settings,
            chat_id,
            message,
            store=conversation_store,
            reply_to_message_id=source_message_id,
        )

    if command in TASK_COMMANDS:
        if not argument:
            await reply(
                "После команды укажите поручение. Например:\n"
                "/task Оксфорд — проверить остатки сиропов завтра до 12:00"
            )
            return True
        if pending_store is None:
            await reply("Создание задач недоступно: база данных не подключена.")
            return True

        draft = await extract_task_draft(argument, settings)
        if draft.clarification_question:
            await reply(draft.clarification_question)
            return True

        payload = TaskCreate(
            title=draft.title,
            description=draft.description,
            original_text=argument,
            venue_code=draft.venue_code,
            status="new",
            priority=draft.priority,
            due_at=draft.due_at,
            source_type="telegram",
            source_reference=f"telegram:{chat_id}:{source_message_id or 0}",
            requires_confirmation=False,
        )
        await pending_store.save_task_draft(
            chat_id,
            payload.model_dump(mode="json"),
            source_message_id=source_message_id,
        )
        await reply(format_task_preview(payload))
        return True

    if command == "/tasks":
        tasks = await task_store.list_tasks()
        await reply(format_task_list(tasks))
        return True

    if pending_store is None:
        await reply("Подтверждение задач недоступно: база данных не подключена.")
        return True

    pending = await pending_store.get_pending_task(chat_id)
    if pending is None:
        await reply("Нет проекта задачи, ожидающего подтверждения.")
        return True

    if command == "/cancel":
        await pending_store.resolve(pending.id, "cancelled")
        await reply("Проект задачи отменён.")
        return True

    payload = TaskCreate.model_validate(pending.payload)
    task = await task_store.create_task(payload)
    await pending_store.resolve(pending.id, "confirmed")
    await reply(
        "Задача создана.\n"
        f"{task.title}\n"
        f"Заведение: {VENUE_LABELS.get(task.venue_code, 'Не указано')}\n"
        f"Срок: {_format_datetime(task.due_at)}"
    )
    return True


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Не указан"
    localized = value
    if localized.tzinfo is None:
        localized = localized.replace(tzinfo=LOCAL_TIMEZONE)
    else:
        localized = localized.astimezone(LOCAL_TIMEZONE)
    return localized.strftime("%d.%m.%Y %H:%M")
