from __future__ import annotations

import json
from uuid import UUID

from redis.asyncio import Redis

from app.core.job_queue import Job, Queue


class RedisQueue(Queue):
    def __init__(self, redis: Redis, key: str = "automation:jobs") -> None:
        self.redis = redis
        self.key = key

    async def enqueue(self, job: Job) -> None:
        await self.redis.rpush(self.key, json.dumps({"execution_id": str(job.execution_id)}))

    async def dequeue(self) -> Job:
        _, raw = await self.redis.blpop(self.key)
        payload = json.loads(raw)
        return Job(execution_id=UUID(payload["execution_id"]))
