from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import TaskOut
from app.telegram_task_archive_commands import (
    archived_tasks,
    format_archive_list,
    select_archive_task,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_task(
    title: str,
    *,
    status: str,
    closed_at: datetime,
    venue_code: str = "oxford",
) -> TaskOut:
    created_at = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
    return TaskOut(
        id=uuid4(),
        venue_code=venue_code,
        venue_name="Оксфорд" if venue_code == "oxford" else "Современник",
        title=title,
        status=status,
        priority="normal",
        source_type="telegram",
        requires_confirmation=False,
        completed_at=closed_at if status == "done" else None,
        created_at=created_at,
        updated_at=closed_at,
    )


def test_archive_is_sorted_by_latest_closed_task() -> None:
    older_done = make_task(
        "Старая завершённая",
        status="done",
        closed_at=datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc),
    )
    newest_cancelled = make_task(
        "Новая отменённая",
        status="cancelled",
        closed_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
    )
    active = make_task(
        "Активная",
        status="work",
        closed_at=datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc),
    )

    archive = archived_tasks([older_done, active, newest_cancelled])

    assert [task.title for task in archive] == [
        "Новая отменённая",
        "Старая завершённая",
    ]
    assert select_archive_task([older_done, newest_cancelled], 1) == newest_cancelled


def test_filtered_archive_keeps_global_archive_numbers() -> None:
    newest_cancelled = make_task(
        "Отменённая",
        status="cancelled",
        closed_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    second_done = make_task(
        "Завершённая Оксфорд",
        status="done",
        closed_at=datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc),
    )
    third_done = make_task(
        "Завершённая Современник",
        status="done",
        closed_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        venue_code="sovremennik",
    )

    rendered = format_archive_list(
        [third_done, newest_cancelled, second_done],
        "done",
    )

    assert "2. Завершённая Оксфорд" in rendered
    assert "3. Завершённая Современник" in rendered
    assert "1. Завершённая Оксфорд" not in rendered
    assert "Номера относятся к общему архиву" in rendered


def test_archive_venue_filter_and_moscow_time() -> None:
    oxford = make_task(
        "Оксфорд",
        status="done",
        closed_at=datetime(2026, 8, 2, 17, 0, tzinfo=timezone.utc),
    )
    sovremennik = make_task(
        "Современник",
        status="done",
        closed_at=datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc),
        venue_code="sovremennik",
    )

    rendered = format_archive_list([oxford, sovremennik], "oxford")

    assert "1. Оксфорд" in rendered
    assert "02.08.2026 20:00" in rendered
    assert "2. Современник" not in rendered


def test_archive_routing_contract() -> None:
    history = (
        REPO_ROOT / "backend" / "app" / "telegram_task_history_commands.py"
    ).read_text(encoding="utf-8")
    archive = (
        REPO_ROOT / "backend" / "app" / "telegram_task_archive_commands.py"
    ).read_text(encoding="utf-8")

    assert "ARCHIVE_COMMANDS" in history
    assert "maybe_handle_task_archive_command" in history
    assert 'ARCHIVE_LIST_COMMANDS = {"/archive", "/completed", "/closed"}' in archive
    assert 'ARCHIVE_INFO_COMMANDS = {"/archive_info", "/closed_info"}' in archive
    assert "format_task_card(task, events)" in archive
