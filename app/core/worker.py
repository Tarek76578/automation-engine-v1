from __future__ import annotations

import logging

from app.core.job_queue import Job, Queue
from app.core.orchestrator import ExecutionOrchestrator

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
            if execution is not None:
                await self.queue.ack(job)
        except Exception:
            logger.exception(
                "execution worker failed; leaving job unacknowledged",
                extra={"execution_id": str(job.execution_id)},
            )
