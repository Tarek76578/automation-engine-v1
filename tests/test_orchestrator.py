import pytest

from app.core.action_executor import action_executor
from app.core.agent_runtime import AgentRegistry, AgentRuntime
from app.core.job_queue import InMemoryQueue
from app.core.observability import (
    ACTIONS_TOTAL,
    EXECUTIONS_TOTAL,
    EXECUTION_DURATION_SECONDS,
    EXECUTION_RETRIES_TOTAL,
    IDEMPOTENCY_HITS_TOTAL,
)
from app.core.orchestrator import ExecutionOrchestrator
from app.core.persistence import InMemoryExecutionRepository
from app.core.router import LLMRouter
from app.core.worker import ExecutionWorker
from app.models.agent import AgentDefinition
from app.models.execution import Execution, ExecutionStatus


@pytest.mark.asyncio
async def test_execution_flows_through_queue_worker_and_agent() -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {"answer": task.input["prompt"]}

    registry.register(AgentDefinition(name="support"), handler)
    runtime = AgentRuntime(registry, LLMRouter())
    repository = InMemoryExecutionRepository()
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(repository, queue, runtime)

    execution = await orchestrator.submit(
        Execution(
            workflow="support",
            input={"agent": "support", "input": {"prompt": "hello"}},
        ),
        idempotency_key="request-1",
    )
    duplicate = await orchestrator.submit(
        Execution(
            workflow="support",
            input={"agent": "support", "input": {"prompt": "ignored"}},
        ),
        idempotency_key="request-1",
    )

    assert duplicate.id == execution.id
    assert execution.idempotency_key == "request-1"
    assert execution.status is ExecutionStatus.queued

    await ExecutionWorker(queue, orchestrator).run_once()
    result = await repository.get(str(execution.id))

    assert result is not None
    assert result.status is ExecutionStatus.succeeded
    assert result.output is not None
    assert result.output["answer"] == "hello"


@pytest.mark.asyncio
async def test_submit_does_not_enqueue_loser_of_idempotency_race() -> None:
    class RaceRepository(InMemoryExecutionRepository):
        def __init__(self, existing: Execution) -> None:
            super().__init__()
            self.existing = existing

        async def get_by_idempotency_key(self, key: str) -> Execution | None:
            return None

        async def save(self, execution: Execution) -> Execution:
            return self.existing

    existing = Execution(workflow="support", idempotency_key="request-race")
    repository = RaceRepository(existing)
    queue = InMemoryQueue()
    runtime = AgentRuntime(AgentRegistry(), LLMRouter())
    orchestrator = ExecutionOrchestrator(repository, queue, runtime)

    submitted = await orchestrator.submit(
        Execution(workflow="support"), idempotency_key="request-race"
    )

    assert submitted.id == existing.id
    assert queue._queue.qsize() == 0


@pytest.mark.asyncio
async def test_execution_uses_default_agent_for_unknown_workflow() -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {"answer": task.input["prompt"]}

    registry.register(AgentDefinition(name="automation"), handler)
    runtime = AgentRuntime(registry, LLMRouter())
    repository = InMemoryExecutionRepository()
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(repository, queue, runtime)

    execution = await orchestrator.submit(
        Execution(
            workflow="lead-enrichment",
            input={"input": {"prompt": "enrich this lead"}},
        )
    )

    await ExecutionWorker(queue, orchestrator).run_once()
    result = await repository.get(str(execution.id))

    assert result is not None
    assert result.status is ExecutionStatus.succeeded
    assert result.output is not None
    assert result.output["agent"] == "automation"


@pytest.mark.asyncio
async def test_execution_retries_and_eventually_fails() -> None:
    registry = AgentRegistry()

    def broken_handler(task, definition):
        raise RuntimeError("boom")

    registry.register(AgentDefinition(name="broken"), broken_handler)
    runtime = AgentRuntime(registry, LLMRouter())
    repository = InMemoryExecutionRepository()
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(
        repository, queue, runtime, max_attempts=2
    )
    execution = await orchestrator.submit(
        Execution(workflow="broken", input={"agent": "broken"})
    )

    await ExecutionWorker(queue, orchestrator).run_once()
    first = await repository.get(str(execution.id))
    assert first is not None
    assert first.status is ExecutionStatus.queued
    assert first.attempts == 1

    await ExecutionWorker(queue, orchestrator).run_once()
    final = await repository.get(str(execution.id))
    assert final is not None
    assert final.status is ExecutionStatus.failed
    assert final.attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_executes_and_verifies_action(monkeypatch) -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {"action": "prepare_message", "summary": "send greeting"}

    registry.register(AgentDefinition(name="automation"), handler)
    runtime = AgentRuntime(registry, LLMRouter())
    repository = InMemoryExecutionRepository()
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(repository, queue, runtime)

    calls = []

    async def fake_execute(action, payload, execution_id):
        calls.append((action, payload, execution_id))
        return {
            "action": action,
            "status": "executed",
            "verified": True,
            "verification": "test_verified",
        }

    monkeypatch.setattr(action_executor, "execute", fake_execute)

    execution = await orchestrator.submit(
        Execution(
            workflow="automation",
            input={"agent": "automation", "input": {"message": "hello"}},
        )
    )

    await ExecutionWorker(queue, orchestrator).run_once()
    result = await repository.get(str(execution.id))

    assert result is not None
    assert result.status is ExecutionStatus.succeeded
    assert result.output is not None
    assert result.output["execution"]["verified"] is True
    assert calls == [
        ("prepare_message", {"message": "hello"}, str(execution.id))
    ]


@pytest.mark.asyncio
async def test_execution_metrics_record_success_and_idempotency_hit() -> None:
    registry = AgentRegistry()

    async def handler(task, definition):
        return {"answer": "ok"}

    registry.register(AgentDefinition(name="metrics-test"), handler)
    orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(), InMemoryQueue(), AgentRuntime(registry, LLMRouter())
    )

    before_success = EXECUTIONS_TOTAL.labels(workflow="metrics-test", status="succeeded")._value.get()
    before_hits = IDEMPOTENCY_HITS_TOTAL.labels(workflow="metrics-test")._value.get()

    execution = await orchestrator.submit(
        Execution(workflow="metrics-test", input={"agent": "metrics-test"}),
        idempotency_key="metrics-key",
    )
    await orchestrator.submit(
        Execution(workflow="metrics-test", input={"agent": "metrics-test"}),
        idempotency_key="metrics-key",
    )
    await orchestrator.process(str(execution.id))

    assert EXECUTIONS_TOTAL.labels(workflow="metrics-test", status="succeeded")._value.get() == before_success + 1
    assert IDEMPOTENCY_HITS_TOTAL.labels(workflow="metrics-test")._value.get() == before_hits + 1


@pytest.mark.asyncio
async def test_execution_metrics_record_retry_and_action_outcomes(monkeypatch) -> None:
    registry = AgentRegistry()

    def broken_handler(task, definition):
        raise RuntimeError("metrics boom")

    registry.register(AgentDefinition(name="metrics-broken"), broken_handler)
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(), queue, AgentRuntime(registry, LLMRouter()), max_attempts=2
    )
    before_retries = EXECUTION_RETRIES_TOTAL.labels(workflow="metrics-broken")._value.get()

    execution = await orchestrator.submit(
        Execution(workflow="metrics-broken", input={"agent": "metrics-broken"})
    )
    await orchestrator.process(str(execution.id))

    assert EXECUTION_RETRIES_TOTAL.labels(workflow="metrics-broken")._value.get() == before_retries + 1

    async def fake_execute(action, payload, execution_id):
        return {"action": action, "status": "executed", "verified": True}

    monkeypatch.setattr(action_executor, "execute", fake_execute)
    action_registry = AgentRegistry()

    async def action_handler(task, definition):
        return {"action": "metrics_action"}

    action_registry.register(AgentDefinition(name="metrics-action"), action_handler)
    action_orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(), InMemoryQueue(), AgentRuntime(action_registry, LLMRouter())
    )
    before_actions = ACTIONS_TOTAL.labels(action="metrics_action", status="succeeded")._value.get()
    action_execution = await action_orchestrator.submit(Execution(workflow="metrics-action"))
    await action_orchestrator.process(str(action_execution.id))

    assert ACTIONS_TOTAL.labels(action="metrics_action", status="succeeded")._value.get() == before_actions + 1
    assert EXECUTION_DURATION_SECONDS.labels(workflow="metrics-action", status="succeeded")._sum.get() > 0
