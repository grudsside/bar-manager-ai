from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .agent import run_agent
from .config import Settings
from .schemas import AgentChatRequest, AgentChatResponse
from .telegram_recurring_commands import maybe_handle_recurring_command
from .telegram_store import TelegramConversationStore, get_telegram_store
from .telegram_summary_commands import maybe_handle_summary_command
from .telegram_task_commands import maybe_handle_task_command
from .telegram_task_history_commands import maybe_handle_task_history_command

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_HISTORY_LIMIT = 12

logger = logging.getLogger(__name__)
_chat_locks: dict[int, asyncio.Lock] = {}


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split text into Telegram-safe chunks, preferring paragraph and word boundaries."""
    normalized = text.strip()
    if not normalized:
        return []
    if limit < 1:
        raise ValueError("limit must be positive")

    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > limit:
        boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary < 1:
            boundary = limit

        chunk = remaining[:boundary].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[boundary:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


def format_agent_response(response: AgentChatResponse) -> str:
    sections = [response.answer.strip()]
    if response.requires_confirmation:
        sections.append("⚠️ Для выполнения действия требуется подтверждение.")
    if response.suggested_actions:
        actions = "\n".join(f"• {action}" for action in response.suggested_actions)
        sections.append(f"Возможные действия:\n{actions}")
    return "\n\n".join(section for section in sections if section)


async def telegram_api_call(
    settings: Settings,
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        raise RuntimeError("Telegram bot token is not configured")

    url = f"{TELEGRAM_API_BASE_URL}/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError(f"Telegram API {method} request failed") from None

    if not body.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed")
    return body


async def send_telegram_text(
    settings: Settings,
    chat_id: int,
    text: str,
    *,
    store: TelegramConversationStore | None = None,
    reply_to_message_id: int | None = None,
) -> None:
    for index, chunk in enumerate(split_telegram_text(text)):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "link_preview_options": {"is_disabled": True},
        }
        if index == 0 and reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        body = await telegram_api_call(settings, "sendMessage", payload)
        result = body.get("result")
        if store is not None and isinstance(result, dict):
            await store.record_outgoing_message(
                chat_id,
                result,
                chunk,
                reply_to_message_id=reply_to_message_id,
            )


async def send_typing_action(settings: Settings, chat_id: int) -> None:
    try:
        await telegram_api_call(
            settings,
            "sendChatAction",
            {"chat_id": chat_id, "action": "typing"},
        )
    except Exception:
        logger.exception("Failed to send Telegram typing action")


async def handle_telegram_update(update: dict[str, Any], settings: Settings) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return

    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, int):
        return

    if settings.owner_telegram_id is None or chat_id != settings.owner_telegram_id:
        logger.warning("Ignored Telegram message from unauthorized chat_id=%s", chat_id)
        return

    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        await _handle_authorized_message(update, message, chat_id, settings)


async def _handle_authorized_message(
    update: dict[str, Any],
    message: dict[str, Any],
    chat_id: int,
    settings: Settings,
) -> None:
    store = get_telegram_store(settings.database_url)
    record_id = None
    try:
        if store is not None:
            record_id = await store.record_incoming_update(update)
            if record_id is None:
                logger.info("Ignored duplicate Telegram update_id=%s", update.get("update_id"))
                return

        message_id = message.get("message_id")
        reply_to_message_id = message_id if isinstance(message_id, int) else None
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            await send_telegram_text(
                settings,
                chat_id,
                "Пока я умею обрабатывать только текстовые сообщения.",
                store=store,
                reply_to_message_id=reply_to_message_id,
            )
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        normalized = text.strip()
        command = normalized.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
        if command == "/start":
            await send_telegram_text(
                settings,
                chat_id,
                (
                    "Bar Manager AI подключён. Я учитываю недавний контекст диалога.\n\n"
                    "Задачи:\n"
                    "/task <поручение> — подготовить проект задачи\n"
                    "/tasks — показать актуальные задачи\n"
                    "/task_info N — открыть карточку и историю задачи\n"
                    "/summary — показать управленческую сводку\n\n"
                    "Повторяющиеся задачи:\n"
                    "/repeat <правило> — подготовить ежедневное или еженедельное правило\n"
                    "/recurring — показать активные правила\n"
                    "/disable_repeat N — отключить правило\n\n"
                    "/confirm — подтвердить подготовленное действие\n"
                    "/cancel — отменить подготовленное действие"
                ),
                store=store,
                reply_to_message_id=reply_to_message_id,
            )
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        handled = await maybe_handle_summary_command(
            normalized,
            chat_id=chat_id,
            source_message_id=reply_to_message_id,
            settings=settings,
            send_text=send_telegram_text,
            conversation_store=store,
        )
        if handled:
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        handled = await maybe_handle_recurring_command(
            normalized,
            chat_id=chat_id,
            source_message_id=reply_to_message_id,
            settings=settings,
            send_text=send_telegram_text,
            conversation_store=store,
        )
        if handled:
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        handled = await maybe_handle_task_history_command(
            normalized,
            chat_id=chat_id,
            source_message_id=reply_to_message_id,
            settings=settings,
            send_text=send_telegram_text,
            conversation_store=store,
        )
        if handled:
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        handled = await maybe_handle_task_command(
            normalized,
            chat_id=chat_id,
            source_message_id=reply_to_message_id,
            settings=settings,
            send_text=send_telegram_text,
            conversation_store=store,
        )
        if handled:
            if store is not None and record_id is not None:
                await store.mark_completed(record_id)
            return

        await send_typing_action(settings, chat_id)
        recent_history = (
            await store.recent_history(chat_id, limit=TELEGRAM_HISTORY_LIMIT)
            if store is not None
            else []
        )
        result = await run_agent(
            AgentChatRequest(
                message=normalized,
                context={"recent_conversation": recent_history},
            ),
            settings,
        )
        await send_telegram_text(
            settings,
            chat_id,
            format_agent_response(result),
            store=store,
            reply_to_message_id=reply_to_message_id,
        )
        if store is not None and record_id is not None:
            await store.mark_completed(record_id)
    except Exception as exc:
        logger.exception("Telegram update processing failed")
        if store is not None and record_id is not None:
            try:
                await store.mark_failed(record_id, type(exc).__name__)
            except Exception:
                logger.exception("Failed to mark Telegram message as failed")
        try:
            await send_telegram_text(
                settings,
                chat_id,
                "Не удалось обработать сообщение. Попробуйте ещё раз через минуту.",
                store=store,
                reply_to_message_id=(
                    message.get("message_id")
                    if isinstance(message.get("message_id"), int)
                    else None
                ),
            )
        except Exception:
            logger.exception("Failed to send Telegram error message")
