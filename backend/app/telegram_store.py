from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg


class TelegramConversationStore:
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

    async def record_incoming_update(self, update: dict[str, Any]) -> UUID | None:
        message = update.get("message")
        if not isinstance(message, dict):
            return None

        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        message_id = message.get("message_id")
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return None

        sender = message.get("from")
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        sender_name = _telegram_name(sender) if isinstance(sender, dict) else None
        chat_title = _telegram_name(chat) if isinstance(chat, dict) else None
        chat_title = chat_title or sender_name or f"Telegram chat {chat_id}"
        text = message.get("text")
        message_text = text if isinstance(text, str) else None
        update_id = update.get("update_id")
        telegram_update_id = update_id if isinstance(update_id, int) else None
        reply_to = message.get("reply_to_message")
        reply_to_message_id = (
            reply_to.get("message_id") if isinstance(reply_to, dict) else None
        )
        raw_date = message.get("date")
        message_date = (
            datetime.fromtimestamp(raw_date, tz=timezone.utc)
            if isinstance(raw_date, int)
            else None
        )

        pool = await self._get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    insert into telegram_chats (chat_id, title, allowed)
                    values ($1, $2, true)
                    on conflict (chat_id) do update
                    set title = excluded.title,
                        allowed = true
                    """,
                    chat_id,
                    chat_title,
                )
                row = await connection.fetchrow(
                    """
                    insert into telegram_messages (
                        chat_id,
                        message_id,
                        sender_id,
                        sender_name,
                        message_text,
                        message_date,
                        reply_to_message_id,
                        forwarded_from,
                        attachments,
                        raw_update,
                        telegram_update_id,
                        direction,
                        role,
                        processing_status
                    ) values (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8::jsonb, '[]'::jsonb, $9::jsonb,
                        $10, 'incoming', 'user', 'processing'
                    )
                    on conflict do nothing
                    returning id
                    """,
                    chat_id,
                    message_id,
                    sender_id if isinstance(sender_id, int) else None,
                    sender_name,
                    message_text,
                    message_date,
                    reply_to_message_id if isinstance(reply_to_message_id, int) else None,
                    json.dumps(_forward_metadata(message), ensure_ascii=False),
                    json.dumps(update, ensure_ascii=False),
                    telegram_update_id,
                )
        return row["id"] if row is not None else None

    async def recent_history(self, chat_id: int, *, limit: int = 12) -> list[dict[str, str]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            select role, message_text
            from telegram_messages
            where chat_id = $1
              and processing_status = 'completed'
              and message_text is not null
            order by created_at desc
            limit $2
            """,
            chat_id,
            max(1, min(limit, 50)),
        )
        return [
            {"role": row["role"], "content": row["message_text"]}
            for row in reversed(rows)
        ]

    async def mark_completed(self, record_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update telegram_messages
            set processing_status = 'completed',
                processed_at = now(),
                error_message = null
            where id = $1
            """,
            record_id,
        )

    async def mark_failed(self, record_id: UUID, error_message: str) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update telegram_messages
            set processing_status = 'failed',
                processed_at = now(),
                error_message = $2
            where id = $1
            """,
            record_id,
            error_message[:1000],
        )

    async def mark_ignored(self, record_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update telegram_messages
            set processing_status = 'ignored',
                processed_at = now()
            where id = $1
            """,
            record_id,
        )

    async def record_outgoing_message(
        self,
        chat_id: int,
        message: dict[str, Any],
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> None:
        message_id = message.get("message_id")
        if not isinstance(message_id, int):
            return
        sender = message.get("from")
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        sender_name = _telegram_name(sender) if isinstance(sender, dict) else "Bar Manager AI"
        raw_date = message.get("date")
        message_date = (
            datetime.fromtimestamp(raw_date, tz=timezone.utc)
            if isinstance(raw_date, int)
            else datetime.now(timezone.utc)
        )

        pool = await self._get_pool()
        await pool.execute(
            """
            insert into telegram_messages (
                chat_id,
                message_id,
                sender_id,
                sender_name,
                message_text,
                message_date,
                reply_to_message_id,
                attachments,
                raw_update,
                direction,
                role,
                processing_status,
                processed_at
            ) values (
                $1, $2, $3, $4, $5, $6, $7,
                '[]'::jsonb, $8::jsonb,
                'outgoing', 'assistant', 'completed', now()
            )
            on conflict (chat_id, message_id) do update
            set message_text = excluded.message_text,
                raw_update = excluded.raw_update,
                processing_status = 'completed',
                processed_at = now(),
                error_message = null
            """,
            chat_id,
            message_id,
            sender_id if isinstance(sender_id, int) else None,
            sender_name,
            text,
            message_date,
            reply_to_message_id,
            json.dumps({"telegram_api_result": message}, ensure_ascii=False),
        )


def _telegram_name(entity: dict[str, Any]) -> str | None:
    title = entity.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    parts = [entity.get("first_name"), entity.get("last_name")]
    full_name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    if full_name:
        return full_name
    username = entity.get("username")
    if isinstance(username, str) and username.strip():
        return f"@{username.strip()}"
    return None


def _forward_metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("forward_origin", "forward_from", "forward_sender_name", "forward_date"):
        if key in message:
            metadata[key] = message[key]
    return metadata


_stores: dict[str, TelegramConversationStore] = {}


def get_telegram_store(database_url: str | None) -> TelegramConversationStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = TelegramConversationStore(database_url)
    return _stores[database_url]
