from __future__ import annotations

import json
from uuid import UUID

from redis.asyncio import Redis

from app.core.job_queue import Job, Queue


class RedisQueue(Queue):
    def __init__(
        self,
        redis: Redis,
        key: str = "automation:jobs",
        processing_key: str = "automation:jobs:processing",
    ) -> None:
        self.redis = redis
        self.key = key
        self.processing_key = processing_key

    @staticmethod
    def _encode(job: Job) -> str:
        return json.dumps(
            {
                "execution_id": str(job.execution_id),
                "job_id": str(job.job_id),
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _decode(raw: str | bytes) -> Job:
        payload = json.loads(raw)
        return Job(
            execution_id=UUID(payload["execution_id"]),
            job_id=UUID(payload["job_id"]),
        )

    async def enqueue(self, job: Job, delay_seconds: float = 0.0) -> None:
        if delay_seconds > 0:
            await self.redis.zadd(
                f"{self.key}:delayed",
                {self._encode(job): float(await self.redis.time()[0]) + delay_seconds},
            )
            return
        await self.redis.rpush(self.key, self._encode(job))

    async def _promote_due(self) -> None:
        delayed_key = f"{self.key}:delayed"
        now = float((await self.redis.time())[0])
        items = await self.redis.zrangebyscore(delayed_key, "-inf", now, start=0, num=50)
        if not items:
            return
        async with self.redis.pipeline(transaction=True) as pipe:
            for raw in items:
                pipe.zrem(delayed_key, raw)
                pipe.rpush(self.key, raw)
            await pipe.execute()

    async def dequeue(self) -> Job:
        while True:
            await self._promote_due()
            raw = await self.redis.brpoplpush(self.key, self.processing_key, timeout=1)
            if raw:
                return self._decode(raw)

    async def ack(self, job: Job) -> None:
        await self.redis.lrem(self.processing_key, 1, self._encode(job))

    async def recover(self) -> int:
        items = await self.redis.lrange(self.processing_key, 0, -1)
        if not items:
            return 0
        async with self.redis.pipeline(transaction=True) as pipe:
            for raw in items:
                pipe.rpush(self.key, raw)
                pipe.lrem(self.processing_key, 1, raw)
            await pipe.execute()
        return len(items)
