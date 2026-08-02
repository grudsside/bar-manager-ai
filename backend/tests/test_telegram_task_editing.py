from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.task_edits import ExtractedTaskEdit, task_update_from_edit
from app.telegram_task_commands import parse_task_edit_argument

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_task_edit_argument_requires_number_and_instruction() -> None:
    assert parse_task_edit_argument("2 перенеси на завтра 12:00") == (
        2,
        "перенеси на завтра 12:00",
    )
    assert parse_task_edit_argument("2") == (2, "")
    assert parse_task_edit_argument("перенеси срок") == (None, "срок")


def test_task_edit_builds_only_explicit_changes() -> None:
    draft = ExtractedTaskEdit(
        priority="high",
        due_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
    )

    update = task_update_from_edit(draft)

    assert update.model_dump(exclude_unset=True) == {
        "priority": "high",
        "due_at": datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
    }


def test_task_edit_can_explicitly_clear_optional_fields() -> None:
    draft = ExtractedTaskEdit(
        clear_description=True,
        clear_venue=True,
        clear_due_at=True,
    )

    update = task_update_from_edit(draft)

    assert update.model_dump(exclude_unset=True) == {
        "description": None,
        "venue_code": None,
        "due_at": None,
    }


def test_task_edit_rejects_value_and_clear_flag_together() -> None:
    with pytest.raises(ValidationError):
        ExtractedTaskEdit(venue_code="oxford", clear_venue=True)


def test_task_edit_pending_action_and_migration_contract() -> None:
    migration = (
        REPO_ROOT
        / "backend"
        / "migrations"
        / "007_telegram_task_field_edits.sql"
    ).read_text(encoding="utf-8")
    pending_store = (
        REPO_ROOT / "backend" / "app" / "pending_action_store.py"
    ).read_text(encoding="utf-8")
    task_commands = (
        REPO_ROOT / "backend" / "app" / "telegram_task_commands.py"
    ).read_text(encoding="utf-8")

    assert "update_task_fields" in migration
    assert '"update_task_fields"' in pending_store
    assert '"/edit"' in task_commands
    assert 'pending.action_type == "update_task_fields"' in task_commands
    assert "EDITABLE_TASK_FIELDS" in task_commands
