from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.execution import Execution, ExecutionStatus


class Base(DeclarativeBase):
    pass


class ExecutionRow(Base):
    __tablename__ = "executions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workflow: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostgresExecutionRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def save(self, execution: Execution) -> Execution:
        async with self.sessions() as session:
            row = ExecutionRow(
                id=execution.id,
                workflow=execution.workflow,
                status=execution.status.value,
                input=execution.input,
                output=execution.output,
                error=execution.error,
                attempts=execution.attempts,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
            )
            await session.merge(row)
            await session.commit()
        return execution

    async def get(self, execution_id: str) -> Execution | None:
        async with self.sessions() as session:
            row = await session.get(ExecutionRow, UUID(execution_id))
            if row is None:
                return None
            return Execution(
                id=row.id,
                workflow=row.workflow,
                status=ExecutionStatus(row.status),
                input=row.input,
                output=row.output,
                error=row.error,
                attempts=row.attempts,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
