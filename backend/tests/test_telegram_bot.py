from pathlib import Path

import pytest

from app.schemas import AgentChatResponse
from app.telegram_bot import format_agent_response, split_telegram_text


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


def test_webhook_dispatches_processing_as_background_task() -> None:
    main_module = (REPO_ROOT / "backend" / "app" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "background_tasks.add_task(handle_telegram_update, update, current)" in main_module
    assert "X-Telegram-Bot-Api-Secret-Token" not in main_module
    assert "x_telegram_bot_api_secret_token" in main_module
