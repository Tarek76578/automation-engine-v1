from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class AgentDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    system_prompt: str = ""
    tools: list[ToolDefinition] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None


class AgentTask(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent: str = Field(min_length=1, max_length=100)
    input: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    task_id: UUID
    output: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    tool_calls: list[str] = Field(default_factory=list)
