from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from app.core.job_queue import Job
from app.integrations.redis_queue import RedisQueue

import pytest
import pytest_asyncio
from redis.asyncio import Redis


@pytest_asyncio.fixture
async def redis_queue() -> RedisQueue:
    url = os.getenv("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL is not configured")

    redis = Redis.from_url(url, decode_responses=True)
    await redis.ping()
    prefix = f"automation:test:{uuid4().hex}"
    queue = RedisQueue(
        redis,
        key=f"{prefix}:jobs",
        processing_key=f"{prefix}:processing",
        dead_letter_key=f"{prefix}:dead-letter",
        visibility_timeout_seconds=1,
        reclaim_batch_size=10,
    )
    try:
        yield queue
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_redis_queue_ack_uses_claim_token(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job)

    first = await redis_queue.dequeue()
    await asyncio.sleep(1.1)
    assert await redis_queue.recover() == 1

    second = await redis_queue.dequeue()
    assert first.job_id == second.job_id
    assert first.claim_token != second.claim_token

    await redis_queue.ack(first)
    assert await redis_queue.redis.llen(redis_queue.processing_key) == 1

    await redis_queue.ack(second)
    assert await redis_queue.redis.llen(redis_queue.processing_key) == 0


@pytest.mark.asyncio
async def test_redis_queue_delayed_enqueue_is_promoted(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job, delay_seconds=0.1)

    await asyncio.sleep(0.15)
    received = await redis_queue.dequeue()
    assert received.execution_id == job.execution_id
    await redis_queue.ack(received)
