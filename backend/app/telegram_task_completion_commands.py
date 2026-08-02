from __future__ import annotations

from typing import Any
from uuid import UUID

from .config import Settings
from .pending_action_store import get_pending_action_store
from .task_store import TaskNotFoundError, get_task_store
from .telegram_task_commands import select_task_by_index

COMPLETION_COMMANDS = {"/complete", "/finish"}
CONFIRMATION_COMMANDS = {"/confirm", "/cancel"}


def parse_completion_argument(argument: str) -> tuple[int | None, str]:
    parts = argument.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    try:
        number = int(parts[0])
    except ValueError:
        return None, ""
    result = parts[1].strip() if len(parts) > 1 else ""
    return (number if number > 0 else None), result


async def maybe_handle_task_completion_command(
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
    if command not in COMPLETION_COMMANDS | CONFIRMATION_COMMANDS:
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

    if command in COMPLETION_COMMANDS:
        number, raw_result = parse_completion_argument(argument)
        try:
            result = _normalize_result(raw_result)
        except ValueError:
            result = ""

        tasks = await task_store.list_tasks()
        task = select_task_by_index(tasks, number)
        if task is None or not result:
            await reply(
                "Сначала отправьте /tasks, затем укажите номер и результат. Например:\n"
                "/complete 1 Остатки проверены, недостающие сиропы заказаны"
            )
            return True
        if pending_store is None:
            await reply("Завершение с результатом недоступно: база данных не подключена.")
            return True

        await pending_store.save_status_change(
            chat_id,
            task_id=task.id,
            status="done",
            title=task.title,
            result=result,
            source_message_id=source_message_id,
        )
        await reply(
            "Подтверждение завершения задачи\n"
            f"Задача: {task.title}\n"
            f"Результат: {result}\n\n"
            "Для завершения отправьте /confirm.\n"
            "Для отмены отправьте /cancel."
        )
        return True

    if pending_store is None:
        return False
    pending = await pending_store.get_pending_action(chat_id)
    if not _is_completion_action(pending):
        return False

    if command == "/cancel":
        await pending_store.resolve(pending.id, "cancelled")
        await reply("Завершение задачи отменено.")
        return True

    try:
        task_id = UUID(str(pending.payload.get("task_id")))
        result = _normalize_result(str(pending.payload.get("result") or ""))
        task = await task_store.complete_task(
            task_id,
            result,
            actor_type="telegram",
        )
    except (TaskNotFoundError, TypeError, ValueError):
        await pending_store.resolve(pending.id, "cancelled")
        await reply("Не удалось завершить задачу: она больше не доступна.")
        return True

    await pending_store.resolve(pending.id, "confirmed")
    await reply(
        "Задача завершена.\n"
        f"Задача: {task.title}\n"
        f"Результат: {result}\n\n"
        "Результат сохранён в /task_info."
    )
    return True


def _is_completion_action(pending: Any) -> bool:
    if pending is None or pending.action_type != "update_task_status":
        return False
    return (
        pending.payload.get("status") == "done"
        and isinstance(pending.payload.get("result"), str)
        and bool(pending.payload["result"].strip())
    )


def _normalize_result(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        raise ValueError("Completion result cannot be empty")
    if len(normalized) > 2_000:
        raise ValueError("Completion result is too long")
    return normalized
