from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.job_queue import Job
from app.integrations.redis_queue import RedisQueue


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
        await redis.delete(
            queue.key,
            queue.processing_key,
            queue.delayed_key,
            queue.claims_key,
            queue.dead_letter_key,
        )
        await redis.aclose()


@pytest.mark.asyncio
async def test_ack_removes_claimed_job(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job)
    claimed = await redis_queue.dequeue()

    await redis_queue.ack(claimed)

    assert await redis_queue.redis.llen(redis_queue.processing_key) == 0
    assert await redis_queue.redis.hget(redis_queue.claims_key, str(job.job_id)) is None


@pytest.mark.asyncio
async def test_expired_job_is_recovered(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job)
    first = await redis_queue.dequeue()
    await asyncio.sleep(1.1)

    assert await redis_queue.recover() == 1
    second = await redis_queue.dequeue()
    assert second.job_id == first.job_id
    assert second.claim_token != first.claim_token
    await redis_queue.ack(second)


@pytest.mark.asyncio
async def test_ack_after_recovery_cannot_resurrect_job(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job)
    claimed = await redis_queue.dequeue()
    await asyncio.sleep(1.1)

    assert await redis_queue.recover() == 1
    await redis_queue.ack(claimed)

    assert await redis_queue.redis.llen(redis_queue.processing_key) == 0
    assert await redis_queue.redis.llen(redis_queue.key) == 1
    recovered = await redis_queue.dequeue()
    assert recovered.job_id == job.job_id
    await redis_queue.ack(recovered)


@pytest.mark.asyncio
async def test_processing_job_without_claim_is_recovered(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    raw = redis_queue._encode(job)
    await redis_queue.redis.rpush(redis_queue.processing_key, raw)

    assert await redis_queue.recover() == 1
    recovered = await redis_queue.dequeue()
    assert recovered.job_id == job.job_id
    await redis_queue.ack(recovered)


@pytest.mark.asyncio
async def test_delayed_job_is_promoted(redis_queue: RedisQueue) -> None:
    job = Job(execution_id=uuid4())
    await redis_queue.enqueue(job, delay_seconds=0.1)
    await asyncio.sleep(0.15)

    received = await redis_queue.dequeue()

    assert received.execution_id == job.execution_id
    await redis_queue.ack(received)
