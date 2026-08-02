from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.schemas import TaskCreate, TaskOut, TaskUpdate
from app.task_history import format_task_card
from app.task_store import InMemoryTaskStore, TaskEventOut

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_task() -> TaskOut:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    return TaskOut(
        id=uuid4(),
        venue_code="oxford",
        venue_name="Оксфорд",
        title="Проверить остатки сиропов",
        description="Сверить со складским отчётом",
        status="work",
        priority="high",
        due_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        source_type="telegram",
        source_reference="telegram:1:2",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def test_task_card_contains_fields_and_readable_history() -> None:
    task = make_task()
    events = [
        TaskEventOut(
            id=uuid4(),
            event_type="updated",
            actor_type="owner",
            payload={
                "status": "work",
                "priority": "high",
                "due_at": "2026-08-03T09:00:00+00:00",
            },
            created_at=datetime(2026, 8, 2, 12, 30, tzinfo=timezone.utc),
        ),
        TaskEventOut(
            id=uuid4(),
            event_type="created",
            actor_type="owner",
            payload={},
            created_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    rendered = format_task_card(task, events)

    assert "Карточка задачи" in rendered
    assert "Статус: В работе" in rendered
    assert "Приоритет: Высокий" in rendered
    assert "Источник: Telegram" in rendered
    assert "статус → В работе" in rendered
    assert "приоритет → Высокий" in rendered
    assert "создана · Владелец" in rendered


@pytest.mark.asyncio
async def test_in_memory_store_records_create_and_update_events() -> None:
    store = InMemoryTaskStore()
    task = await store.create_task(
        TaskCreate(
            title="Проверить остатки",
            venue_code="oxford",
            source_type="telegram",
        )
    )
    await store.update_task(task.id, TaskUpdate(status="work", priority="high"))

    events = await store.list_task_events(task.id)

    assert [event.event_type for event in events] == ["updated", "created"]
    assert events[0].payload == {"status": "work", "priority": "high"}


def test_telegram_history_routing_contract() -> None:
    bot = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    command = (
        REPO_ROOT / "backend" / "app" / "telegram_task_history_commands.py"
    ).read_text(encoding="utf-8")
    store = (REPO_ROOT / "backend" / "app" / "task_store.py").read_text(
        encoding="utf-8"
    )

    assert "maybe_handle_task_history_command" in bot
    assert bot.index("maybe_handle_task_history_command(") < bot.index(
        "maybe_handle_task_command("
    )
    assert 'TASK_INFO_COMMANDS = {"/task_info", "/info"}' in command
    assert "list_task_events" in store
    assert "/task_info N" in bot
