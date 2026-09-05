from __future__ import annotations

from typing import Protocol

from app.models.execution import Execution


class ExecutionRepository(Protocol):
    async def save(self, execution: Execution) -> Execution: ...

    async def get(self, execution_id: str) -> Execution | None: ...


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Execution] = {}

    async def save(self, execution: Execution) -> Execution:
        self._items[str(execution.id)] = execution
        return execution

    async def get(self, execution_id: str) -> Execution | None:
        return self._items.get(execution_id)


execution_repository = InMemoryExecutionRepository()
