from __future__ import annotations

import asyncio
import logging

from app.core.agent_runtime import agent_runtime
from app.core.config import settings
from app.core.job_queue import queue
from app.core.orchestrator import ExecutionOrchestrator
from app.core.worker import ExecutionWorker
from app.integrations.n8n import N8nClient

logger = logging.getLogger(__name__)


async def main() -> None:
    n8n = N8nClient(settings.n8n_base_url) if settings.n8n_base_url else None
    orchestrator = ExecutionOrchestrator(queue=queue, repository=__import__('app.core.persistence', fromlist=['execution_repository']).execution_repository, runtime=agent_runtime, n8n=n8n)
    worker = ExecutionWorker(queue, orchestrator)
    logger.info("automation execution worker started")
    while True:
        await worker.run_once()


if __name__ == "__main__":
    asyncio.run(main())
