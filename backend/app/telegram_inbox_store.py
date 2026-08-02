from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

from .schemas import (
    TelegramChatOut,
    TelegramInboxItemOut,
    TelegramInboxTaskCreate,
)


class TelegramInboxNotFoundError(LookupError):
    pass


class TelegramInboxAlreadyProcessedError(RuntimeError):
    pass


class TelegramChatNotFoundError(LookupError):
    pass


class TelegramInboxStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=4,
                command_timeout=30,
                statement_cache_size=0,
            )
        return self._pool

    async def list_chats(self) -> list[TelegramChatOut]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            select
                chat.chat_id,
                chat.title,
                chat.allowed,
                chat.purpose,
                venue.code as venue_code,
                venue.name as venue_name,
                chat.created_at,
                chat.updated_at
            from telegram_chats as chat
            left join venues as venue on venue.id = chat.venue_id
            order by chat.allowed desc, chat.updated_at desc, chat.title
            """
        )
        return [TelegramChatOut(**dict(row)) for row in rows]

    async def update_chat(
        self,
        chat_id: int,
        changes: dict[str, Any],
    ) -> TelegramChatOut:
        if not changes:
            return await self.get_chat(chat_id)
        unsupported = set(changes) - {"allowed", "purpose", "venue_code"}
        if unsupported:
            raise ValueError("Unsupported Telegram chat fields")

        pool = await self._get_pool()
        venue_id: UUID | None | object = _UNSET
        if "venue_code" in changes:
            venue_id = await _resolve_venue_id(pool, changes.get("venue_code"))

        current = await self.get_chat(chat_id)
        allowed = changes.get("allowed", current.allowed)
        purpose = changes.get("purpose", current.purpose)
        if purpose is not None:
            purpose = " ".join(str(purpose).strip().split()) or None
        if venue_id is _UNSET:
            venue_id = await _resolve_venue_id(pool, current.venue_code)

        result = await pool.execute(
            """
            update telegram_chats
            set allowed = $2,
                purpose = $3,
                venue_id = $4
            where chat_id = $1
            """,
            chat_id,
            bool(allowed),
            purpose,
            venue_id,
        )
        if result.endswith(" 0"):
            raise TelegramChatNotFoundError(str(chat_id))
        return await self.get_chat(chat_id)

    async def get_chat(self, chat_id: int) -> TelegramChatOut:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            select
                chat.chat_id,
                chat.title,
                chat.allowed,
                chat.purpose,
                venue.code as venue_code,
                venue.name as venue_name,
                chat.created_at,
                chat.updated_at
            from telegram_chats as chat
            left join venues as venue on venue.id = chat.venue_id
            where chat.chat_id = $1
            """,
            chat_id,
        )
        if row is None:
            raise TelegramChatNotFoundError(str(chat_id))
        return TelegramChatOut(**dict(row))

    async def list_inbox(
        self,
        *,
        inbox_status: str | None = None,
        limit: int = 100,
    ) -> list[TelegramInboxItemOut]:
        pool = await self._get_pool()
        safe_limit = max(1, min(limit, 250))
        query = _INBOX_SELECT + " where message.direction = 'incoming'"
        arguments: list[Any] = []
        if inbox_status:
            query += " and message.inbox_status = $1"
            arguments.append(inbox_status)
        else:
            query += " and message.inbox_status <> 'ignored'"
        query += (
            " order by message.message_date desc nulls last, "
            "message.created_at desc limit $" + str(len(arguments) + 1)
        )
        arguments.append(safe_limit)
        rows = await pool.fetch(query, *arguments)
        return [_inbox_from_record(row) for row in rows]

    async def get_inbox(self, message_id: UUID) -> TelegramInboxItemOut:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            _INBOX_SELECT + " where message.id = $1",
            message_id,
        )
        if row is None:
            raise TelegramInboxNotFoundError(str(message_id))
        return _inbox_from_record(row)

    async def update_inbox_status(
        self,
        message_id: UUID,
        inbox_status: str,
    ) -> TelegramInboxItemOut:
        if inbox_status not in {"new", "review", "dismissed"}:
            raise ValueError("Unsupported inbox status change")
        pool = await self._get_pool()
        result = await pool.execute(
            """
            update telegram_messages
            set inbox_status = $2,
                reviewed_at = case
                    when $2 in ('review', 'dismissed') then now()
                    else null
                end
            where id = $1
              and direction = 'incoming'
              and inbox_status <> 'confirmed'
            """,
            message_id,
            inbox_status,
        )
        if result.endswith(" 0"):
            raise TelegramInboxNotFoundError(str(message_id))
        return await self.get_inbox(message_id)

    async def create_task_from_inbox(
        self,
        message_id: UUID,
        payload: TelegramInboxTaskCreate,
    ) -> UUID:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                source = await connection.fetchrow(
                    """
                    select
                        message.id,
                        message.chat_id,
                        message.message_id,
                        message.message_text,
                        message.inbox_status,
                        chat.venue_id as chat_venue_id
                    from telegram_messages as message
                    join telegram_chats as chat on chat.chat_id = message.chat_id
                    where message.id = $1
                      and message.direction = 'incoming'
                    for update
                    """,
                    message_id,
                )
                if source is None:
                    raise TelegramInboxNotFoundError(str(message_id))
                if source["inbox_status"] in {"confirmed", "dismissed", "ignored"}:
                    raise TelegramInboxAlreadyProcessedError(str(message_id))

                venue_id = source["chat_venue_id"]
                if payload.venue_code is not None:
                    venue_id = await connection.fetchval(
                        "select id from venues where code = $1",
                        payload.venue_code,
                    )
                    if venue_id is None:
                        raise ValueError("Unknown venue code")

                source_reference = (
                    f"telegram:{source['chat_id']}:{source['message_id']}"
                )
                task_id = await connection.fetchval(
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
                    ) values (
                        $1, $2, $3, $4, 'new', $5, $6,
                        'telegram', $7, false
                    )
                    returning id
                    """,
                    venue_id,
                    payload.title.strip(),
                    payload.description,
                    source["message_text"],
                    payload.priority,
                    payload.due_at,
                    source_reference,
                )
                await connection.execute(
                    """
                    insert into task_events (
                        task_id, event_type, actor_type, payload
                    ) values (
                        $1,
                        'created_from_telegram_inbox',
                        'owner',
                        jsonb_build_object(
                            'telegram_message_id', $2::uuid::text,
                            'expected_result', $3::text
                        )
                    )
                    """,
                    task_id,
                    message_id,
                    payload.expected_result,
                )
                try:
                    await connection.execute(
                        """
                        insert into telegram_task_links (
                            telegram_message_id,
                            task_id,
                            relation_type
                        ) values ($1, $2, 'source')
                        """,
                        message_id,
                        task_id,
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise TelegramInboxAlreadyProcessedError(str(message_id)) from exc

                await connection.execute(
                    """
                    update telegram_messages
                    set inbox_status = 'confirmed',
                        classification = 'task',
                        reviewed_at = now()
                    where id = $1
                    """,
                    message_id,
                )
        return task_id


_INBOX_SELECT = """
select
    message.id,
    message.chat_id,
    chat.title as chat_title,
    venue.code as venue_code,
    venue.name as venue_name,
    message.message_id,
    message.sender_id,
    message.sender_name,
    message.message_text,
    message.message_date,
    message.attachments,
    message.classification,
    message.confidence,
    message.inbox_status,
    message.analysis,
    source_link.task_id as linked_task_id,
    message.processing_status,
    message.error_message,
    message.created_at
from telegram_messages as message
join telegram_chats as chat on chat.chat_id = message.chat_id
left join venues as venue on venue.id = chat.venue_id
left join telegram_task_links as source_link
    on source_link.telegram_message_id = message.id
   and source_link.relation_type = 'source'
"""


def _inbox_from_record(row: asyncpg.Record) -> TelegramInboxItemOut:
    values = dict(row)
    for field, fallback in (("attachments", []), ("analysis", {})):
        value = values.get(field)
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, type(fallback)):
            value = fallback
        values[field] = value
    confidence = values.get("confidence")
    values["confidence"] = float(confidence) if confidence is not None else None
    return TelegramInboxItemOut(**values)


async def _resolve_venue_id(
    pool: asyncpg.Pool,
    venue_code: str | None,
) -> UUID | None:
    if venue_code is None:
        return None
    venue_id = await pool.fetchval(
        "select id from venues where code = $1",
        venue_code,
    )
    if venue_id is None:
        raise ValueError("Unknown venue code")
    return venue_id


_UNSET = object()
_stores: dict[str, TelegramInboxStore] = {}


def get_telegram_inbox_store(database_url: str | None) -> TelegramInboxStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = TelegramInboxStore(database_url)
    return _stores[database_url]
