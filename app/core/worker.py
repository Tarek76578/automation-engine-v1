from __future__ import annotations

import logging

from app.core.job_queue import InMemoryQueue, Job
from app.core.orchestrator import ExecutionOrchestrator

logger = logging.getLogger(__name__)


class ExecutionWorker:
    def __init__(
        self, queue: InMemoryQueue, orchestrator: ExecutionOrchestrator
    ) -> None:
        self.queue = queue
        self.orchestrator = orchestrator

    async def run_once(self) -> None:
        job: Job = await self.queue.dequeue()
        try:
            await self.orchestrator.process(str(job.execution_id))
        except Exception:
            logger.exception(
                "execution worker failed",
                extra={"execution_id": str(job.execution_id)},
            )
        finally:
            self.queue.task_done()
