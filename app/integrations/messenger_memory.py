from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


@dataclass(frozen=True)
class ConversationMessage:
    conversation_key: str
    direction: str
    sender_id: str
    message: str
    event_id: str | None = None
    created_at: datetime | None = None


class MemoryBase(DeclarativeBase):
    pass


class MessengerMessageRow(MemoryBase):
    __tablename__ = "messenger_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_key: Mapped[str] = mapped_column(String(400), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    sender_id: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(10000))
    event_id: Mapped[str | None] = mapped_column(String(400), unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InMemoryMessengerMemory:
    """Bounded fallback used when no database is configured."""

    def __init__(self, max_messages_per_conversation: int = 50) -> None:
        self.max_messages_per_conversation = max_messages_per_conversation
        self._items: dict[str, list[ConversationMessage]] = {}
        self._events: set[str] = set()

    async def append(self, message: ConversationMessage) -> bool:
        if message.event_id and message.event_id in self._events:
            return False
        self._items.setdefault(message.conversation_key, []).append(message)
        self._items[message.conversation_key] = self._items[message.conversation_key][-self.max_messages_per_conversation:]
        if message.event_id:
            self._events.add(message.event_id)
        return True

    async def recent(self, conversation_key: str, limit: int = 12) -> list[ConversationMessage]:
        return list(self._items.get(conversation_key, []))[-limit:]


class PostgresMessengerMemory:
    """Durable conversation store; message bodies contain no access tokens or secrets."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self.engine.begin() as connection:
            await connection.run_sync(MemoryBase.metadata.create_all)
        self._schema_ready = True

    async def append(self, message: ConversationMessage) -> bool:
        await self._ensure_schema()
        async with self.sessions() as session:
            if message.event_id:
                existing = await session.execute(
                    select(MessengerMessageRow.id).where(MessengerMessageRow.event_id == message.event_id)
                )
                if existing.scalar_one_or_none() is not None:
                    return False
            row = MessengerMessageRow(
                conversation_key=message.conversation_key,
                direction=message.direction,
                sender_id=message.sender_id,
                message=message.message,
                event_id=message.event_id,
                created_at=message.created_at or datetime.now(UTC),
            )
            session.add(row)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                if message.event_id:
                    existing = await session.execute(
                        select(MessengerMessageRow.id).where(MessengerMessageRow.event_id == message.event_id)
                    )
                    if existing.scalar_one_or_none() is not None:
                        return False
                raise
        return True

    async def recent(self, conversation_key: str, limit: int = 12) -> list[ConversationMessage]:
        await self._ensure_schema()
        safe_limit = max(1, min(limit, 50))
        async with self.sessions() as session:
            result = await session.execute(
                select(MessengerMessageRow)
                .where(MessengerMessageRow.conversation_key == conversation_key)
                .order_by(MessengerMessageRow.created_at.desc(), MessengerMessageRow.id.desc())
                .limit(safe_limit)
            )
            rows = list(result.scalars())
        return [
            ConversationMessage(row.conversation_key, row.direction, row.sender_id, row.message, row.event_id, row.created_at)
            for row in reversed(rows)
        ]


class MessengerMemory:
    def __init__(self, store: InMemoryMessengerMemory | PostgresMessengerMemory | None = None) -> None:
        self.store = store or (PostgresMessengerMemory(settings.database_url) if settings.database_url else InMemoryMessengerMemory())

    async def record_inbound(self, page_id: str, sender_id: str, message: str, event_id: str, timestamp: Any = None) -> bool:
        return await self.store.append(ConversationMessage(
            conversation_key=conversation_key(page_id, sender_id), direction="inbound", sender_id=sender_id,
            message=message, event_id=event_id, created_at=_timestamp(timestamp),
        ))

    async def record_outbound(self, page_id: str, recipient_id: str, message: str, execution_id: str | None = None) -> bool:
        return await self.store.append(ConversationMessage(
            conversation_key=conversation_key(page_id, recipient_id), direction="outbound", sender_id=page_id,
            message=message, event_id=f"execution:{execution_id}" if execution_id else None,
            created_at=datetime.now(UTC),
        ))

    async def recent_context(self, page_id: str, sender_id: str, limit: int = 12) -> list[dict[str, str]]:
        messages = await self.store.recent(conversation_key(page_id, sender_id), limit)
        return [{"direction": item.direction, "message": item.message} for item in messages]


def conversation_key(page_id: str, sender_id: str) -> str:
    return f"meta:{page_id}:{sender_id}"


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, UTC)
    return None


messenger_memory = MessengerMemory()
