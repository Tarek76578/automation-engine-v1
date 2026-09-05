import pytest

from app.core.agent_runtime import AgentRegistry, AgentRuntime
from app.core.job_queue import InMemoryQueue
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
async def test_execution_retries_and_eventually_fails_to_dlq() -> None:
    registry = AgentRegistry()

    def broken_handler(task, definition):
        raise RuntimeError("boom")

    registry.register(AgentDefinition(name="broken"), broken_handler)
    runtime = AgentRuntime(registry, LLMRouter())
    repository = InMemoryExecutionRepository()
    queue = InMemoryQueue()
    orchestrator = ExecutionOrchestrator(
        repository,
        queue,
        runtime,
        max_attempts=2,
        retry_base_delay_seconds=0,
    )
    execution = await orchestrator.submit(
        Execution(workflow="broken", input={"agent": "broken"})
    )

    await ExecutionWorker(queue, orchestrator).run_once()
    first = await repository.get(str(execution.id))
    assert first is not None
    assert first.status is ExecutionStatus.queued
    assert first.attempts == 1
    assert queue.dead_letters == []

    await ExecutionWorker(queue, orchestrator).run_once()
    final = await repository.get(str(execution.id))
    assert final is not None
    assert final.status is ExecutionStatus.failed
    assert final.attempts == 2
    assert len(queue.dead_letters) == 1
    assert queue.dead_letters[0][1] == "boom"


def test_retry_delay_is_exponential_and_bounded() -> None:
    orchestrator = ExecutionOrchestrator(
        InMemoryExecutionRepository(),
        InMemoryQueue(),
        AgentRuntime(AgentRegistry(), LLMRouter()),
        retry_base_delay_seconds=2,
        retry_max_delay_seconds=5,
    )

    assert orchestrator._retry_delay(1) == 2
    assert orchestrator._retry_delay(2) == 4
    assert orchestrator._retry_delay(3) == 5
    assert orchestrator._retry_delay(10) == 5
