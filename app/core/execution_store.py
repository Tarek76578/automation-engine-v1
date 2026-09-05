from __future__ import annotations

from threading import Lock

from app.models.execution import Execution


class ExecutionStore:
    """Small in-process store used as the Phase 2 reference implementation.

    The interface is intentionally persistence-agnostic so PostgreSQL/Redis can
    replace it without changing the API or orchestration contracts.
    """

    def __init__(self) -> None:
        self._items: dict[str, Execution] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = Lock()

    def create(self, execution: Execution, idempotency_key: str | None = None) -> Execution:
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return self._items[self._idempotency[idempotency_key]]
            key = str(execution.id)
            self._items[key] = execution
            if idempotency_key:
                self._idempotency[idempotency_key] = key
            return execution

    def get(self, execution_id: str) -> Execution | None:
        return self._items.get(execution_id)


store = ExecutionStore()
