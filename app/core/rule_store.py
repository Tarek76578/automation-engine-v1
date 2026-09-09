from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, Integer, String, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings
from app.models.rule import AutomationRule


class RuleBase(DeclarativeBase):
    pass


class RuleRow(RuleBase):
    __tablename__ = "automation_rules"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)


class InMemoryRuleStore:
    def __init__(self) -> None:
        self._items: dict[str, AutomationRule] = {}

    async def list(self) -> list[AutomationRule]:
        return sorted(self._items.values(), key=lambda r: r.priority, reverse=True)

    async def get(self, rule_id: UUID) -> AutomationRule | None:
        return self._items.get(str(rule_id))

    async def save(self, rule: AutomationRule) -> AutomationRule:
        self._items[str(rule.id)] = rule
        return rule

    async def delete(self, rule_id: UUID) -> bool:
        return self._items.pop(str(rule_id), None) is not None


class PostgresRuleStore:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self.engine.begin() as connection:
            await connection.run_sync(RuleBase.metadata.create_all)
            await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automation_rules_priority ON automation_rules (priority DESC)"))
        self._schema_ready = True

    async def list(self) -> list[AutomationRule]:
        await self.ensure_schema()
        async with self.sessions() as session:
            result = await session.execute(select(RuleRow).order_by(RuleRow.priority.desc(), RuleRow.name.asc()))
            return [AutomationRule.model_validate(row.definition) for row in result.scalars()]

    async def get(self, rule_id: UUID) -> AutomationRule | None:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = await session.get(RuleRow, rule_id)
            return AutomationRule.model_validate(row.definition) if row else None

    async def save(self, rule: AutomationRule) -> AutomationRule:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = RuleRow(id=rule.id, name=rule.name, enabled=rule.enabled, priority=rule.priority, definition=rule.model_dump(mode="json"))
            await session.merge(row)
            await session.commit()
        return rule

    async def delete(self, rule_id: UUID) -> bool:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = await session.get(RuleRow, rule_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


rule_store = PostgresRuleStore(settings.database_url) if settings.database_url else InMemoryRuleStore()
