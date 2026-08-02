from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from .schemas import TaskOut

ReminderKind = Literal["task_due_24h", "task_due_2h", "task_overdue"]

ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")


@dataclass(frozen=True)
class TaskReminderSpec:
    kind: ReminderKind
    dedupe_key: str
    title: str
    body: str
    severity: str
    scheduled_for: datetime


def select_reminder_kind(
    task: TaskOut,
    *,
    now: datetime | None = None,
) -> ReminderKind | None:
    if task.status not in ACTIVE_STATUSES or task.due_at is None:
        return None

    current = _as_utc(now or datetime.now(timezone.utc))
    due_at = _as_utc(task.due_at)
    remaining = due_at - current

    if remaining <= timedelta(0):
        return "task_overdue"
    if remaining <= timedelta(hours=2):
        return "task_due_2h"
    if remaining <= timedelta(hours=24):
        return "task_due_24h"
    return None


def build_task_reminder(
    task: TaskOut,
    kind: ReminderKind,
) -> TaskReminderSpec:
    if task.due_at is None:
        raise ValueError("A task reminder requires due_at")

    due_at = _as_utc(task.due_at)
    venue = task.venue_name or {
        "oxford": "Оксфорд",
        "sovremennik": "Современник",
    }.get(task.venue_code, "Заведение не указано")
    due_text = due_at.astimezone(LOCAL_TIMEZONE).strftime("%d.%m.%Y %H:%M")

    if kind == "task_due_24h":
        title = "До срока задачи меньше 24 часов"
        body = (
            "⏰ До срока осталось меньше 24 часов.\n"
            f"Задача: {task.title}\n"
            f"{venue} · срок: {due_text}\n\n"
            "Откройте /tasks, чтобы изменить статус."
        )
        severity = "normal"
        scheduled_for = due_at - timedelta(hours=24)
    elif kind == "task_due_2h":
        title = "До срока задачи меньше 2 часов"
        body = (
            "⚠️ До срока осталось меньше 2 часов.\n"
            f"Задача: {task.title}\n"
            f"{venue} · срок: {due_text}\n\n"
            "Откройте /tasks, чтобы изменить статус."
        )
        severity = "important"
        scheduled_for = due_at - timedelta(hours=2)
    elif kind == "task_overdue":
        title = "Задача просрочена"
        body = (
            "🚨 Задача просрочена.\n"
            f"Задача: {task.title}\n"
            f"{venue} · срок был: {due_text}\n\n"
            "Откройте /tasks и обновите статус задачи."
        )
        severity = "critical"
        scheduled_for = due_at
    else:
        raise ValueError(f"Unsupported reminder kind: {kind}")

    due_epoch = int(due_at.timestamp())
    return TaskReminderSpec(
        kind=kind,
        dedupe_key=f"task:{task.id}:due:{due_epoch}:{kind}",
        title=title,
        body=body,
        severity=severity,
        scheduled_for=scheduled_for,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
