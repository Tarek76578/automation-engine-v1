from __future__ import annotations

import logging

from app.core.job_queue import Job, Queue
from app.core.orchestrator import ExecutionOrchestrator
from app.models.execution import ExecutionStatus

logger = logging.getLogger(__name__)


class ExecutionWorker:
    def __init__(self, queue: Queue, orchestrator: ExecutionOrchestrator) -> None:
        self.queue = queue
        self.orchestrator = orchestrator
        self._recovered = False

    async def run_once(self) -> None:
        if not self._recovered:
            recovered = await self.queue.recover()
            if recovered:
                logger.warning("recovered %s in-flight jobs", recovered)
            self._recovered = True

        job: Job = await self.queue.dequeue()
        try:
            execution = await self.orchestrator.process(str(job.execution_id))
            if execution is None:
                await self.queue.dead_letter(job, "execution_not_found")
            elif execution.status is ExecutionStatus.failed:
                await self.queue.dead_letter(
                    job, execution.error or "execution_failed"
                )
            else:
                await self.queue.ack(job)
        except Exception:
            logger.exception(
                "execution worker failed; leaving job unacknowledged",
                extra={"execution_id": str(job.execution_id)},
            )
