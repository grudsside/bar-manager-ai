from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .agent import run_agent
from .config import Settings, get_settings
from .schemas import (
    AgentChatRequest,
    AgentChatResponse,
    HealthResponse,
    TelegramWebhookResponse,
)

settings = get_settings()
if settings.openai_api_key:
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Owner-Key"],
)


def require_owner(
    x_owner_key: Annotated[str | None, Header()] = None,
    current: Settings = Depends(get_settings),
) -> None:
    if not current.owner_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner access is not configured",
        )
    if not x_owner_key or not hmac.compare_digest(x_owner_key, current.owner_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid owner key",
        )


@app.get("/health", response_model=HealthResponse)
async def health(current: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        service=current.app_name,
        environment=current.environment,
        openai_configured=bool(current.openai_api_key),
        telegram_configured=bool(current.telegram_bot_token and current.telegram_webhook_secret),
        database_configured=bool(current.database_url),
    )


@app.post(
    "/api/agent/chat",
    response_model=AgentChatResponse,
    dependencies=[Depends(require_owner)],
)
async def agent_chat(
    payload: AgentChatRequest,
    current: Settings = Depends(get_settings),
) -> AgentChatResponse:
    try:
        return await run_agent(payload, current)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.post("/api/telegram/webhook", response_model=TelegramWebhookResponse)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    current: Settings = Depends(get_settings),
) -> TelegramWebhookResponse:
    if not current.telegram_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook is not configured",
        )
    if (
        not x_telegram_bot_api_secret_token
        or not hmac.compare_digest(
            x_telegram_bot_api_secret_token,
            current.telegram_webhook_secret,
        )
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    update: dict[str, Any] = await request.json()

    # Следующий этап: проверить белый список chat_id, сохранить исходное сообщение
    # в PostgreSQL и поставить его в очередь ИИ-классификации. До подключения базы
    # webhook подтверждает получение, но не выполняет необратимых действий.
    return TelegramWebhookResponse(
        update_id=update.get("update_id"),
        received_at=datetime.now(timezone.utc),
    )
