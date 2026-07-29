from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Бар-менеджер AI API"
    environment: str = "development"
    app_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:8080"

    owner_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    owner_telegram_id: int | None = None

    database_url: str | None = None
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
