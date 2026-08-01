from __future__ import annotations

import logging
from typing import Any

import httpx

from .agent import run_agent
from .config import Settings
from .schemas import AgentChatRequest, AgentChatResponse

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_TEXT_LIMIT = 4096

logger = logging.getLogger(__name__)


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
        # httpx exceptions can include the request URL, which contains the bot token.
        # Replace them with a token-free error before anything reaches application logs.
        raise RuntimeError(f"Telegram API {method} request failed") from None

    if not body.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed")
    return body


async def send_telegram_text(settings: Settings, chat_id: int, text: str) -> None:
    for chunk in split_telegram_text(text):
        await telegram_api_call(
            settings,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": chunk,
                "link_preview_options": {"is_disabled": True},
            },
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
    """Process one Telegram update after the webhook has already returned HTTP 200."""
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

    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        await send_telegram_text(
            settings,
            chat_id,
            "Пока я умею обрабатывать только текстовые сообщения.",
        )
        return

    normalized = text.strip()
    command = normalized.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command == "/start":
        await send_telegram_text(
            settings,
            chat_id,
            (
                "Bar Manager AI подключён. Отправьте задачу, вопрос или описание "
                "рабочей ситуации обычным текстом."
            ),
        )
        return

    await send_typing_action(settings, chat_id)

    try:
        result = await run_agent(
            AgentChatRequest(
                message=normalized,
                context={
                    "source": "telegram",
                    "telegram_chat_id": chat_id,
                    "telegram_message_id": message.get("message_id"),
                    "telegram_update_id": update.get("update_id"),
                },
            ),
            settings,
        )
        await send_telegram_text(settings, chat_id, format_agent_response(result))
    except Exception:
        logger.exception("Telegram update processing failed")
        try:
            await send_telegram_text(
                settings,
                chat_id,
                "Не удалось обработать сообщение. Попробуйте ещё раз через минуту.",
            )
        except Exception:
            logger.exception("Failed to send Telegram error message")
