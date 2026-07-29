from app.config import Settings


def test_empty_optional_environment_values_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")

    settings = Settings(_env_file=None)

    assert settings.owner_telegram_id is None
    assert settings.openai_api_key is None
    assert settings.telegram_bot_token is None
