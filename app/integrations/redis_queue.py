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
  redis.call('LPUSH', KEYS[2], raw)
  redis.call('ZREM', KEYS[1], raw)
end
return #items
"""

_RECLAIM_LUA = """
local items = redis.call(
  'ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2]
)
for _, raw in ipairs(items) do
  redis.call('LPUSH', KEYS[2], raw)
  redis.call('ZREM', KEYS[1], raw)
end
return #items
"""
