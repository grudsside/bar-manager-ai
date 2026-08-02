from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class PendingTaskAction:
    id: UUID
    payload: dict[str, Any]
    source_message_id: int | None


class TelegramPendingActionStore:
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

    async def save_task_draft(
        self,
        chat_id: int,
        payload: dict[str, Any],
        *,
        source_message_id: int | None,
    ) -> UUID:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    update telegram_pending_actions
                    set status = 'cancelled', resolved_at = now()
                    where chat_id = $1
                      and action_type = 'create_task'
                      and status = 'pending'
                    """,
                    chat_id,
                )
                row = await connection.fetchrow(
                    """
                    insert into telegram_pending_actions (
                        chat_id, action_type, payload, source_message_id
                    ) values ($1, 'create_task', $2::jsonb, $3)
                    returning id
                    """,
                    chat_id,
                    json.dumps(payload, ensure_ascii=False),
                    source_message_id,
                )
        return row["id"]

    async def get_pending_task(self, chat_id: int) -> PendingTaskAction | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            select id, payload, source_message_id
            from telegram_pending_actions
            where chat_id = $1
              and action_type = 'create_task'
              and status = 'pending'
              and expires_at > now()
            order by created_at desc
            limit 1
            """,
            chat_id,
        )
        if row is None:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid pending task payload")
        return PendingTaskAction(
            id=row["id"],
            payload=payload,
            source_message_id=row["source_message_id"],
        )

    async def resolve(self, action_id: UUID, status: str) -> None:
        if status not in {"confirmed", "cancelled", "expired"}:
            raise ValueError("Unsupported pending action status")
        pool = await self._get_pool()
        await pool.execute(
            """
            update telegram_pending_actions
            set status = $2, resolved_at = now()
            where id = $1 and status = 'pending'
            """,
            action_id,
            status,
        )


_stores: dict[str, TelegramPendingActionStore] = {}


def get_pending_action_store(
    database_url: str | None,
) -> TelegramPendingActionStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = TelegramPendingActionStore(database_url)
    return _stores[database_url]
