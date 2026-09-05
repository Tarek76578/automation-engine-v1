from __future__ import annotations

import logging

from app.core.agent_runtime import AgentRuntime
from app.core.job_queue import Job, InMemoryQueue

logger = logging.getLogger(__name__)


class ExecutionWorker:
    def __init__(self, queue: InMemoryQueue, runtime: AgentRuntime) -> None:
        self.queue = queue
        self.runtime = runtime

    async def run_once(self) -> None:
        job: Job = await self.queue.dequeue()
        try:
            await self.runtime.execute_by_execution_id(job.execution_id)
        except Exception:
            logger.exception("execution worker failed", extra={"execution_id": str(job.execution_id)})
        finally:
            self.queue.task_done()
