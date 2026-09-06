from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class PlanStep(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    reason: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    goal: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1, max_length=20)
    requires_approval: bool = False
    approval_reason: str = ""


class AgentPlanner:
    """Convert an agent request into a validated, executable plan."""

    ALLOWED_ACTIONS = frozenset({"prepare_message", "webhook", "http_webhook", "analyze_request", "process_request"})
    SENSITIVE_MARKERS = ("publish", "delete", "send money", "payment", "charge", "شراء", "دفع", "حذف", "نشر")

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider

    async def plan(self, task_input: dict[str, Any], system_prompt: str = "") -> AgentPlan:
        if self.provider is not None:
            try:
                response = await self.provider.generate(self._request(task_input, system_prompt))
                plan = self._parse(response.text)
                return self._validate(plan)
            except Exception:
                # Planning must remain available when the configured LLM is unavailable
                # or returns malformed output; deterministic planning is the safe fallback.
                pass
        return self._local_plan(task_input)

    @staticmethod
    def _request(task_input: dict[str, Any], system_prompt: str) -> Any:
        from app.providers.base import LLMRequest

        prompt = (
            "Return JSON only with keys goal, steps, requires_approval, approval_reason. "
            "Each step must contain action, reason, parameters. "
            f"Task: {json.dumps(task_input, ensure_ascii=False)}"
        )
        return LLMRequest(model="agent-planner", prompt=prompt, system=system_prompt or None)

    @staticmethod
    def _parse(text: str) -> AgentPlan:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        try:
            return AgentPlan.model_validate_json(raw)
        except ValidationError as exc:
            raise ValueError("LLM returned an invalid agent plan") from exc

    def _validate(self, plan: AgentPlan) -> AgentPlan:
        for step in plan.steps:
            if step.action not in self.ALLOWED_ACTIONS:
                raise ValueError(f"unsupported planned action: {step.action}")
        return plan

    def _local_plan(self, task_input: dict[str, Any]) -> AgentPlan:
        text = str(task_input.get("message", task_input.get("prompt", task_input.get("value", "")))).strip()
        lower = text.lower()
        if task_input.get("webhook_url"):
            action = "webhook"
            parameters = {"webhook_url": task_input["webhook_url"], "webhook_payload": task_input.get("webhook_payload", task_input)}
        elif any(word in lower for word in ("send", "أرسل", "رسالة", "message")):
            action = "prepare_message"
            parameters = {"message": text}
        elif any(word in lower for word in ("analy", "حلل", "حلّل", "analyse", "analyze")):
            action = "analyze_request"
            parameters = {"request": text}
        else:
            action = "process_request"
            parameters = {"request": text}
        sensitive = any(marker in lower for marker in self.SENSITIVE_MARKERS)
        return AgentPlan(
            goal=text or "Process automation request",
            steps=[PlanStep(action=action, reason="Deterministic fallback plan", parameters=parameters)],
            requires_approval=sensitive,
            approval_reason="The request appears to involve a sensitive or externally consequential operation." if sensitive else "",
        )
