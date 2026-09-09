from __future__ import annotations

import hmac
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.core.rule_engine import RuleEngine
from app.core.rule_store import rule_store
from app.models.execution import Execution

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
engine = RuleEngine()


@router.post("/{rule_id}", status_code=202)
async def receive_webhook(
    rule_id: UUID,
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
    x_webhook_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if settings.inbound_webhook_secret:
        if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.inbound_webhook_secret):
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    rule = await rule_store.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not rule.enabled:
        raise HTTPException(status_code=409, detail="Rule is disabled")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")

    event_type = payload.get("event_type") or payload.get("type")
    event = payload.get("event")
    if not isinstance(event, dict):
        event = {"type": event_type, "payload": payload}
    elif event_type and "type" not in event:
        event = {**event, "type": event_type}

    task_input = {**payload, "event": event, "event_type": event.get("type"), "rule_id": str(rule.id)}
    rule_data = rule.model_dump(mode="json", by_alias=True)
    task_input["rules"] = [rule_data]
    plan = engine.plan(task_input)
    if plan.goal != rule.name:
        raise HTTPException(status_code=422, detail="Webhook received but rule conditions did not match")

    execution = Execution(workflow=f"webhook:{rule.name}", input=task_input)
    idempotency_key = None
    if x_webhook_id:
        idempotency_key = f"webhook:{rule.id}:{x_webhook_id[:200]}"

    from app.api.executions import orchestrator

    saved = await orchestrator.submit(execution, idempotency_key)
    return {
        "accepted": True,
        "execution_id": str(saved.id),
        "status": saved.status.value,
        "rule_id": str(rule.id),
        "rule": rule.name,
        "matched": True,
    }
