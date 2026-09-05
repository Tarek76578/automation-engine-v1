from __future__ import annotations

import json
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.job_queue import Job, Queue


class RedisQueue(Queue):
    def __init__(
        self,
        redis: Redis,
        key: str = "automation:jobs",
        processing_key: str = "automation:jobs:processing",
        dead_letter_key: str = "automation:jobs:dead-letter",
        visibility_timeout_seconds: int = 300,
        reclaim_batch_size: int = 100,
    ) -> None:
        self.redis = redis
        self.key = key
        self.processing_key = processing_key
        self.dead_letter_key = dead_letter_key
        self.delayed_key = f"{key}:delayed"
        self.claims_key = f"{processing_key}:claims"
        self.visibility_timeout_seconds = max(1, visibility_timeout_seconds)
        self.reclaim_batch_size = max(1, reclaim_batch_size)

    @staticmethod
    def _encode(job: Job) -> str:
        payload = {"execution_id": str(job.execution_id), "job_id": str(job.job_id)}
        if job.claim_token is not None:
            payload["claim_token"] = job.claim_token
        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str | bytes) -> Job:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        return Job(
            execution_id=UUID(payload["execution_id"]),
            job_id=UUID(payload["job_id"]),
            claim_token=payload.get("claim_token"),
        )

    @staticmethod
    def _without_claim(job: Job) -> Job:
        return Job(execution_id=job.execution_id, job_id=job.job_id)

    async def enqueue(self, job: Job, delay_seconds: float = 0.0) -> None:
        payload = self._encode(self._without_claim(job))
        if delay_seconds > 0:
            now = float((await self.redis.time())[0])
            await self.redis.zadd(self.delayed_key, {payload: now + delay_seconds})
            return
        await self.redis.rpush(self.key, payload)

    async def _promote_due(self) -> None:
        now = float((await self.redis.time())[0])
        items = await self.redis.zrangebyscore(
            self.delayed_key, "-inf", now, start=0, num=self.reclaim_batch_size
        )
        if not items:
            return
        async with self.redis.pipeline(transaction=True) as pipe:
            for raw in items:
                pipe.zrem(self.delayed_key, raw)
                pipe.rpush(self.key, raw)
            await pipe.execute()

    async def dequeue(self) -> Job:
        while True:
            await self._promote_due()
            raw = await self.redis.brpoplpush(self.key, self.processing_key, timeout=1)
            if raw is None:
                continue

            job = self._decode(raw)
            claim_token = uuid4().hex
            claimed = Job(job.execution_id, job.job_id, claim_token)
            payload = self._encode(claimed)
            deadline = float((await self.redis.time())[0]) + self.visibility_timeout_seconds

            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lrem(self.processing_key, 1, raw)
                pipe.rpush(self.processing_key, payload)
                pipe.hset(self.claims_key, str(job.job_id), deadline)
                await pipe.execute()
            return claimed

    async def ack(self, job: Job) -> None:
        if job.claim_token is None:
            return
        payload = self._encode(job)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, payload)
            pipe.hdel(self.claims_key, str(job.job_id))
            await pipe.execute()

    async def dead_letter(self, job: Job, reason: str) -> None:
        if job.claim_token is None:
            return
        record = json.dumps(
            {"job": json.loads(self._encode(self._without_claim(job))), "reason": reason},
            separators=(",", ":"),
        )
        payload = self._encode(job)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, payload)
            pipe.hdel(self.claims_key, str(job.job_id))
            pipe.rpush(self.dead_letter_key, record)
            await pipe.execute()

    async def recover(self) -> int:
        now = float((await self.redis.time())[0])
        recovered = 0
        processing = await self.redis.lrange(self.processing_key, 0, -1)
        for raw in processing[: self.reclaim_batch_size]:
            job = self._decode(raw)
            deadline = await self.redis.hget(self.claims_key, str(job.job_id))
            if deadline is None or float(deadline) <= now:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.lrem(self.processing_key, 1, raw)
                    pipe.hdel(self.claims_key, str(job.job_id))
                    pipe.rpush(self.key, self._encode(self._without_claim(job)))
                    await pipe.execute()
                recovered += 1
        return recovered
