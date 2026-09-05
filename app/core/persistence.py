from __future__ import annotations

from typing import Protocol

from app.models.execution import Execution


class ExecutionRepository(Protocol):
    async def save(self, execution: Execution) -> Execution: ...

    async def get(self, execution_id: str) -> Execution | None: ...

    async def get_by_idempotency_key(self, key: str) -> Execution | None: ...


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Execution] = {}
        self._idempotency: dict[str, str] = {}

    async def save(self, execution: Execution) -> Execution:
        execution_id = str(execution.id)
        existing_key = execution.idempotency_key
        if existing_key:
            existing_id = self._idempotency.get(existing_key)
            if existing_id and existing_id != execution_id:
                return self._items[existing_id]
            self._idempotency[existing_key] = execution_id
        self._items[execution_id] = execution
        return execution

    async def get(self, execution_id: str) -> Execution | None:
        return self._items.get(execution_id)

    async def get_by_idempotency_key(self, key: str) -> Execution | None:
        execution_id = self._idempotency.get(key)
        return self._items.get(execution_id) if execution_id else None


execution_repository = InMemoryExecutionRepository()
