from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RuleCondition(BaseModel):
    field: str | None = None
    operator: str | None = None
    value: Any = None
    all: list["RuleCondition"] | None = None
    any: list["RuleCondition"] | None = None
    not_: "RuleCondition" | None = Field(default=None, alias="not")

    model_config = {"populate_by_name": True}


class RuleAction(BaseModel):
    type: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="Rule matched", max_length=500)


class AutomationRule(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int = 0
    trigger: dict[str, Any] | None = None
    conditions: list[RuleCondition] = Field(default_factory=list)
    actions: list[RuleAction] = Field(min_length=1)
    requires_approval: bool = False
    approval_reason: str = Field(default="", max_length=500)


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int = 0
    trigger: dict[str, Any] | None = None
    conditions: list[RuleCondition] = Field(default_factory=list)
    actions: list[RuleAction] = Field(min_length=1)
    requires_approval: bool = False
    approval_reason: str = Field(default="", max_length=500)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    priority: int | None = None
    trigger: dict[str, Any] | None = None
    conditions: list[RuleCondition] | None = None
    actions: list[RuleAction] | None = Field(default=None, min_length=1)
    requires_approval: bool | None = None
    approval_reason: str | None = Field(default=None, max_length=500)


class RuleDryRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
