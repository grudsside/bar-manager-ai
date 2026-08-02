from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

TaskStatus = Literal["new", "planned", "work", "waiting", "done", "cancelled"]
TaskPriority = Literal["low", "normal", "high", "critical"]
TaskSource = Literal["manual", "telegram", "recurring", "agent", "file"]
VenueCode = Literal["oxford", "sovremennik"]
InboxStatus = Literal["new", "review", "confirmed", "dismissed", "ignored"]
InboxClassification = Literal[
    "task",
    "task_update",
    "writeoff",
    "preparation",
    "information",
    "unknown",
]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str
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


class TelegramChatOut(BaseModel):
    chat_id: int
    title: str
    allowed: bool
    purpose: str | None = None
    venue_code: VenueCode | None = None
    venue_name: str | None = None
    created_at: datetime
    updated_at: datetime


class TelegramChatUpdate(BaseModel):
    allowed: bool | None = None
    purpose: str | None = Field(default=None, max_length=2_000)
    venue_code: VenueCode | None = None


class TelegramInboxItemOut(BaseModel):
    id: UUID
    chat_id: int
    chat_title: str
    venue_code: VenueCode | None = None
    venue_name: str | None = None
    message_id: int
    sender_id: int | None = None
    sender_name: str | None = None
    message_text: str | None = None
    message_date: datetime | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    classification: InboxClassification | None = None
    confidence: float | None = None
    inbox_status: InboxStatus
    analysis: dict[str, Any] = Field(default_factory=dict)
    linked_task_id: UUID | None = None
    processing_status: str
    error_message: str | None = None
    created_at: datetime


class TelegramInboxUpdate(BaseModel):
    status: Literal["new", "review", "dismissed"]


class TelegramInboxTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    venue_code: VenueCode | None = None
    priority: TaskPriority = "normal"
    due_at: datetime | None = None
    expected_result: str | None = Field(default=None, max_length=2_000)
