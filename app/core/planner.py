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

    ALLOWED_ACTIONS = frozenset(
        {
            "prepare_message",
            "webhook",
            "http_webhook",
            "analyze_request",
            "process_request",
            "meta_page_info",
            "meta_page_messages",
            "meta_page_post",
            "meta_page_reply",
        }
    )
    SENSITIVE_MARKERS = (
        "publish",
        "delete",
        "send money",
        "payment",
        "charge",
        "spend",
        "post",
        "facebook post",
        "meta post",
        "reply",
        "messenger",
        "facebook message",
        "شراء",
        "دفع",
        "حذف",
        "نشر",
        "منشور",
        "رد",
        "رسالة فيسبوك",
        "ماسنجر",
    )
    SENSITIVE_ACTIONS = frozenset(
        {
            "publish",
            "delete",
            "payment",
            "charge",
            "send_money",
            "spend",
            "meta_page_post",
            "meta_page_reply",
        }
    )

    def __init__(self, provider: Any | None = None, model: str = "agent-planner") -> None:
        self.provider = provider
        self.model = model

    async def plan(self, task_input: dict[str, Any], system_prompt: str = "") -> AgentPlan:
        if self.provider is not None:
            try:
                response = await self.provider.generate(self._request(task_input, system_prompt))
                return self._validate(self._parse(response.text), task_input)
            except Exception as exc:
                if self._is_rate_limit_error(exc):
                    raise
                return self._local_plan(task_input)
        return self._local_plan(task_input)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        return (response is not None and getattr(response, "status_code", None) == 429) or (
            "429" in str(exc) and "too many requests" in str(exc).lower()
        )

    def _request(self, task_input: dict[str, Any], system_prompt: str) -> Any:
        from app.providers.base import LLMRequest

        prompt = (
            "Return JSON only with keys goal, steps, requires_approval, approval_reason. "
            "Each step must contain action, reason, parameters. "
            f"Task: {json.dumps(task_input, ensure_ascii=False)}"
        )
        return LLMRequest(model=self.model, prompt=prompt, system=system_prompt or None)

    @staticmethod
    def _parse(text: str) -> AgentPlan:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw[3:].strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        try:
            return AgentPlan.model_validate_json(raw)
        except ValidationError as exc:
            raise ValueError("LLM returned an invalid agent plan") from exc

    def _validate(self, plan: AgentPlan, task_input: dict[str, Any] | None = None) -> AgentPlan:
        for step in plan.steps:
            if step.action not in self.ALLOWED_ACTIONS:
                raise ValueError(f"unsupported planned action: {step.action}")
        if task_input is not None and self._is_sensitive(task_input, plan):
            plan.requires_approval = True
            if not plan.approval_reason:
                plan.approval_reason = "The request contains a sensitive or externally consequential operation."
        return plan

    def _is_sensitive(self, task_input: dict[str, Any], plan: AgentPlan) -> bool:
        text = json.dumps(task_input, ensure_ascii=False).lower()
        if any(marker in text for marker in self.SENSITIVE_MARKERS):
            return True
        return any(step.action.lower() in self.SENSITIVE_ACTIONS for step in plan.steps)

    def _local_plan(self, task_input: dict[str, Any]) -> AgentPlan:
        text = str(task_input.get("message", task_input.get("prompt", task_input.get("value", "")))).strip()
        lower = text.lower()
        if task_input.get("meta_page_post"):
            action = "meta_page_post"
            parameters = {"message": str(task_input["meta_page_post"])}
            if task_input.get("link"):
                parameters["link"] = task_input["link"]
        elif task_input.get("meta_page_reply"):
            action = "meta_page_reply"
            parameters = {
                "recipient_id": str(task_input.get("recipient_id", "")),
                "message": str(task_input["meta_page_reply"]),
            }
        elif task_input.get("meta_page_messages"):
            action = "meta_page_messages"
            parameters = {"limit": task_input.get("limit", 25)}
        elif task_input.get("meta_page_info"):
            action = "meta_page_info"
            parameters = {}
        elif task_input.get("webhook_url"):
            action = "webhook"
            parameters = {
                "webhook_url": task_input["webhook_url"],
                "webhook_payload": task_input.get("webhook_payload", task_input),
            }
        elif any(word in lower for word in ("send", "أرسل", "رسالة", "message")):
            action = "prepare_message"
            parameters = {"message": text}
        elif any(word in lower for word in ("analy", "حلل", "حلّل", "analyse", "analyze")):
            action = "analyze_request"
            parameters = {"request": text}
        else:
            action = "process_request"
            parameters = {"request": text}
        sensitive = self._is_sensitive(
            task_input, AgentPlan(goal=text or "Process automation request", steps=[PlanStep(action=action)])
        )
        return AgentPlan(
            goal=text or "Process automation request",
            steps=[PlanStep(action=action, reason="Deterministic fallback plan", parameters=parameters)],
            requires_approval=sensitive,
            approval_reason=(
                "The request appears to involve a sensitive or externally consequential operation."
                if sensitive
                else ""
            ),
        )
