from __future__ import annotations

from typing import Any

from .config import Settings
from .task_history import format_task_card
from .task_store import get_task_store
from .telegram_task_archive_commands import (
    ARCHIVE_COMMANDS,
    maybe_handle_task_archive_command,
)

ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
TASK_INFO_COMMANDS = {"/task_info", "/info"}
TASK_NOTE_COMMANDS = {"/note"}
TASK_HISTORY_COMMANDS = TASK_INFO_COMMANDS | TASK_NOTE_COMMANDS | ARCHIVE_COMMANDS


async def maybe_handle_task_history_command(
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
    if command not in TASK_HISTORY_COMMANDS:
        return False

    if command in ARCHIVE_COMMANDS:
        return await maybe_handle_task_archive_command(
            text,
            chat_id=chat_id,
            source_message_id=source_message_id,
            settings=settings,
            send_text=send_text,
            conversation_store=conversation_store,
        )

    argument = parts[1].strip() if len(parts) > 1 else ""
    number, note_text = _parse_number_and_text(argument)

    task_store = get_task_store(settings.database_url)
    tasks = await task_store.list_tasks()
    active = [task for task in tasks if task.status in ACTIVE_STATUSES]

    if number < 1 or number > len(active):
        message = (
            "Не удалось определить задачу. Сначала отправьте /tasks, затем укажите "
            "номер, например /task_info 1."
        )
    else:
        task = active[number - 1]
        if command in TASK_NOTE_COMMANDS:
            if not note_text:
                message = (
                    "После номера укажите текст заметки. Например:\n"
                    "/note 1 Поставщик подтвердил доставку к 15:00"
                )
            else:
                try:
                    await task_store.add_task_note(
                        task.id,
                        note_text,
                        actor_type="telegram",
                    )
                except ValueError:
                    message = "Заметка должна содержать от 1 до 2000 символов."
                else:
                    message = (
                        "Заметка добавлена.\n"
                        f"Задача: {task.title}\n"
                        f"Заметка: {note_text.strip()}"
                    )
        else:
            events = await task_store.list_task_events(task.id, limit=10)
            message = format_task_card(task, events)

    await send_text(
        settings,
        chat_id,
        message,
        store=conversation_store,
        reply_to_message_id=source_message_id,
    )
    return True


def _parse_number_and_text(argument: str) -> tuple[int, str]:
    parts = argument.strip().split(maxsplit=1)
    try:
        number = int(parts[0]) if parts else 0
    except ValueError:
        number = 0
    text = parts[1].strip() if len(parts) > 1 else ""
    return number, text
