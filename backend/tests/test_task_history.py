import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskCreate, TaskOut, TaskUpdate
from app.task_history import format_task_card
from app.task_store import InMemoryTaskStore, TaskEventOut, TaskNotFoundError

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


def test_task_card_contains_fields_notes_results_and_readable_history() -> None:
    task = make_task()
    events = [
        TaskEventOut(
            id=uuid4(),
            event_type="completed_with_result",
            actor_type="telegram",
            payload={"result": "Остатки сверены, недостающие сиропы заказаны"},
            created_at=datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc),
        ),
        TaskEventOut(
            id=uuid4(),
            event_type="note_added",
            actor_type="telegram",
            payload={"text": "Поставщик подтвердил доставку к 15:00"},
            created_at=datetime(2026, 8, 2, 12, 45, tzinfo=timezone.utc),
        ),
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
    assert "заметка: Поставщик подтвердил доставку к 15:00 · Telegram" in rendered
    assert "завершена. Результат: Остатки сверены" in rendered
    assert "создана · Владелец" in rendered


def test_in_memory_store_records_create_update_and_note_events() -> None:
    async def scenario() -> None:
        store = InMemoryTaskStore()
        task = await store.create_task(
            TaskCreate(
                title="Проверить остатки",
                venue_code="oxford",
                source_type="telegram",
            )
        )
        await store.update_task(task.id, TaskUpdate(status="work", priority="high"))
        note = await store.add_task_note(
            task.id,
            "  Поставщик   подтвердил доставку  ",
            actor_type="telegram",
        )

        events = await store.list_task_events(task.id)

        assert [event.event_type for event in events] == [
            "note_added",
            "updated",
            "created",
        ]
        assert note.payload == {"text": "Поставщик подтвердил доставку"}
        assert note.actor_type == "telegram"
        assert events[1].payload == {"status": "work", "priority": "high"}

    asyncio.run(scenario())


def test_complete_task_stores_result_and_status_together() -> None:
    async def scenario() -> None:
        store = InMemoryTaskStore()
        task = await store.create_task(TaskCreate(title="Проверить остатки"))

        completed = await store.complete_task(
            task.id,
            "  Остатки сверены,   сиропы заказаны  ",
            actor_type="telegram",
        )
        events = await store.list_task_events(task.id)

        assert completed.status == "done"
        assert completed.completed_at is not None
        assert events[0].event_type == "completed_with_result"
        assert events[0].payload == {
            "result": "Остатки сверены, сиропы заказаны"
        }
        assert events[0].actor_type == "telegram"

        try:
            await store.complete_task(task.id, "Повторное завершение")
        except TaskNotFoundError:
            pass
        else:
            raise AssertionError("Completed task was completed twice")

    asyncio.run(scenario())


def test_empty_and_oversized_notes_and_results_are_rejected() -> None:
    async def scenario() -> None:
        store = InMemoryTaskStore()
        task = await store.create_task(TaskCreate(title="Проверка"))

        for invalid in ("   ", "x" * 2_001):
            try:
                await store.add_task_note(task.id, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid note was accepted")

            try:
                await store.complete_task(task.id, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid completion result was accepted")

    asyncio.run(scenario())


def test_telegram_history_and_completion_routing_contract() -> None:
    bot = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    history_command = (
        REPO_ROOT / "backend" / "app" / "telegram_task_history_commands.py"
    ).read_text(encoding="utf-8")
    completion_command = (
        REPO_ROOT / "backend" / "app" / "telegram_task_completion_commands.py"
    ).read_text(encoding="utf-8")
    store = (REPO_ROOT / "backend" / "app" / "task_store.py").read_text(
        encoding="utf-8"
    )

    assert "maybe_handle_task_history_command" in bot
    assert "maybe_handle_task_completion_command" in bot
    assert bot.index("maybe_handle_task_completion_command(") < bot.index(
        "maybe_handle_task_command("
    )
    assert bot.index("maybe_handle_task_history_command(") < bot.index(
        "maybe_handle_task_command("
    )
    assert 'TASK_INFO_COMMANDS = {"/task_info", "/info"}' in history_command
    assert 'TASK_NOTE_COMMANDS = {"/note"}' in history_command
    assert 'COMPLETION_COMMANDS = {"/complete", "/finish"}' in completion_command
    assert "complete_task" in store
    assert "completed_with_result" in store
    assert "/task_info N" in bot
    assert "/complete N <результат>" in bot
