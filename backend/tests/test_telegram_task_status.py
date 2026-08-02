from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskOut
from app.telegram_task_commands import (
    format_status_confirmation,
    format_task_list,
    parse_task_number,
    select_task_by_number,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _task(title: str, status: str = "new") -> TaskOut:
    now = datetime.now(timezone.utc)
    return TaskOut(
        id=uuid4(),
        title=title,
        status=status,
        priority="normal",
        source_type="telegram",
        requires_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def test_parse_task_number_accepts_only_positive_integers() -> None:
    assert parse_task_number("2") == 2
    assert parse_task_number("0") is None
    assert parse_task_number("-1") is None
    assert parse_task_number("one") is None


def test_select_task_by_number_uses_only_active_tasks() -> None:
    first = _task("Первая")
    completed = _task("Завершённая", status="done")
    second = _task("Вторая", status="waiting")

    assert select_task_by_number([first, completed, second], "1") == first
    assert select_task_by_number([first, completed, second], "2") == second
    assert select_task_by_number([first, completed, second], "3") is None


def test_task_list_explains_status_commands() -> None:
    rendered = format_task_list([_task("Проверить остатки")])

    assert "/work N" in rendered
    assert "/wait N" in rendered
    assert "/done N" in rendered
    assert "/cancel_task N" in rendered


def test_done_and_cancel_require_confirmation() -> None:
    task = _task("Проверить остатки")

    done = format_status_confirmation(task, "done")
    cancelled = format_status_confirmation(task, "cancelled")

    assert "Завершена" in done
    assert "Отменена" in cancelled
    assert "/confirm" in done
    assert "/cancel" in done


def test_pending_action_migration_allows_status_updates() -> None:
    migration = (
        REPO_ROOT
        / "backend"
        / "migrations"
        / "004_telegram_task_status_actions.sql"
    ).read_text(encoding="utf-8")
    store_module = (
        REPO_ROOT / "backend" / "app" / "pending_action_store.py"
    ).read_text(encoding="utf-8")

    assert "update_task_status" in migration
    assert "save_status_change" in store_module
    assert "get_pending_action" in store_module
