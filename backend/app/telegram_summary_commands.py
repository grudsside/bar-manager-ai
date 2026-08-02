from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .daily_summary import build_daily_summary
from .task_store import get_task_store


async def maybe_handle_summary_command(
    text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    settings: Settings,
    send_text: Any,
    conversation_store: Any,
) -> bool:
    command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command != "/summary":
        return False

    task_store = get_task_store(settings.database_url)
    tasks = await task_store.list_tasks()
    await send_text(
        settings,
        chat_id,
        build_daily_summary(
            tasks,
            now=datetime.now(timezone.utc),
            heading="Сводка задач",
        ),
        store=conversation_store,
        reply_to_message_id=source_message_id,
    )
    return True
