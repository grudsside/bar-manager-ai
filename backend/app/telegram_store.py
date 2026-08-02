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

    async def register_chat(
        self,
        update: dict[str, Any],
        *,
        allow: bool = False,
    ) -> int | None:
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if not isinstance(chat_id, int):
            return None
        sender = message.get("from")
        sender_name = _telegram_name(sender) if isinstance(sender, dict) else None
        chat_title = _telegram_name(chat) if isinstance(chat, dict) else None
        chat_title = chat_title or sender_name or f"Telegram chat {chat_id}"

        pool = await self._get_pool()
        await pool.execute(
            """
            insert into telegram_chats (chat_id, title, allowed)
            values ($1, $2, $3)
            on conflict (chat_id) do update
            set title = excluded.title,
                allowed = telegram_chats.allowed or excluded.allowed
            """,
            chat_id,
            chat_title,
            allow,
        )
        return chat_id

    async def chat_access(self, chat_id: int) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            select
                chat.chat_id,
                chat.title,
                chat.allowed,
                chat.purpose,
                venue.code as venue_code
            from telegram_chats as chat
            left join venues as venue on venue.id = chat.venue_id
            where chat.chat_id = $1
            """,
            chat_id,
        )
        return dict(row) if row is not None else None

    async def record_incoming_update(
        self,
        update: dict[str, Any],
        *,
        inbox_status: str = "new",
        allow_chat: bool = False,
    ) -> UUID | None:
        if inbox_status not in {"new", "review", "confirmed", "dismissed", "ignored"}:
            raise ValueError("Unsupported Telegram inbox status")

        message = update.get("message")
        if not isinstance(message, dict):
            return None

        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        message_id = message.get("message_id")
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return None

        await self.register_chat(update, allow=allow_chat)

        sender = message.get("from")
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        sender_name = _telegram_name(sender) if isinstance(sender, dict) else None
        text = message.get("text") or message.get("caption")
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
        row = await pool.fetchrow(
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
                processing_status,
                inbox_status
            ) values (
                $1, $2, $3, $4, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10::jsonb,
                $11, 'incoming', 'user', 'processing', $12
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
            json.dumps(_attachments_metadata(message), ensure_ascii=False),
            json.dumps(update, ensure_ascii=False),
            telegram_update_id,
            inbox_status,
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

    async def save_inbox_analysis(
        self,
        record_id: UUID,
        *,
        classification: str,
        confidence: float,
        analysis: dict[str, Any],
    ) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            update telegram_messages
            set classification = $2,
                confidence = $3,
                analysis = $4::jsonb,
                processing_status = 'completed',
                processed_at = now(),
                error_message = null
            where id = $1
            """,
            record_id,
            classification,
            confidence,
            json.dumps(analysis, ensure_ascii=False),
        )

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
                inbox_status = 'ignored',
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
                inbox_status,
                processed_at
            ) values (
                $1, $2, $3, $4, $5, $6, $7,
                '[]'::jsonb, $8::jsonb,
                'outgoing', 'assistant', 'completed', 'ignored', now()
            )
            on conflict (chat_id, message_id) do update
            set message_text = excluded.message_text,
                raw_update = excluded.raw_update,
                processing_status = 'completed',
                inbox_status = 'ignored',
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


def _attachments_metadata(message: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = photos[-1]
        if isinstance(largest, dict):
            attachments.append(
                {
                    "type": "photo",
                    "file_id": largest.get("file_id"),
                    "width": largest.get("width"),
                    "height": largest.get("height"),
                }
            )
    for key in ("document", "video", "audio", "voice"):
        value = message.get(key)
        if isinstance(value, dict):
            attachments.append(
                {
                    "type": key,
                    "file_id": value.get("file_id"),
                    "file_name": value.get("file_name"),
                    "mime_type": value.get("mime_type"),
                    "file_size": value.get("file_size"),
                }
            )
    return attachments


_stores: dict[str, TelegramConversationStore] = {}


def get_telegram_store(database_url: str | None) -> TelegramConversationStore | None:
    if not database_url:
        return None
    if database_url not in _stores:
        _stores[database_url] = TelegramConversationStore(database_url)
    return _stores[database_url]
