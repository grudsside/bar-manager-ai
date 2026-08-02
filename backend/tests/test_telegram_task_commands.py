from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskCreate, TaskOut
from app.telegram_task_commands import (
    format_task_list,
    format_task_preview,
    parse_command,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_parse_command_supports_bot_suffix_and_argument() -> None:
    command, argument = parse_command(
        "/task@gridsside_assistant_bot Оксфорд — проверить сиропы"
    )
    assert command == "/task"
    assert argument == "Оксфорд — проверить сиропы"


def test_task_preview_requires_explicit_confirmation() -> None:
    payload = TaskCreate(
        title="Проверить остатки сиропов",
        venue_code="oxford",
        priority="high",
        due_at=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
        source_type="telegram",
    )

    preview = format_task_preview(payload)

    assert "Проверить остатки сиропов" in preview
    assert "Оксфорд" in preview
    assert "/confirm" in preview
    assert "/cancel" in preview


def test_task_list_hides_completed_tasks() -> None:
    now = datetime.now(timezone.utc)
    active = TaskOut(
        id=uuid4(),
        title="Активная задача",
        status="work",
        priority="normal",
        source_type="telegram",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )
    completed = TaskOut(
        id=uuid4(),
        title="Завершённая задача",
        status="done",
        priority="normal",
        source_type="telegram",
        requires_confirmation=False,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )

    rendered = format_task_list([active, completed])

    assert "Активная задача" in rendered
    assert "Завершённая задача" not in rendered


def test_pending_action_migration_and_command_contract() -> None:
    migration = (
        REPO_ROOT / "backend" / "migrations" / "003_telegram_pending_actions.sql"
    ).read_text(encoding="utf-8")
    bot_module = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    draft_module = (REPO_ROOT / "backend" / "app" / "task_drafts.py").read_text(
        encoding="utf-8"
    )

    assert "telegram_pending_actions" in migration
    assert "where status = 'pending'" in migration
    assert "maybe_handle_task_command" in bot_module
    assert '"output_type": ExtractedTaskDraft' in draft_module
