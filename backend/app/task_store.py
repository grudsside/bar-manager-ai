from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from .schemas import TaskCreate, TaskOut, TaskUpdate


class TaskNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class TaskEventOut:
    id: UUID
    event_type: str
    actor_type: str
    payload: dict[str, Any]
    created_at: datetime


class TaskStore(ABC):
    @abstractmethod
    async def list_tasks(self, *, status: str | None = None) -> list[TaskOut]:
        raise NotImplementedError

    @abstractmethod
    async def get_task(self, task_id: UUID) -> TaskOut:
        raise NotImplementedError

    @abstractmethod
    async def create_task(self, payload: TaskCreate) -> TaskOut:
        raise NotImplementedError

    @abstractmethod
    async def update_task(self, task_id: UUID, payload: TaskUpdate) -> TaskOut:
        raise NotImplementedError

    @abstractmethod
    async def list_task_events(
        self,
        task_id: UUID,
        *,
        limit: int = 10,
    ) -> list[TaskEventOut]:
        raise NotImplementedError


class InMemoryTaskStore(TaskStore):
    def __init__(self) -> None:
        self._tasks: dict[UUID, TaskOut] = {}
        self._events: dict[UUID, list[TaskEventOut]] = {}

    async def list_tasks(self, *, status: str | None = None) -> list[TaskOut]:
        rows = list(self._tasks.values())
        if status:
            rows = [row for row in rows if row.status == status]
        return sorted(rows, key=lambda row: (row.due_at is None, row.due_at or row.created_at))

    async def get_task(self, task_id: UUID) -> TaskOut:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(str(task_id)) from exc

    async def create_task(self, payload: TaskCreate) -> TaskOut:
        now = datetime.now(timezone.utc)
        row = TaskOut(
            id=uuid4(),
            venue_code=payload.venue_code,
            venue_name=_venue_name(payload.venue_code),
            title=payload.title,
            description=payload.description,
            original_text=payload.original_text,
            status=payload.status,
            priority=payload.priority,
            due_at=payload.due_at,
            waiting_until=payload.waiting_until,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            requires_confirmation=payload.requires_confirmation,
            completed_at=now if payload.status == "done" else None,
            created_at=now,
            updated_at=now,
        )
        self._tasks[row.id] = row
        self._events.setdefault(row.id, []).append(
            TaskEventOut(
                id=uuid4(),
                event_type="created",
                actor_type="owner",
                payload=payload.model_dump(mode="json"),
                created_at=now,
            )
        )
        return row

    async def update_task(self, task_id: UUID, payload: TaskUpdate) -> TaskOut:
        current = await self.get_task(task_id)
        changes = payload.model_dump(exclude_unset=True)
        if "venue_code" in changes:
            changes["venue_name"] = _venue_name(changes["venue_code"])
        if changes.get("status") == "done" and current.completed_at is None:
            changes["completed_at"] = datetime.now(timezone.utc)
        elif "status" in changes and changes["status"] != "done":
            changes["completed_at"] = None
        now = datetime.now(timezone.utc)
        changes["updated_at"] = now
        updated = current.model_copy(update=changes)
        self._tasks[task_id] = updated
        self._events.setdefault(task_id, []).append(
            TaskEventOut(
                id=uuid4(),
                event_type="updated",
                actor_type="owner",
                payload=payload.model_dump(exclude_unset=True, mode="json"),
                created_at=now,
            )
        )
        return updated

    async def list_task_events(
        self,
        task_id: UUID,
        *,
        limit: int = 10,
    ) -> list[TaskEventOut]:
        await self.get_task(task_id)
        safe_limit = max(1, min(limit, 50))
        rows = sorted(
            self._events.get(task_id, []),
            key=lambda event: event.created_at,
            reverse=True,
        )
        return rows[:safe_limit]


class PostgresTaskStore(TaskStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        return self._pool

    async def list_tasks(self, *, status: str | None = None) -> list[TaskOut]:
        pool = await self._get_pool()
        query = _TASK_SELECT
        values: list[Any] = []
        if status:
            query += " where t.status = $1"
            values.append(status)
        query += " order by t.due_at nulls last, t.created_at desc"
        rows = await pool.fetch(query, *values)
        return [_task_from_record(row) for row in rows]

    async def get_task(self, task_id: UUID) -> TaskOut:
        pool = await self._get_pool()
        row = await pool.fetchrow(_TASK_SELECT + " where t.id = $1", task_id)
        if row is None:
            raise TaskNotFoundError(str(task_id))
        return _task_from_record(row)

    async def create_task(self, payload: TaskCreate) -> TaskOut:
        pool = await self._get_pool()
        venue_id = await _resolve_venue_id(pool, payload.venue_code)
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    insert into tasks (
                        venue_id, title, description, original_text, status, priority,
                        due_at, waiting_until, source_type, source_reference,
                        requires_confirmation, completed_at
                    ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    returning id
                    """,
                    venue_id,
                    payload.title,
                    payload.description,
                    payload.original_text,
                    payload.status,
                    payload.priority,
                    payload.due_at,
                    payload.waiting_until,
                    payload.source_type,
                    payload.source_reference,
                    payload.requires_confirmation,
                    datetime.now(timezone.utc) if payload.status == "done" else None,
                )
                task_id = row["id"]
                await connection.execute(
                    """
                    insert into task_events (task_id, event_type, actor_type, payload)
                    values ($1, 'created', 'owner', $2::jsonb)
                    """,
                    task_id,
                    json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                )
        return await self.get_task(task_id)

    async def update_task(self, task_id: UUID, payload: TaskUpdate) -> TaskOut:
        current = await self.get_task(task_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return current

        pool = await self._get_pool()
        if "venue_code" in changes:
            changes["venue_id"] = await _resolve_venue_id(pool, changes.pop("venue_code"))
        if changes.get("status") == "done" and current.completed_at is None:
            changes["completed_at"] = datetime.now(timezone.utc)
        elif "status" in changes and changes["status"] != "done":
            changes["completed_at"] = None

        allowed = {
            "venue_id", "title", "description", "original_text", "status", "priority",
            "due_at", "waiting_until", "source_type", "source_reference",
            "requires_confirmation", "completed_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported task fields: {sorted(unknown)}")

        assignments: list[str] = []
        values: list[Any] = []
        for index, (field, value) in enumerate(changes.items(), start=1):
            assignments.append(f"{field} = ${index}")
            values.append(value)
        values.append(task_id)

        event_payload = payload.model_dump(exclude_unset=True, mode="json")
        async with pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    f"update tasks set {', '.join(assignments)} where id = ${len(values)}",
                    *values,
                )
                if result.endswith(" 0"):
                    raise TaskNotFoundError(str(task_id))
                await connection.execute(
                    """
                    insert into task_events (task_id, event_type, actor_type, payload)
                    values ($1, 'updated', 'owner', $2::jsonb)
                    """,
                    task_id,
                    json.dumps(event_payload, ensure_ascii=False),
                )
        return await self.get_task(task_id)

    async def list_task_events(
        self,
        task_id: UUID,
        *,
        limit: int = 10,
    ) -> list[TaskEventOut]:
        await self.get_task(task_id)
        safe_limit = max(1, min(limit, 50))
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            select id, event_type, actor_type, payload, created_at
            from task_events
            where task_id = $1
            order by created_at desc, id desc
            limit $2
            """,
            task_id,
            safe_limit,
        )
        return [_task_event_from_record(row) for row in rows]


_TASK_SELECT = """
select
    t.id,
    v.code as venue_code,
    v.name as venue_name,
    t.title,
    t.description,
    t.original_text,
    t.status,
    t.priority,
    t.due_at,
    t.waiting_until,
    t.source_type,
    t.source_reference,
    t.requires_confirmation,
    t.completed_at,
    t.created_at,
    t.updated_at
from tasks t
left join venues v on v.id = t.venue_id
"""


def _task_from_record(row: asyncpg.Record) -> TaskOut:
    return TaskOut(**dict(row))


def _task_event_from_record(row: asyncpg.Record) -> TaskEventOut:
    values = dict(row)
    payload = values.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        payload = {}
    values["payload"] = payload
    return TaskEventOut(**values)


async def _resolve_venue_id(pool: asyncpg.Pool, venue_code: str | None) -> UUID | None:
    if venue_code is None:
        return None
    venue_id = await pool.fetchval("select id from venues where code = $1", venue_code)
    if venue_id is None:
        raise ValueError(f"Unknown venue code: {venue_code}")
    return venue_id


def _venue_name(code: str | None) -> str | None:
    return {"oxford": "Оксфорд", "sovremennik": "Современник"}.get(code)


_memory_store = InMemoryTaskStore()
_postgres_stores: dict[str, PostgresTaskStore] = {}


def get_task_store(database_url: str | None) -> TaskStore:
    if not database_url:
        return _memory_store
    if database_url not in _postgres_stores:
        _postgres_stores[database_url] = PostgresTaskStore(database_url)
    return _postgres_stores[database_url]
