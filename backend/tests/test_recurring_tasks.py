from datetime import datetime, time, timezone
from pathlib import Path

from app.recurring_rules import (
    ExtractedRecurringRule,
    first_due_at,
    format_recurrence,
    next_due_at,
    schedule_rrule,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_daily_rule_uses_next_local_occurrence() -> None:
    draft = ExtractedRecurringRule(
        title="Проверить остатки сиропов",
        venue_code="oxford",
        frequency="daily",
        due_time=time(10, 0),
    )

    before = first_due_at(
        draft,
        now=datetime(2026, 8, 2, 5, 0, tzinfo=timezone.utc),
    )
    after = first_due_at(
        draft,
        now=datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc),
    )

    assert before == datetime(2026, 8, 2, 7, 0, tzinfo=timezone.utc)
    assert after == datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)


def test_weekly_rule_selects_nearest_named_weekday() -> None:
    draft = ExtractedRecurringRule(
        title="Провести ревизию",
        frequency="weekly",
        weekdays=["MO", "FR"],
        due_time=time(9, 30),
    )

    first = first_due_at(
        draft,
        now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    following = next_due_at(
        first,
        frequency="weekly",
        weekdays=["MO", "FR"],
        due_time=time(9, 30),
    )

    assert first == datetime(2026, 8, 3, 6, 30, tzinfo=timezone.utc)
    assert following == datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc)


def test_schedule_and_human_label_are_normalized() -> None:
    assert schedule_rrule("daily", []) == "FREQ=DAILY"
    assert schedule_rrule("weekly", ["FR", "MO", "FR"]) == (
        "FREQ=WEEKLY;BYDAY=MO,FR"
    )
    assert format_recurrence("weekly", ["FR", "MO"], time(10, 0)) == (
        "понедельник, пятница в 10:00"
    )


def test_recurring_task_schema_and_worker_contract() -> None:
    migration = (
        REPO_ROOT / "backend" / "migrations" / "006_recurring_task_generation.sql"
    ).read_text(encoding="utf-8")
    store = (REPO_ROOT / "backend" / "app" / "recurring_store.py").read_text(
        encoding="utf-8"
    )
    worker = (REPO_ROOT / "backend" / "app" / "reminder_worker.py").read_text(
        encoding="utf-8"
    )
    bot = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    task_commands = (
        REPO_ROOT / "backend" / "app" / "telegram_task_commands.py"
    ).read_text(encoding="utf-8")

    assert "next_due_at" in migration
    assert "tasks_recurring_source_reference_idx" in migration
    assert "create_recurring_rule" in migration
    assert "disable_recurring_rule" in migration
    assert "for update skip locked" in store
    assert "on conflict do nothing" in store
    assert "STALE_OCCURRENCE_LIMIT" in store
    assert "'recurring_rule_id', $2::uuid::text" in store
    assert "generate_due_tasks" in worker
    assert "maybe_handle_recurring_command" in bot
    assert bot.index("maybe_handle_recurring_command") < bot.index(
        "maybe_handle_task_command"
    )
    assert 'pending.action_type == "create_recurring_rule"' in task_commands
    assert 'pending.action_type == "disable_recurring_rule"' in task_commands
