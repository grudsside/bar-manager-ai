from pathlib import Path

import pytest

from app.agent import build_agent_input
from app.schemas import AgentChatRequest, AgentChatResponse
from app.telegram_bot import format_agent_response, split_telegram_text
from app.telegram_store import _forward_metadata, _telegram_name


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_split_telegram_text_respects_platform_limit() -> None:
    text = ("Абзац для проверки деления длинного ответа. " * 300).strip()

    chunks = split_telegram_text(text)

    assert len(chunks) > 1
    assert all(1 <= len(chunk) <= 4096 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_telegram_text_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        split_telegram_text("текст", limit=0)


def test_format_agent_response_includes_confirmation_and_actions() -> None:
    response = AgentChatResponse(
        answer="Задача подготовлена.",
        requires_confirmation=True,
        suggested_actions=["Создать задачу", "Назначить срок"],
    )

    formatted = format_agent_response(response)

    assert "Задача подготовлена." in formatted
    assert "требуется подтверждение" in formatted
    assert "• Создать задачу" in formatted
    assert "• Назначить срок" in formatted


def test_telegram_name_prefers_human_readable_fields() -> None:
    assert _telegram_name({"title": "Рабочий чат", "username": "ignored"}) == "Рабочий чат"
    assert _telegram_name({"first_name": "Григорий", "last_name": "Иванов"}) == "Григорий Иванов"
    assert _telegram_name({"username": "gridsside"}) == "@gridsside"


def test_forward_metadata_only_keeps_forward_fields() -> None:
    metadata = _forward_metadata(
        {
            "text": "Текст",
            "forward_sender_name": "Источник",
            "forward_date": 123,
        }
    )
    assert metadata == {"forward_sender_name": "Источник", "forward_date": 123}


def test_webhook_dispatches_processing_as_background_task() -> None:
    main_module = (REPO_ROOT / "backend" / "app" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "background_tasks.add_task(handle_telegram_update, update, current)" in main_module
    assert "X-Telegram-Bot-Api-Secret-Token" not in main_module
    assert "x_telegram_bot_api_secret_token" in main_module


def test_telegram_memory_is_persisted_and_passed_to_agent() -> None:
    bot_module = (REPO_ROOT / "backend" / "app" / "telegram_bot.py").read_text(
        encoding="utf-8"
    )
    store_module = (REPO_ROOT / "backend" / "app" / "telegram_store.py").read_text(
        encoding="utf-8"
    )
    migration = (
        REPO_ROOT / "backend" / "migrations" / "002_telegram_conversation_memory.sql"
    ).read_text(encoding="utf-8")

    assert "record_incoming_update(update)" in bot_module
    assert "recent_history(chat_id" in bot_module
    assert 'context={"recent_conversation": recent_history}' in bot_module
    assert "telegram_chat_id" not in bot_module
    assert "telegram_message_id" not in bot_module
    assert "telegram_update_id" not in bot_module
    assert "record_outgoing_message" in bot_module
    assert "mark_completed(record_id)" in bot_module
    assert "on conflict do nothing" in store_module
    assert "telegram_messages_update_id_unique_idx" in migration
    assert "processing_status" in migration


def test_agent_input_uses_history_without_exposing_technical_metadata() -> None:
    prompt = build_agent_input(
        AgentChatRequest(
            message="Какое кодовое слово?",
            context={
                "source": "telegram",
                "telegram_chat_id": 123,
                "telegram_message_id": 45,
                "telegram_update_id": 67,
                "recent_conversation": [
                    {"role": "user", "content": "Кодовое слово — Сапфир."},
                    {"role": "assistant", "content": "Запомнил."},
                ],
            },
        )
    )

    assert "Какое кодовое слово?" in prompt
    assert "Кодовое слово — Сапфир." in prompt
    assert "Запомнил." in prompt
    assert "telegram_chat_id" not in prompt
    assert "telegram_message_id" not in prompt
    assert "telegram_update_id" not in prompt
    assert '"source"' not in prompt
