import pytest

from app.core.job_queue import InMemoryQueue, Job


@pytest.mark.asyncio
async def test_in_memory_queue_round_trip() -> None:
    from uuid import uuid4

    queue = InMemoryQueue()
    execution_id = uuid4()
    job = Job(execution_id=execution_id)
    await queue.enqueue(job)
    received = await queue.dequeue()
    await queue.ack(received)
    assert received.execution_id == execution_id
