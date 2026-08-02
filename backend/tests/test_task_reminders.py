from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskOut
from app.task_reminders import build_task_reminder, select_reminder_kind

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_task(*, due_at: datetime, status: str = "new") -> TaskOut:
    now = datetime.now(timezone.utc)
    return TaskOut(
        id=uuid4(),
        venue_code="oxford",
        venue_name="Оксфорд",
        title="Проверить остатки сиропов",
        status=status,
        priority="normal",
        due_at=due_at,
        source_type="telegram",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def test_reminder_kind_follows_nearest_deadline_window() -> None:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)

    assert select_reminder_kind(
        make_task(due_at=now + timedelta(hours=30)), now=now
    ) is None
    assert select_reminder_kind(
        make_task(due_at=now + timedelta(hours=12)), now=now
    ) == "task_due_24h"
    assert select_reminder_kind(
        make_task(due_at=now + timedelta(minutes=90)), now=now
    ) == "task_due_2h"
    assert select_reminder_kind(
        make_task(due_at=now - timedelta(minutes=1)), now=now
    ) == "task_overdue"


def test_completed_task_never_generates_reminder() -> None:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    task = make_task(due_at=now - timedelta(hours=1), status="done")

    assert select_reminder_kind(task, now=now) is None


def test_dedupe_key_changes_when_deadline_changes() -> None:
    first_due = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    task = make_task(due_at=first_due)

    first = build_task_reminder(task, "task_due_24h")
    moved = task.model_copy(update={"due_at": first_due + timedelta(days=1)})
    second = build_task_reminder(moved, "task_due_24h")

    assert first.dedupe_key != second.dedupe_key
    assert str(task.id) in first.dedupe_key


def test_reminder_text_contains_task_venue_and_moscow_deadline() -> None:
    task = make_task(
        due_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    )

    reminder = build_task_reminder(task, "task_due_2h")

    assert "Проверить остатки сиропов" in reminder.body
    assert "Оксфорд" in reminder.body
    assert "03.08.2026 12:00" in reminder.body
    assert reminder.severity == "important"


def test_reminder_worker_deployment_contract() -> None:
    migration = (
        REPO_ROOT
        / "backend"
        / "migrations"
        / "005_task_reminder_deduplication.sql"
    ).read_text(encoding="utf-8")
    compose = (
        REPO_ROOT / "deploy" / "firstvds" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    deploy = (
        REPO_ROOT / "deploy" / "firstvds" / "scripts" / "deploy.sh"
    ).read_text(encoding="utf-8")
    store = (REPO_ROOT / "backend" / "app" / "reminder_store.py").read_text(
        encoding="utf-8"
    )

    assert "dedupe_key" in migration
    assert "unique index" in migration
    assert "bar-manager-ai-reminder" in compose
    assert "app.reminder_worker" in compose
    assert "api reminder" in deploy
    assert "reminder_version" in deploy
    assert "on conflict (dedupe_key) do nothing" in store
    assert "for update of event skip locked" in store
    assert "task.status in ('new', 'planned', 'work', 'waiting')" in store
    assert "event.dedupe_key =" in store
    assert "next_attempt_at" in store
    assert "interval '5 minutes'" in store
