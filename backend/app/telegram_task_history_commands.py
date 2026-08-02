from __future__ import annotations

from typing import Any

from .config import Settings
from .task_history import format_task_card
from .task_store import get_task_store

ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
TASK_INFO_COMMANDS = {"/task_info", "/info"}


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
    if command not in TASK_INFO_COMMANDS:
        return False

    argument = parts[1].strip() if len(parts) > 1 else ""
    try:
        number = int(argument)
    except ValueError:
        number = 0

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
