from datetime import UTC, datetime, timedelta

import pytest

from app.core.action_executor import action_executor
from app.core.agent_runtime import AgentRegistry, AgentRuntime
from app.core.approval import ApprovalManager
from app.core.job_queue import InMemoryQueue
from app.core.orchestrator import ExecutionOrchestrator
from app.core.persistence import InMemoryExecutionRepository
from app.core.router import LLMRouter
from app.models.agent import AgentDefinition
from app.models.execution import Execution, ExecutionStatus


@pytest.mark.asyncio
async def test_sensitive_execution_waits_for_approval_and_does_not_execute(monkeypatch) -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {
            "action": "prepare_message",
            "summary": "publish approved message",
            "plan": {
                "goal": "publish approved message",
                "steps": [{"action": "prepare_message", "reason": "publish", "parameters": {"message": "hello"}}],
                "requires_approval": True,
                "approval_reason": "Publishing is externally consequential.",
            },
        }

    registry.register(AgentDefinition(name="automation"), handler)
    orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(), InMemoryQueue(), AgentRuntime(registry, LLMRouter())
    )
    calls = []

    async def fake_execute(action, payload, execution_id):
        calls.append((action, payload, execution_id))
        return {"action": action, "verified": True}

    monkeypatch.setattr(action_executor, "execute", fake_execute)
    execution = await orchestrator.submit(Execution(workflow="automation", input={"agent": "automation"}))

    result = await orchestrator.process(str(execution.id))

    assert result is not None
    assert result.status is ExecutionStatus.waiting_approval
    assert result.approval_token
    assert result.approval_token_hash
    assert result.approval_token_hash != result.approval_token
    assert calls == []


@pytest.mark.asyncio
async def test_approval_executes_once_and_invalid_token_is_rejected(monkeypatch) -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {
            "action": "prepare_message",
            "plan": {
                "goal": "publish message",
                "steps": [{"action": "prepare_message"}],
                "requires_approval": True,
                "approval_reason": "Publishing requires approval.",
            },
        }

    registry.register(AgentDefinition(name="automation"), handler)
    repository = InMemoryExecutionRepository()
    orchestrator = ExecutionOrchestrator(repository, InMemoryQueue(), AgentRuntime(registry, LLMRouter()))
    calls = []

    async def fake_execute(action, payload, execution_id):
        calls.append(execution_id)
        return {"action": action, "verified": True}

    monkeypatch.setattr(action_executor, "execute", fake_execute)
    execution = await orchestrator.submit(Execution(workflow="automation", input={"agent": "automation"}))
    waiting = await orchestrator.process(str(execution.id))
    assert waiting is not None and waiting.approval_token

    with pytest.raises(ValueError, match="invalid or expired"):
        await orchestrator.approve(str(execution.id), "wrong-token", "tester")

    approved = await orchestrator.approve(str(execution.id), waiting.approval_token, "tester")
    assert approved is not None
    assert approved.status is ExecutionStatus.succeeded
    assert approved.approval_decision == "approved"
    assert approved.approval_decided_by == "tester"
    assert approved.approval_token_hash is None
    assert calls == [str(execution.id)]


@pytest.mark.asyncio
async def test_reject_prevents_execution(monkeypatch) -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {
            "action": "prepare_message",
            "plan": {"goal": "delete item", "steps": [{"action": "prepare_message"}], "requires_approval": True},
        }

    registry.register(AgentDefinition(name="automation"), handler)
    orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(), InMemoryQueue(), AgentRuntime(registry, LLMRouter())
    )
    calls = []

    async def fake_execute(*args):
        calls.append(args)
        return {"action": "prepare_message", "verified": True}

    monkeypatch.setattr(action_executor, "execute", fake_execute)
    execution = await orchestrator.submit(Execution(workflow="automation", input={"agent": "automation"}))
    waiting = await orchestrator.process(str(execution.id))
    assert waiting is not None and waiting.approval_token

    rejected = await orchestrator.reject(str(execution.id), waiting.approval_token, "tester")
    assert rejected is not None
    assert rejected.status is ExecutionStatus.failed
    assert rejected.approval_decision == "rejected"
    assert calls == []


def test_approval_manager_rejects_expired_tokens() -> None:
    manager = ApprovalManager(ttl_seconds=60)
    now = datetime(2026, 9, 6, tzinfo=UTC)
    token, token_hash, expires_at = manager.issue(now)

    assert manager.verify(token, token_hash, expires_at, now + timedelta(seconds=59))
    assert not manager.verify(token, token_hash, expires_at, now + timedelta(seconds=60))
