from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.daily_summary import (
    build_daily_summary,
    daily_summary_dedupe_key,
    daily_summary_schedule,
)
from app.schemas import TaskOut

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_task(
    title: str,
    *,
    due_at: datetime | None,
    status: str = "new",
    priority: str = "normal",
) -> TaskOut:
    now = datetime.now(timezone.utc)
    return TaskOut(
        id=uuid4(),
        venue_code="oxford",
        venue_name="Оксфорд",
        title=title,
        status=status,
        priority=priority,
        due_at=due_at,
        source_type="telegram",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def test_daily_summary_starts_at_eight_moscow_time() -> None:
    before = datetime(2026, 8, 2, 4, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 2, 5, 1, tzinfo=timezone.utc)

    assert daily_summary_schedule(before, hour=8, minute=0) is None

    summary_date, scheduled_for = daily_summary_schedule(after, hour=8, minute=0)
    assert summary_date.isoformat() == "2026-08-02"
    assert scheduled_for == datetime(2026, 8, 2, 5, 0, tzinfo=timezone.utc)


def test_summary_contains_operational_groups_and_counts() -> None:
    now = datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc)
    tasks = [
        make_task("Просроченная", due_at=now - timedelta(hours=1)),
        make_task("Сегодня", due_at=now + timedelta(hours=2)),
        make_task(
            "Критичная без срока",
            due_at=None,
            priority="critical",
        ),
        make_task(
            "Ожидает поставку",
            due_at=now + timedelta(days=1),
            status="waiting",
        ),
        make_task(
            "Завершённая",
            due_at=now - timedelta(hours=2),
            status="done",
        ),
    ]

    rendered = build_daily_summary(tasks, now=now)

    assert "Активных задач: 4" in rendered
    assert "Просрочено: 1" in rendered
    assert "На сегодня: 1" in rendered
    assert "В ожидании: 1" in rendered
    assert "Высокий приоритет: 1" in rendered
    assert "Просроченная" in rendered
    assert "Сегодня" in rendered
    assert "Критичная без срока" in rendered
    assert "Ожидает поставку" in rendered
    assert "Завершённая" not in rendered


def test_daily_summary_dedupe_key_is_one_per_local_day() -> None:
    first = daily_summary_dedupe_key(datetime(2026, 8, 2).date())
    second = daily_summary_dedupe_key(datetime(2026, 8, 3).date())

    assert first == "daily-summary:2026-08-02"
    assert first != second


def test_daily_summary_deployment_and_command_contract() -> None:
    worker = (REPO_ROOT / "backend" / "app" / "reminder_worker.py").read_text(
        encoding="utf-8"
    )
    store = (REPO_ROOT / "backend" / "app" / "reminder_store.py").read_text(
        encoding="utf-8"
    )
    bot = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    compose = (
        REPO_ROOT / "deploy" / "firstvds" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    assert "daily_summary_schedule" in worker
    assert "claim_daily_summary" in worker
    assert "daily_task_summary" in store
    assert "on conflict (dedupe_key) do update" in store
    assert "maybe_handle_summary_command" in bot
    assert "/summary" in bot
    assert "DAILY_SUMMARY_HOUR_MSK" in compose
