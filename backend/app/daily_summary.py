from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from .schemas import TaskOut

LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="MSK")
ACTIVE_STATUSES = {"new", "planned", "work", "waiting"}
HIGH_PRIORITIES = {"high", "critical"}
MAX_ITEMS_PER_SECTION = 5

VENUE_LABELS = {
    "oxford": "Оксфорд",
    "sovremennik": "Современник",
    None: "Без заведения",
}
STATUS_LABELS = {
    "new": "Новая",
    "planned": "Запланирована",
    "work": "В работе",
    "waiting": "Ожидание",
}


def daily_summary_schedule(
    now: datetime,
    *,
    hour: int = 8,
    minute: int = 0,
) -> tuple[date, datetime] | None:
    """Return the current local summary date and UTC schedule after send time."""
    if not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    if not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")

    aware_now = _as_aware(now)
    local_now = aware_now.astimezone(LOCAL_TIMEZONE)
    scheduled_local = datetime.combine(
        local_now.date(),
        time(hour=hour, minute=minute, tzinfo=LOCAL_TIMEZONE),
    )
    if local_now < scheduled_local:
        return None
    return local_now.date(), scheduled_local.astimezone(timezone.utc)


def daily_summary_dedupe_key(summary_date: date) -> str:
    return f"daily-summary:{summary_date.isoformat()}"


def build_daily_summary(
    tasks: list[TaskOut],
    *,
    now: datetime,
    heading: str = "Утренняя сводка",
) -> str:
    aware_now = _as_aware(now)
    local_now = aware_now.astimezone(LOCAL_TIMEZONE)
    local_date = local_now.date()

    active = [task for task in tasks if task.status in ACTIVE_STATUSES]
    overdue = sorted(
        [
            task
            for task in active
            if task.due_at is not None and _as_aware(task.due_at) < aware_now
        ],
        key=lambda task: _as_aware(task.due_at),
    )
    due_today = sorted(
        [
            task
            for task in active
            if task.due_at is not None
            and _as_aware(task.due_at) >= aware_now
            and _as_aware(task.due_at).astimezone(LOCAL_TIMEZONE).date() == local_date
        ],
        key=lambda task: _as_aware(task.due_at),
    )
    waiting = [task for task in active if task.status == "waiting"]
    important = [task for task in active if task.priority in HIGH_PRIORITIES]

    lines = [
        f"{heading} · {local_date.strftime('%d.%m.%Y')}",
        "",
        f"Активных задач: {len(active)}",
        f"Просрочено: {len(overdue)}",
        f"На сегодня: {len(due_today)}",
        f"В ожидании: {len(waiting)}",
        f"Высокий приоритет: {len(important)}",
    ]

    if not active:
        lines.extend(["", "Активных задач нет."])
    else:
        _append_section(lines, "Просрочено", overdue)
        _append_section(lines, "На сегодня", due_today)
        _append_section(lines, "Высокий приоритет", important)
        _append_section(lines, "В ожидании", waiting)

    lines.extend(
        [
            "",
            "Откройте /tasks для полного списка или /summary для новой сводки.",
        ]
    )
    return "\n".join(lines)


def _append_section(lines: list[str], title: str, tasks: list[TaskOut]) -> None:
    if not tasks:
        return
    lines.extend(["", f"{title}:"])
    for task in tasks[:MAX_ITEMS_PER_SECTION]:
        lines.append(_format_task_line(task))
    if len(tasks) > MAX_ITEMS_PER_SECTION:
        lines.append(f"…ещё {len(tasks) - MAX_ITEMS_PER_SECTION}")


def _format_task_line(task: TaskOut) -> str:
    venue = VENUE_LABELS.get(task.venue_code, "Без заведения")
    status = STATUS_LABELS.get(task.status, task.status)
    due = "без срока"
    if task.due_at is not None:
        due = _as_aware(task.due_at).astimezone(LOCAL_TIMEZONE).strftime("%d.%m %H:%M")
    return f"• {task.title} — {venue}, {status}, {due}"


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
