from datetime import datetime
from uuid import UUID

from app.models.execution import Execution, ExecutionStatus

from sqlalchemy import JSON, DateTime, String, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    idempotency_key: Mapped[str | None] = mapped_column(
        String(200), unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostgresExecutionRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    "ALTER TABLE executions "
                    "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(200)"
                )
            )
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_executions_idempotency_key "
                    "ON executions (idempotency_key)"
                )
            )
        self._schema_ready = True

    async def save(self, execution: Execution) -> Execution:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = ExecutionRow(
                id=execution.id,
                workflow=execution.workflow,
                status=execution.status.value,
                input=execution.input,
                output=execution.output,
                error=execution.error,
                attempts=execution.attempts,
                idempotency_key=execution.idempotency_key,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
            )
            try:
                await session.merge(row)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if not execution.idempotency_key:
                    raise
                result = await session.execute(
                    select(ExecutionRow).where(
                        ExecutionRow.idempotency_key == execution.idempotency_key
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                return self._to_execution(existing)
        return execution

    async def get(self, execution_id: str) -> Execution | None:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = await session.get(ExecutionRow, UUID(execution_id))
            return self._to_execution(row) if row is not None else None

    async def get_by_idempotency_key(self, key: str) -> Execution | None:
        await self.ensure_schema()
        async with self.sessions() as session:
            result = await session.execute(
                select(ExecutionRow).where(ExecutionRow.idempotency_key == key)
            )
            row = result.scalar_one_or_none()
            return self._to_execution(row) if row is not None else None

    @staticmethod
    def _to_execution(row: ExecutionRow) -> Execution:
        return Execution(
            id=row.id,
            workflow=row.workflow,
            status=ExecutionStatus(row.status),
            input=row.input,
            output=row.output,
            error=row.error,
            attempts=row.attempts,
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
