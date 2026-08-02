from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

import asyncpg

from .recurring_rules import (
    RecurrenceFrequency,
    WeekdayCode,
    next_due_at,
    schedule_rrule,
)
from .schemas import TaskPriority, VenueCode

GENERATION_HORIZON = timedelta(hours=24)
STALE_OCCURRENCE_LIMIT = timedelta(hours=24)
MAX_ADVANCES_PER_RULE = 1000
MAX_GENERATED_OCCURRENCES_PER_RULE = 32


@dataclass(frozen=True)
class RecurringRuleCreate:
    title: str
    description: str | None
    original_text: str
    venue_code: VenueCode | None
    priority: TaskPriority
    frequency: RecurrenceFrequency
    weekdays: list[WeekdayCode]
    due_time: time
    next_due_at: datetime
    source_chat_id: int


@dataclass(frozen=True)
class RecurringRuleOut:
    id: UUID
    venue_code: VenueCode | None
    venue_name: str | None
    title: str
    description: str | None
    original_text: str | None
    frequency: RecurrenceFrequency
    weekdays: list[WeekdayCode]
    due_time: time
    priority: TaskPriority
    enabled: bool
    next_due_at: datetime | None
    last_generated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RecurringRuleNotFoundError(LookupError):
    pass


class RecurringRuleStore:
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

    async def create_rule(self, payload: RecurringRuleCreate) -> RecurringRuleOut:
        pool = await self._get_pool()
        venue_id = await _resolve_venue_id(pool, payload.venue_code)
        row = await pool.fetchrow(
            """
            insert into recurring_rules (
                venue_id,
                title,
                description,
                schedule_rrule,
                default_due_time,
                priority,
                enabled,
                frequency,
                weekdays,
                next_due_at,
                source_chat_id,
                original_text
            ) values ($1,$2,$3,$4,$5,$6,true,$7,$8,$9,$10,$11)
            returning id
            """,
            venue_id,
            payload.title,
            payload.description,
            schedule_rrule(payload.frequency, payload.weekdays),
            payload.due_time,
            payload.priority,
            payload.frequency,
            payload.weekdays,
            _as_aware(payload.next_due_at),
            payload.source_chat_id,
            payload.original_text,
        )
        return await self.get_rule(row["id"])

    async def get_rule(self, rule_id: UUID) -> RecurringRuleOut:
        pool = await self._get_pool()
        row = await pool.fetchrow(_RULE_SELECT + " where rule.id = $1", rule_id)
        if row is None:
            raise RecurringRuleNotFoundError(str(rule_id))
        return _rule_from_record(row)

    async def list_rules(self, *, enabled_only: bool = True) -> list[RecurringRuleOut]:
        pool = await self._get_pool()
        query = _RULE_SELECT
        if enabled_only:
            query += " where rule.enabled = true"
        query += " order by rule.next_due_at nulls last, rule.created_at"
        rows = await pool.fetch(query)
        return [_rule_from_record(row) for row in rows]

    async def disable_rule(self, rule_id: UUID) -> RecurringRuleOut:
        pool = await self._get_pool()
        result = await pool.execute(
            "update recurring_rules set enabled = false where id = $1 and enabled = true",
            rule_id,
        )
        if result.endswith(" 0"):
            raise RecurringRuleNotFoundError(str(rule_id))
        return await self.get_rule(rule_id)

    async def generate_due_tasks(self, *, now: datetime) -> int:
        pool = await self._get_pool()
        aware_now = _as_aware(now)
        horizon = aware_now + GENERATION_HORIZON
        cutoff = aware_now - STALE_OCCURRENCE_LIMIT
        generated = 0

        async with pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """
                    select
                        rule.id,
                        rule.venue_id,
                        rule.title,
                        rule.description,
                        rule.original_text,
                        rule.priority,
                        rule.frequency,
                        rule.weekdays,
                        rule.default_due_time,
                        rule.next_due_at
                    from recurring_rules as rule
                    where rule.enabled = true
                      and rule.next_due_at is not null
                      and rule.next_due_at <= $1
                    order by rule.next_due_at
                    for update skip locked
                    """,
                    horizon,
                )

                for row in rows:
                    frequency = row["frequency"]
                    weekdays = list(row["weekdays"] or [])
                    due_time = row["default_due_time"]
                    current_due = _as_aware(row["next_due_at"])

                    advances = 0
                    while current_due < cutoff:
                        advances += 1
                        if advances > MAX_ADVANCES_PER_RULE:
                            raise RuntimeError("Recurring rule could not catch up safely")
                        current_due = next_due_at(
                            current_due,
                            frequency=frequency,
                            weekdays=weekdays,
                            due_time=due_time,
                        )

                    occurrences = 0
                    while current_due <= horizon:
                        occurrences += 1
                        if occurrences > MAX_GENERATED_OCCURRENCES_PER_RULE:
                            raise RuntimeError("Recurring rule generated too many occurrences")

                        source_reference = (
                            f"recurring:{row['id']}:"
                            f"{int(current_due.timestamp())}"
                        )
                        task = await connection.fetchrow(
                            """
                            insert into tasks (
                                venue_id,
                                title,
                                description,
                                original_text,
                                status,
                                priority,
                                due_at,
                                source_type,
                                source_reference,
                                requires_confirmation
                            ) values ($1,$2,$3,$4,'new',$5,$6,'recurring',$7,false)
                            on conflict do nothing
                            returning id
                            """,
                            row["venue_id"],
                            row["title"],
                            row["description"],
                            row["original_text"],
                            row["priority"],
                            current_due,
                            source_reference,
                        )
                        if task is not None:
                            await connection.execute(
                                """
                                insert into task_events (
                                    task_id, event_type, actor_type, payload
                                ) values (
                                    $1,
                                    'generated_from_recurring_rule',
                                    'system',
                                    jsonb_build_object(
                                        'recurring_rule_id', $2::uuid::text,
                                        'due_at', $3::timestamptz
                                    )
                                )
                                """,
                                task["id"],
                                row["id"],
                                current_due,
                            )
                            generated += 1

                        current_due = next_due_at(
                            current_due,
                            frequency=frequency,
                            weekdays=weekdays,
                            due_time=due_time,
                        )

                    await connection.execute(
                        """
                        update recurring_rules
                        set next_due_at = $2,
                            last_generated_at = $3
                        where id = $1
                        """,
                        row["id"],
                        current_due,
                        aware_now,
                    )

        return generated


_RULE_SELECT = """
select
    rule.id,
    venue.code as venue_code,
    venue.name as venue_name,
    rule.title,
    rule.description,
    rule.original_text,
    rule.frequency,
    rule.weekdays,
    rule.default_due_time as due_time,
    rule.priority,
    rule.enabled,
    rule.next_due_at,
    rule.last_generated_at,
    rule.created_at,
    rule.updated_at
from recurring_rules as rule
left join venues as venue on venue.id = rule.venue_id
"""


def _rule_from_record(row: asyncpg.Record) -> RecurringRuleOut:
    values: dict[str, Any] = dict(row)
    values["weekdays"] = list(values.get("weekdays") or [])
    return RecurringRuleOut(**values)


async def _resolve_venue_id(
    pool: asyncpg.Pool,
    venue_code: VenueCode | None,
) -> UUID | None:
    if venue_code is None:
        return None
    venue_id = await pool.fetchval(
        "select id from venues where code = $1",
        venue_code,
    )
    if venue_id is None:
        raise ValueError(f"Unknown venue code: {venue_code}")
    return venue_id


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_stores: dict[str, RecurringRuleStore] = {}


def get_recurring_rule_store(
    database_url: str | None,
) -> RecurringRuleStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = RecurringRuleStore(database_url)
    return _stores[database_url]
