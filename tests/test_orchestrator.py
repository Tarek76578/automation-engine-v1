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
    assert execution.status is ExecutionStatus.queued

    await ExecutionWorker(queue, orchestrator).run_once()
    result = await repository.get(str(execution.id))

    assert result is not None
    assert result.status is ExecutionStatus.succeeded
    assert result.output is not None
    assert result.output["answer"] == "hello"


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
