from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any, Protocol


class ExecutionQueue(Protocol):
    def enqueue(self, execution_id: str, payload: dict[str, Any]) -> None: ...
    def dequeue(self) -> tuple[str, dict[str, Any]] | None: ...


class InMemoryExecutionQueue:
    """Reference queue; Redis Streams can implement the same contract later."""

    def __init__(self) -> None:
        self._items: deque[tuple[str, dict[str, Any]]] = deque()
        self._lock = Lock()

    def enqueue(self, execution_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items.append((execution_id, payload))

    def dequeue(self) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            return self._items.popleft() if self._items else None


execution_queue = InMemoryExecutionQueue()
