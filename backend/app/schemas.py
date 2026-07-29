from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

TaskStatus = Literal["new", "planned", "work", "waiting", "done", "cancelled"]
TaskPriority = Literal["low", "normal", "high", "critical"]
TaskSource = Literal["manual", "telegram", "recurring", "agent", "file"]
VenueCode = Literal["oxford", "sovremennik"]


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


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    original_text: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    status: TaskStatus = "new"
    priority: TaskPriority = "normal"
    due_at: datetime | None = None
    waiting_until: datetime | None = None
    source_type: TaskSource = "manual"
    source_reference: str | None = Field(default=None, max_length=1_000)
    requires_confirmation: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    original_text: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    waiting_until: datetime | None = None
    source_type: TaskSource | None = None
    source_reference: str | None = Field(default=None, max_length=1_000)
    requires_confirmation: bool | None = None


class TaskOut(BaseModel):
    id: UUID
    venue_code: VenueCode | None = None
    venue_name: str | None = None
    title: str
    description: str | None = None
    original_text: str | None = None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None = None
    waiting_until: datetime | None = None
    source_type: TaskSource
    source_reference: str | None = None
    requires_confirmation: bool
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
