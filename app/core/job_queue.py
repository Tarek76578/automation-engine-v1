from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.core.config import settings


@dataclass(frozen=True)
class Job:
    execution_id: UUID
    job_id: UUID = field(default_factory=uuid4)
    claim_token: str | None = None


class Queue:
    async def enqueue(self, job: Job, delay_seconds: float = 0.0) -> None:
        raise NotImplementedError

    async def dequeue(self) -> Job:
        raise NotImplementedError

    async def ack(self, job: Job) -> None:
        raise NotImplementedError

    async def dead_letter(self, job: Job, reason: str) -> None:
        raise NotImplementedError

    async def recover(self) -> int:
        return 0


class InMemoryQueue(Queue):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self.dead_letters: list[tuple[Job, str]] = []

    async def enqueue(self, job: Job, delay_seconds: float = 0.0) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await self._queue.put(job)

    async def dequeue(self) -> Job:
        return await self._queue.get()

    async def ack(self, job: Job) -> None:
        self._queue.task_done()

    async def dead_letter(self, job: Job, reason: str) -> None:
        self.dead_letters.append((job, reason))
        self._queue.task_done()


def _build_queue() -> Queue:
    if not settings.redis_url:
        return InMemoryQueue()

    from redis.asyncio import Redis

    from app.integrations.redis_queue import RedisQueue

    return RedisQueue(Redis.from_url(settings.redis_url))


queue = _build_queue()
