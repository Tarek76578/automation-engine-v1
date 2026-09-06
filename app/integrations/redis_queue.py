from __future__ import annotations

import json
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.job_queue import Job, Queue


_ACK_SCRIPT = """
local claim = redis.call('HGET', KEYS[2], ARGV[1])
if claim ~= ARGV[3] then
    return 0
end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[2])
if removed == 1 then
    redis.call('HDEL', KEYS[2], ARGV[1])
end
return removed
"""

_RECOVER_WITH_CLAIM_SCRIPT = """
local claim = redis.call('HGET', KEYS[2], ARGV[1])
if claim ~= ARGV[3] then
    return 0
end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[2])
if removed == 1 then
    redis.call('HDEL', KEYS[2], ARGV[1])
    redis.call('RPUSH', KEYS[3], ARGV[2])
end
return removed
"""

_RECOVER_WITHOUT_CLAIM_SCRIPT = """
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 1 then
    return 0
end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[2])
if removed == 1 then
    redis.call('RPUSH', KEYS[3], ARGV[2])
end
return removed
"""


class RedisQueue(Queue):
    """Redis-backed at-least-once queue with crash-safe visibility recovery.

    Jobs are atomically moved from the ready list to the processing list with
    BLMOVE. A separate claim record carries the visibility deadline and token.
    ACK and recovery use Lua scripts so an ACK cannot race with recovery and
    accidentally resurrect an already-completed job.
    """

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

    async def enqueue(self, job: Job, delay_seconds: float = 0.0) -> None:
        payload = self._encode(job)
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
            raw = await self.redis.blmove(
                self.key, self.processing_key, timeout=1, src="RIGHT", dest="LEFT"
            )
            if raw is None:
                continue

            job = self._decode(raw)
            claim_token = uuid4().hex
            deadline = float((await self.redis.time())[0]) + self.visibility_timeout_seconds
            claim = json.dumps(
                {"token": claim_token, "deadline": deadline}, separators=(",", ":")
            )
            await self.redis.hset(self.claims_key, str(job.job_id), claim)
            return Job(job.execution_id, job.job_id, claim_token)

    async def ack(self, job: Job) -> None:
        if job.claim_token is None:
            return
        payload = self._encode(job)
        claim = await self.redis.hget(self.claims_key, str(job.job_id))
        if claim is None:
            return
        try:
            claim_data = json.loads(claim)
        except (TypeError, ValueError):
            return
        if claim_data.get("token") != job.claim_token:
            return
        await self.redis.eval(
            _ACK_SCRIPT,
            2,
            self.processing_key,
            self.claims_key,
            str(job.job_id),
            payload,
            claim,
        )

    async def dead_letter(self, job: Job, reason: str) -> None:
        if job.claim_token is None:
            return
        payload = self._encode(job)
        record = json.dumps(
            {"job": json.loads(payload), "reason": reason}, separators=(",", ":")
        )
        claim = await self.redis.hget(self.claims_key, str(job.job_id))
        if claim is None:
            return
        try:
            claim_data = json.loads(claim)
        except (TypeError, ValueError):
            return
        if claim_data.get("token") != job.claim_token:
            return
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, payload)
            pipe.hdel(self.claims_key, str(job.job_id))
            pipe.rpush(self.dead_letter_key, record)
            await pipe.execute()

    async def recover(self) -> int:
        now = float((await self.redis.time())[0])
        recovered = 0
        processing = await self.redis.lrange(self.processing_key, 0, self.reclaim_batch_size - 1)
        for raw in processing:
            job = self._decode(raw)
            claim = await self.redis.hget(self.claims_key, str(job.job_id))
            if claim is None:
                recovered += int(
                    await self.redis.eval(
                        _RECOVER_WITHOUT_CLAIM_SCRIPT,
                        3,
                        self.processing_key,
                        self.claims_key,
                        self.key,
                        str(job.job_id),
                        raw,
                    )
                )
                continue
            try:
                claim_data = json.loads(claim)
                deadline = float(claim_data["deadline"])
            except (TypeError, ValueError, KeyError):
                deadline = 0.0
            if deadline <= now:
                recovered += int(
                    await self.redis.eval(
                        _RECOVER_WITH_CLAIM_SCRIPT,
                        3,
                        self.processing_key,
                        self.claims_key,
                        self.key,
                        str(job.job_id),
                        raw,
                        claim,
                    )
                )
        return recovered
