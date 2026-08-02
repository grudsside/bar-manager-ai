from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .config import Settings
from .pending_action_store import get_pending_action_store
from .schemas import TaskCreate, TaskOut, TaskUpdate
from .task_drafts import extract_task_draft
from .task_store import TaskNotFoundError, get_task_store

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
TASK_COMMANDS = {"/task", "/new"}
DIRECT_STATUS_COMMANDS = {
    "/work": "work",
    "/wait": "waiting",
}
CONFIRMED_STATUS_COMMANDS = {
    "/done": "done",
    "/cancel_task": "cancelled",
}
ALL_TASK_COMMANDS = (
    TASK_COMMANDS
    | {"/tasks", "/confirm", "/cancel"}
    | set(DIRECT_STATUS_COMMANDS)
    | set(CONFIRMED_STATUS_COMMANDS)
)

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
    "done": "Завершена",
    "cancelled": "Отменена",
}


def parse_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


def parse_task_number(argument: str) -> int | None:
    try:
        number = int(argument.strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def active_tasks(tasks: list[TaskOut]) -> list[TaskOut]:
    return [task for task in tasks if task.status in ACTIVE_STATUSES]


def select_task_by_number(tasks: list[TaskOut], argument: str) -> TaskOut | None:
    number = parse_task_number(argument)
    current = active_tasks(tasks)
    if number is None or number > len(current):
        return None
    return current[number - 1]


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
    all_active = active_tasks(tasks)
    current = all_active[:10]
    if not current:
        return "Актуальных задач пока нет."

    lines = ["Актуальные задачи:"]
    for index, task in enumerate(current, start=1):
        venue = VENUE_LABELS.get(task.venue_code, "Не указано")
        due = _format_datetime(task.due_at)
        status = STATUS_LABELS.get(task.status, task.status)
        lines.append(f"{index}. {task.title}\n   {venue} · {status} · срок: {due}")
    if len(all_active) > len(current):
        lines.append("Показаны первые 10 задач.")
    lines.extend(
        [
            "",
            "Управление по номеру:",
            "/work N — взять в работу",
            "/wait N — перевести в ожидание",
            "/done N — завершить после подтверждения",
            "/cancel_task N — отменить после подтверждения",
        ]
    )
    return "\n".join(lines)


def format_status_confirmation(task: TaskOut, status: str) -> str:
    return (
        "Подтверждение изменения задачи\n"
        f"Задача: {task.title}\n"
        f"Новый статус: {STATUS_LABELS.get(status, status)}\n\n"
        "Для применения отправьте /confirm.\n"
        "Для отмены отправьте /cancel."
    )


def format_status_result(task: TaskOut) -> str:
    return (
        "Статус задачи обновлён.\n"
        f"Задача: {task.title}\n"
        f"Статус: {STATUS_LABELS.get(task.status, task.status)}"
    )


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
    if command not in ALL_TASK_COMMANDS:
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
            await reply(
                f"{draft.clarification_question}\n\n"
                "После уточнения отправьте полное поручение командой /task ещё раз."
            )
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

    if command in DIRECT_STATUS_COMMANDS or command in CONFIRMED_STATUS_COMMANDS:
        tasks = await task_store.list_tasks()
        task = select_task_by_number(tasks, argument)
        if task is None:
            await reply(
                "Не удалось определить задачу. Сначала отправьте /tasks, затем укажите "
                "номер, например /work 1."
            )
            return True

        target_status = (
            DIRECT_STATUS_COMMANDS.get(command)
            or CONFIRMED_STATUS_COMMANDS[command]
        )
        if command in DIRECT_STATUS_COMMANDS:
            updated = await task_store.update_task(
                task.id,
                TaskUpdate(status=target_status),
            )
            await reply(format_status_result(updated))
            return True

        if pending_store is None:
            await reply("Подтверждение изменения недоступно: база данных не подключена.")
            return True
        await pending_store.save_status_change(
            chat_id,
            task_id=task.id,
            status=target_status,
            title=task.title,
            source_message_id=source_message_id,
        )
        await reply(format_status_confirmation(task, target_status))
        return True

    if pending_store is None:
        await reply("Подтверждение задач недоступно: база данных не подключена.")
        return True

    pending = await pending_store.get_pending_action(chat_id)
    if pending is None:
        await reply("Нет действия, ожидающего подтверждения.")
        return True

    if command == "/cancel":
        await pending_store.resolve(pending.id, "cancelled")
        await reply("Ожидающее действие отменено.")
        return True

    if pending.action_type == "create_task":
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

    if pending.action_type == "update_task_status":
        try:
            task_id = UUID(str(pending.payload.get("task_id")))
            target_status = str(pending.payload.get("status"))
            if target_status not in {"done", "cancelled"}:
                raise ValueError("Unsupported pending task status")
            task = await task_store.update_task(
                task_id,
                TaskUpdate(status=target_status),
            )
        except (TaskNotFoundError, TypeError, ValueError):
            await pending_store.resolve(pending.id, "cancelled")
            await reply("Не удалось применить изменение: задача больше не доступна.")
            return True
        await pending_store.resolve(pending.id, "confirmed")
        await reply(format_status_result(task))
        return True

    await pending_store.resolve(pending.id, "cancelled")
    await reply("Неизвестное ожидающее действие отменено.")
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
