from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from .agent import run_agent
from .config import Settings, get_settings
from .schemas import (
    AgentChatRequest,
    AgentChatResponse,
    HealthResponse,
    TaskCreate,
    TaskOut,
    TaskStatus,
    TaskUpdate,
    TelegramWebhookResponse,
)
from .task_store import TaskNotFoundError, TaskStore, get_task_store
from .telegram_bot import handle_telegram_update

settings = get_settings()
if settings.openai_api_key:
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
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


def task_store(current: Settings = Depends(get_settings)) -> TaskStore:
    return get_task_store(current.database_url)


@app.get("/health", response_model=HealthResponse)
async def health(current: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        service=current.app_name,
        environment=current.environment,
        openai_configured=bool(current.openai_api_key),
        telegram_configured=bool(current.telegram_bot_token and current.telegram_webhook_secret),
        database_configured=bool(current.database_url),
    )


@app.get(
    "/api/tasks",
    response_model=list[TaskOut],
    dependencies=[Depends(require_owner)],
)
async def list_tasks(
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    store: TaskStore = Depends(task_store),
) -> list[TaskOut]:
    return await store.list_tasks(status=task_status)


@app.post(
    "/api/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_owner)],
)
async def create_task(
    payload: TaskCreate,
    store: TaskStore = Depends(task_store),
) -> TaskOut:
    try:
        return await store.create_task(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get(
    "/api/tasks/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_owner)],
)
async def get_task(task_id: UUID, store: TaskStore = Depends(task_store)) -> TaskOut:
    try:
        return await store.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc


@app.patch(
    "/api/tasks/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_owner)],
)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    store: TaskStore = Depends(task_store),
) -> TaskOut:
    try:
        return await store.update_task(task_id, payload)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(handle_telegram_update, update, current)

    return TelegramWebhookResponse(
        update_id=update.get("update_id"),
        received_at=datetime.now(timezone.utc),
    )
