from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.agent_runtime import AgentRuntime
from app.core.job_queue import Job, Queue
from app.core.persistence import ExecutionRepository
from app.core.state_machine import transition
from app.integrations.n8n import N8nClient
from app.models.agent import AgentTask
from app.models.execution import Execution, ExecutionStatus

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """Coordinates the durable execution lifecycle.

    API requests only create and enqueue work. The worker owns execution,
    state transitions, persistence, retry accounting, and optional n8n output.
    """

    def __init__(
        self,
        repository: ExecutionRepository,
        queue: Queue,
        runtime: AgentRuntime,
        n8n: N8nClient | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.runtime = runtime
        self.n8n = n8n
        self.max_attempts = max(1, max_attempts)

    async def submit(self, execution: Execution) -> Execution:
        existing = await self.repository.get(str(execution.id))
        if existing is not None:
            return existing
        await self.repository.save(execution)
        await self.queue.enqueue(Job(execution_id=execution.id))
        return execution

    async def process(self, execution_id: str) -> Execution | None:
        execution = await self.repository.get(execution_id)
        if execution is None:
            return None
        if execution.status in {ExecutionStatus.succeeded, ExecutionStatus.failed}:
            return execution

        transition(execution, ExecutionStatus.running)
        execution.attempts += 1
        execution.updated_at = datetime.now(timezone.utc)
        await self.repository.save(execution)

        try:
            agent_name = str(execution.input.get("agent", execution.workflow))
            task_input = execution.input.get("input", execution.input)
            if not isinstance(task_input, dict):
                task_input = {"value": task_input}

            result = await self.runtime.execute_async(
                AgentTask(agent=agent_name, input=task_input)
            )
            output: dict[str, Any] = dict(result.output)
            output["agent"] = agent_name
            output["provider"] = result.provider
            output["model"] = result.model

            webhook = execution.input.get("n8n_webhook")
            if webhook:
                if self.n8n is None:
                    raise RuntimeError("n8n webhook requested but N8nClient is not configured")
                output["n8n"] = await self.n8n.trigger_webhook(
                    str(webhook),
                    {"execution_id": str(execution.id), "output": output},
                )

            transition(execution, ExecutionStatus.succeeded)
            execution.output = output
            execution.error = None
        except Exception as exc:
            execution.error = str(exc)
            if execution.attempts >= self.max_attempts:
                transition(execution, ExecutionStatus.failed)
            else:
                transition(execution, ExecutionStatus.queued)
                await self.repository.save(execution)
                await self.queue.enqueue(Job(execution_id=execution.id))
                logger.warning(
                    "execution retry scheduled",
                    extra={"execution_id": execution_id, "attempt": execution.attempts},
                )
                return execution
        execution.updated_at = datetime.now(timezone.utc)
        await self.repository.save(execution)
        return execution
