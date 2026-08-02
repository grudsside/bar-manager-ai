from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from .schemas import TaskOut
from .task_reminders import TaskReminderSpec

TASK_REMINDER_TYPES = (
    "task_due_24h",
    "task_due_2h",
    "task_overdue",
)


@dataclass(frozen=True)
class ClaimedReminder:
    id: UUID
    task_id: UUID
    title: str
    body: str
    severity: str


class TaskReminderStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=3,
                command_timeout=30,
                statement_cache_size=0,
            )
        return self._pool

    async def ensure_event(self, task: TaskOut, spec: TaskReminderSpec) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            insert into notification_events (
                task_id,
                notification_type,
                title,
                body,
                severity,
                scheduled_for,
                dedupe_key
            ) values ($1, $2, $3, $4, $5, $6, $7)
            on conflict (dedupe_key) do nothing
            """,
            task.id,
            spec.kind,
            spec.title,
            spec.body,
            spec.severity,
            spec.scheduled_for,
            spec.dedupe_key,
        )

    async def claim_next(self) -> ClaimedReminder | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            with candidate as (
                select event.id
                from notification_events as event
                join tasks as task on task.id = event.task_id
                where event.sent_at is null
                  and event.task_id is not null
                  and event.notification_type = any($1::text[])
                  and event.scheduled_for <= now()
                  and task.status in ('new', 'planned', 'work', 'waiting')
                  and task.due_at is not null
                  and event.dedupe_key = (
                    'task:' || task.id::text || ':due:' ||
                    floor(extract(epoch from task.due_at))::bigint::text || ':' ||
                    event.notification_type
                  )
                  and (
                    nullif(event.delivery_results ->> 'next_attempt_at', '') is null
                    or nullif(
                        event.delivery_results ->> 'next_attempt_at', ''
                    )::timestamptz <= now()
                  )
                  and (
                    event.delivery_results ->> 'status' is distinct from 'sending'
                    or nullif(
                        event.delivery_results ->> 'claimed_at', ''
                    )::timestamptz < now() - interval '10 minutes'
                  )
                order by event.scheduled_for, event.created_at
                for update of event skip locked
                limit 1
            )
            update notification_events as event
            set delivery_results = jsonb_build_object(
                'status', 'sending',
                'claimed_at', now()
            )
            from candidate
            where event.id = candidate.id
            returning event.id, event.task_id, event.title, event.body, event.severity
            """,
            list(TASK_REMINDER_TYPES),
        )
        if row is None:
            return None
        return ClaimedReminder(**dict(row))

    async def mark_sent(self, reminder_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update notification_events
            set sent_at = now(),
                delivery_results = jsonb_build_object(
                    'status', 'sent',
                    'sent_at', now()
                )
            where id = $1
            """,
            reminder_id,
        )

    async def mark_failed(self, reminder_id: UUID, error_type: str) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update notification_events
            set delivery_results = jsonb_build_object(
                'status', 'failed',
                'error_type', $2,
                'failed_at', now(),
                'next_attempt_at', now() + interval '5 minutes'
            )
            where id = $1 and sent_at is null
            """,
            reminder_id,
            error_type,
        )


_stores: dict[str, TaskReminderStore] = {}


def get_reminder_store(database_url: str | None) -> TaskReminderStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = TaskReminderStore(database_url)
    return _stores[database_url]
