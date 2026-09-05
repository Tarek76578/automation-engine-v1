from uuid import uuid4

from app.core.job_queue import InMemoryQueue, Job

import pytest


@pytest.mark.asyncio
async def test_in_memory_queue_round_trip() -> None:
    queue = InMemoryQueue()
    execution_id = uuid4()
    job = Job(execution_id=execution_id)
    await queue.enqueue(job)
    received = await queue.dequeue()
    await queue.ack(received)
    assert received.execution_id == execution_id
