from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.core.rule_store import rule_store
from app.main import app
from app.models.execution import Execution
from app.models.rule import AutomationRule, RuleAction, RuleCondition


class FakeOrchestrator:
    def __init__(self) -> None:
        self.received: Execution | None = None
        self.idempotency_key: str | None = None

    async def submit(
        self,
        execution: Execution,
        idempotency_key: str | None = None,
    ) -> Execution:
        self.received = execution
        self.idempotency_key = idempotency_key
        return execution


@pytest.mark.asyncio
async def test_webhook_matches_rule_and_enqueues_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = AutomationRule(
        id=uuid4(),
        name="welcome-new-customer",
        trigger={"type": "customer.created"},
        conditions=[
            RuleCondition(field="customer.name", operator="exists")
        ],
        actions=[
            RuleAction(
                type="prepare_message",
                parameters={"message": "Welcome {{customer.name}}"},
            )
        ],
    )
    await rule_store.save(rule)
    fake = FakeOrchestrator()
    monkeypatch.setattr("app.api.executions.orchestrator", fake)
    monkeypatch.setattr(
        "app.core.config.settings.inbound_webhook_secret", "secret"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/webhooks/{rule.id}",
            headers={
                "X-Webhook-Secret": "secret",
                "X-Webhook-Id": "evt-123",
            },
            json={"type": "customer.created", "customer": {"name": "Ahmed"}},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["matched"] is True
    assert fake.received is not None
    assert fake.received.input["customer"]["name"] == "Ahmed"
    assert fake.idempotency_key == f"webhook:{rule.id}:evt-123"


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = AutomationRule(
        id=uuid4(),
        name="protected-rule",
        actions=[
            RuleAction(type="prepare_message", parameters={"message": "ok"})
        ],
    )
    await rule_store.save(rule)
    monkeypatch.setattr(
        "app.core.config.settings.inbound_webhook_secret", "secret"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/webhooks/{rule.id}", json={"type": "test"}
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid webhook secret"
