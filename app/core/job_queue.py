from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.core.config import settings


@dataclass(frozen=True)
class Job:
    execution_id: UUID


class Queue:
    async def enqueue(self, job: Job) -> None:
        raise NotImplementedError

    async def dequeue(self) -> Job:
        raise NotImplementedError


class InMemoryQueue(Queue):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()

    async def enqueue(self, job: Job) -> None:
        await self._queue.put(job)

    async def dequeue(self) -> Job:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()


def _build_queue() -> Queue:
    if not settings.redis_url:
        return InMemoryQueue()
    from redis.asyncio import Redis

    from app.integrations.redis_queue import RedisQueue

    return RedisQueue(Redis.from_url(settings.redis_url))


queue = _build_queue()
