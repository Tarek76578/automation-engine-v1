from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ExecutionStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    waiting_approval = "waiting_approval"


class ExecutionRequest(BaseModel):
    workflow: str = Field(min_length=1, max_length=200)
    input: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)


class Execution(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workflow: str
    status: ExecutionStatus = ExecutionStatus.queued
    input: dict = Field(default_factory=dict)
    output: dict | None = None
    error: str | None = None
    attempts: int = 0
    idempotency_key: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
