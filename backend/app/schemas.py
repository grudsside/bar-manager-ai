from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    openai_configured: bool
    telegram_configured: bool
    database_configured: bool


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    task_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    answer: str
    requires_confirmation: bool = False
    suggested_actions: list[str] = Field(default_factory=list)


class TelegramWebhookResponse(BaseModel):
    accepted: bool = True
    update_id: int | None = None
    received_at: datetime
