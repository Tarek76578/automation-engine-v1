from __future__ import annotations

import asyncio
import logging

from app.api.executions import orchestrator
from app.core.job_queue import queue

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Continuously consume queued executions and acknowledge each job."""
    logger.info("automation worker started")
    while True:
        try:
            recovered = await queue.recover()
            if recovered:
                logger.warning("recovered %s stale queue job(s)", recovered)

            job = await queue.dequeue()
            try:
                result = await orchestrator.process(str(job.execution_id))
                if result is None:
                    await queue.dead_letter(job, "execution not found")
                    logger.error("execution not found execution_id=%s", job.execution_id)
                else:
                    await queue.ack(job)
                    logger.info(
                        "execution processed execution_id=%s status=%s attempts=%s",
                        result.id,
                        result.status.value,
                        result.attempts,
                    )
            except Exception as exc:
                logger.exception("worker processing error execution_id=%s", job.execution_id)
                await queue.dead_letter(job, str(exc))
        except asyncio.CancelledError:
            logger.info("automation worker stopping")
            raise
        except Exception:
            logger.exception("worker loop error")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
