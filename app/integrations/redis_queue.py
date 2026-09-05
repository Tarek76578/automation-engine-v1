from __future__ import annotations

import json
from uuid import UUID, uuid4

from app.core.job_queue import Job, Queue
from redis.asyncio import Redis


_PROMOTE_DUE_LUA = """
local items = redis.call(
  'ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2]
)
for _, raw in ipairs(items) do
  if redis.call('ZREM', KEYS[1], raw) == 1 then
    redis.call('RPUSH', KEYS[2], raw)
  end
end
return #items
"""

_RECLAIM_LUA = """
local items = redis.call(
  'ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2]
)
local reclaimed = 0
for _, raw in ipairs(items) do
  if redis.call('ZREM', KEYS[1], raw) == 1 then
    redis.call('LREM', KEYS[2], 1, raw)
    redis.call('RPUSH', KEYS[3], raw)
    reclaimed = reclaimed + 1
  end
end
return reclaimed
"""


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
        payload = {
            "execution_id": str(job.execution_id),
            "job_id": str(job.job_id),
        }
        if job.claim_token is not None:
            payload["claim_token"] = job.claim_token
        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str | bytes) -> Job:
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
            await self.redis.zadd(
                self.delayed_key, {payload: now + delay_seconds}
            )
            return
        await self.redis.rpush(self.key, payload)

    async def _promote_due(self) -> None:
        now = float((await self.redis.time())[0])
        await self.redis.eval(
            _PROMOTE_DUE_LUA,
            2,
            self.delayed_key,
            self.key,
            now,
            self.reclaim_batch_size,
        )

    async def dequeue(self) -> Job:
        while True:
            await self._promote_due()
            raw = await self.redis.blmove(
                self.key,
                self.processing_key,
                "RIGHT",
                "LEFT",
                1,
            )
            if not raw:
                continue

            claim_token = uuid4().hex
            claimed_at = float((await self.redis.time())[0])
            claimed_job = self._decode(raw)
            claimed_job = Job(
                execution_id=claimed_job.execution_id,
                job_id=claimed_job.job_id,
                claim_token=claim_token,
            )
            processing_payload = self._encode(claimed_job)

            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lrem(self.processing_key, 1, raw)
                pipe.rpush(self.processing_key, processing_payload)
                pipe.zadd(
                    self.claims_key,
                    {
                        processing_payload:
                            claimed_at + self.visibility_timeout_seconds
                    },
                )
                await pipe.execute()
            return claimed_job

    async def ack(self, job: Job) -> None:
        if job.claim_token is None:
            return
        payload = self._encode(job)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, payload)
            pipe.zrem(self.claims_key, payload)
            await pipe.execute()

    async def dead_letter(self, job: Job, reason: str) -> None:
        if job.claim_token is None:
            return
        payload = self._encode(job)
        record = json.dumps(
            {
                "job": json.loads(self._encode(self._without_claim(job))),
                "reason": reason,
            },
            separators=(",", ":"),
        )
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, payload)
            pipe.zrem(self.claims_key, payload)
            pipe.rpush(self.dead_letter_key, record)
            await pipe.execute()

    async def recover(self) -> int:
        now = float((await self.redis.time())[0])
        return int(
            await self.redis.eval(
                _RECLAIM_LUA,
                3,
                self.claims_key,
                self.processing_key,
                self.key,
                now,
                self.reclaim_batch_size,
            )
        )
