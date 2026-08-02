from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import get_settings
from .daily_summary import (
    build_daily_summary,
    daily_summary_dedupe_key,
    daily_summary_schedule,
)
from .reminder_store import ClaimedReminder, get_reminder_store
from .task_reminders import build_task_reminder, select_reminder_kind
from .task_store import get_task_store
from .telegram_bot import send_telegram_text
from .telegram_store import get_telegram_store

POLL_INTERVAL_SECONDS = 60
MAX_DELIVERIES_PER_CYCLE = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run_reminder_cycle() -> int:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for reminder worker")
    if not settings.telegram_bot_token or settings.owner_telegram_id is None:
        raise RuntimeError("Telegram configuration is required for reminder worker")

    task_store = get_task_store(settings.database_url)
    reminder_store = get_reminder_store(settings.database_url)
    if reminder_store is None:
        raise RuntimeError("Reminder store is unavailable")

    now = datetime.now(timezone.utc)
    tasks = await task_store.list_tasks()
    for task in tasks:
        kind = select_reminder_kind(task, now=now)
        if kind is None:
            continue
        await reminder_store.ensure_event(task, build_task_reminder(task, kind))

    summary_key = None
    summary_slot = daily_summary_schedule(
        now,
        hour=settings.daily_summary_hour_msk,
        minute=settings.daily_summary_minute_msk,
    )
    if summary_slot is not None:
        summary_date, scheduled_for = summary_slot
        summary_key = daily_summary_dedupe_key(summary_date)
        await reminder_store.ensure_daily_summary(
            dedupe_key=summary_key,
            scheduled_for=scheduled_for,
            body=build_daily_summary(tasks, now=now),
        )

    conversation_store = get_telegram_store(settings.database_url)
    delivered = 0

    if summary_key is not None:
        summary = await reminder_store.claim_daily_summary(summary_key)
        if summary is not None:
            if await _deliver(
                summary,
                settings=settings,
                reminder_store=reminder_store,
                conversation_store=conversation_store,
            ):
                delivered += 1

    for _ in range(MAX_DELIVERIES_PER_CYCLE):
        reminder = await reminder_store.claim_next()
        if reminder is None:
            break
        if await _deliver(
            reminder,
            settings=settings,
            reminder_store=reminder_store,
            conversation_store=conversation_store,
        ):
            delivered += 1

    return delivered


async def _deliver(
    reminder: ClaimedReminder,
    *,
    settings: object,
    reminder_store: object,
    conversation_store: object,
) -> bool:
    try:
        await send_telegram_text(
            settings,
            settings.owner_telegram_id,
            reminder.body,
            store=conversation_store,
        )
        await reminder_store.mark_sent(reminder.id)
        logger.info(
            "Telegram notification delivered: reminder_id=%s task_id=%s severity=%s",
            reminder.id,
            reminder.task_id,
            reminder.severity,
        )
        return True
    except Exception as exc:
        await reminder_store.mark_failed(reminder.id, type(exc).__name__)
        logger.exception(
            "Telegram notification delivery failed: reminder_id=%s task_id=%s",
            reminder.id,
            reminder.task_id,
        )
        return False


async def main() -> None:
    logger.info("Task reminder and daily summary worker started")
    while True:
        try:
            delivered = await run_reminder_cycle()
            if delivered:
                logger.info("Notification cycle completed: delivered=%s", delivered)
        except Exception:
            logger.exception("Notification cycle failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
