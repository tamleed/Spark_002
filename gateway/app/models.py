from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    async_mode: bool | None = Field(default=None, alias="async")
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
    }


class JobCreateRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus = "queued"


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    requested_model: str
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float | None = None
    error: str | None = None


class QueueStatusResponse(BaseModel):
    queue_length: int
    current_job_id: str | None
    current_model: str | None
    switching: bool
    drain_mode: bool


class AdminSwitchRequest(BaseModel):
    model: str


class HealthResponse(BaseModel):
    status: str
    redis: str


class StatusResponse(BaseModel):
    active_model: str | None
    uptime_sec: float
    switching: bool
    current_job_id: str | None
    queue_length: int
    drain_mode: bool
