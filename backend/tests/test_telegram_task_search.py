from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskOut
from app.telegram_task_search_commands import _filter, _format_results, _search

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_task(
    title: str,
    *,
    venue_code: str | None = "oxford",
    status: str = "new",
    priority: str = "normal",
    due_at: datetime | None = None,
    description: str | None = None,
) -> TaskOut:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    return TaskOut(
        id=uuid4(),
        venue_code=venue_code,
        venue_name={
            "oxford": "Оксфорд",
            "sovremennik": "Современник",
        }.get(venue_code),
        title=title,
        description=description,
        status=status,
        priority=priority,
        due_at=due_at,
        source_type="telegram",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def test_filters_preserve_global_task_numbers() -> None:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    indexed = [
        (1, make_task("Просроченная", due_at=now - timedelta(hours=1))),
        (
            2,
            make_task(
                "Проверить сиропы",
                venue_code="oxford",
                priority="high",
                due_at=now + timedelta(hours=2),
            ),
        ),
        (
            3,
            make_task(
                "Заказать молоко",
                venue_code="sovremennik",
                status="waiting",
                due_at=now + timedelta(days=1),
            ),
        ),
    ]

    today = _filter(indexed, "today", now=now)
    overdue = _filter(indexed, "overdue", now=now)
    high = _filter(indexed, "high", now=now)
    waiting = _filter(indexed, "waiting", now=now)

    assert [number for number, _ in today] == [1, 2]
    assert [number for number, _ in overdue] == [1]
    assert [number for number, _ in high] == [2]
    assert [number for number, _ in waiting] == [3]


def test_search_checks_title_description_and_venue() -> None:
    indexed = [
        (
            1,
            make_task(
                "Проверить остатки",
                description="Сиропы и пюре на складе",
                venue_code="oxford",
            ),
        ),
        (2, make_task("Заказать стаканы", venue_code="sovremennik")),
    ]

    assert [number for number, _ in _search(indexed, "сиропы склад")] == [1]
    assert [number for number, _ in _search(indexed, "современник стаканы")] == [2]
    assert _search(indexed, "кофемолка") == []


def test_filtered_output_keeps_original_number_and_explains_safety() -> None:
    task = make_task("Проверить остатки", priority="critical")

    rendered = _format_results(
        [(7, task)],
        title="Задачи: критические",
        empty="Нет задач",
    )

    assert "7. Проверить остатки" in rendered
    assert "Критический" in rendered
    assert "Номера совпадают с общим списком /tasks" in rendered


def test_telegram_search_routing_contract() -> None:
    bot = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    commands = (
        REPO_ROOT / "backend" / "app" / "telegram_task_search_commands.py"
    ).read_text(encoding="utf-8")

    assert "maybe_handle_task_search_command" in bot
    assert bot.index("maybe_handle_task_search_command(") < bot.index(
        "maybe_handle_task_command("
    )
    assert 'SEARCH_COMMANDS = {"/find"}' in commands
    assert 'command == "/tasks" and bool(argument)' in commands
    assert "Номера совпадают с общим списком /tasks" in commands
    assert "/tasks <filter>" in bot
    assert "/find <текст>" in bot
