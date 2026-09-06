from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


class MetaCredentialError(RuntimeError):
    """Raised when Meta credential storage is unavailable or corrupted."""


class CredentialStore(Protocol):
    async def initialize(self) -> None: ...

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None: ...

    async def load(self) -> dict[str, str] | None: ...

    async def save_oauth_state(self, state_hash: str, expires_at: datetime) -> None: ...

    async def consume_oauth_state(self, state_hash: str, now: datetime) -> bool: ...


class EncryptedCredentialCodec:
    """Small Fernet codec used to keep access tokens encrypted at rest."""

    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise MetaCredentialError("META_OAUTH_ENCRYPTION_KEY is required")
        try:
            self._fernet = Fernet(encryption_key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise MetaCredentialError("META_OAUTH_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise MetaCredentialError("Stored Meta credential could not be decrypted") from exc


class CredentialBase(DeclarativeBase):
    pass


class MetaCredentialRow(CredentialBase):
    __tablename__ = "meta_credentials"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(200))
    page_name: Mapped[str] = mapped_column(String(200), default="")
    access_token_ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetaOAuthStateRow(CredentialBase):
    __tablename__ = "meta_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._credentials: dict[str, str] | None = None
        self._oauth_states: dict[str, datetime] = {}

    async def initialize(self) -> None:
        return None

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None:
        self._credentials = {"page_id": page_id, "page_name": page_name, "page_access_token": page_access_token}

    async def load(self) -> dict[str, str] | None:
        return dict(self._credentials) if self._credentials else None

    async def save_oauth_state(self, state_hash: str, expires_at: datetime) -> None:
        self._oauth_states[state_hash] = expires_at

    async def consume_oauth_state(self, state_hash: str, now: datetime) -> bool:
        expires_at = self._oauth_states.pop(state_hash, None)
        return expires_at is not None and expires_at >= now


class UnavailableCredentialStore:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def initialize(self) -> None:
        raise MetaCredentialError(self.reason)

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None:
        raise MetaCredentialError(self.reason)

    async def load(self) -> dict[str, str] | None:
        raise MetaCredentialError(self.reason)

    async def save_oauth_state(self, state_hash: str, expires_at: datetime) -> None:
        raise MetaCredentialError(self.reason)

    async def consume_oauth_state(self, state_hash: str, now: datetime) -> bool:
        raise MetaCredentialError(self.reason)


class PostgresCredentialStore:
    """Persist Meta credentials and one-time OAuth state in PostgreSQL."""

    def __init__(self, database_url: str, encryption_key: str) -> None:
        self._codec = EncryptedCredentialCodec(encryption_key)
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._schema_ready = False

    async def initialize(self) -> None:
        if self._schema_ready:
            return
        async with self.engine.begin() as connection:
            await connection.run_sync(CredentialBase.metadata.create_all)
        self._schema_ready = True

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None:
        await self.initialize()
        now = datetime.now(UTC)
        ciphertext = self._codec.encrypt(page_access_token)
        async with self.sessions() as session:
            row = await session.get(MetaCredentialRow, "default")
            if row is None:
                row = MetaCredentialRow(key="default", page_id=page_id, page_name=page_name, access_token_ciphertext=ciphertext, created_at=now, updated_at=now)
                session.add(row)
            else:
                row.page_id = page_id
                row.page_name = page_name
                row.access_token_ciphertext = ciphertext
                row.updated_at = now
            await session.commit()

    async def load(self) -> dict[str, str] | None:
        await self.initialize()
        async with self.sessions() as session:
            result = await session.execute(select(MetaCredentialRow).where(MetaCredentialRow.key == "default"))
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return {"page_id": row.page_id, "page_name": row.page_name, "page_access_token": self._codec.decrypt(row.access_token_ciphertext)}

    async def save_oauth_state(self, state_hash: str, expires_at: datetime) -> None:
        await self.initialize()
        now = datetime.now(UTC)
        async with self.sessions() as session:
            session.add(MetaOAuthStateRow(state_hash=state_hash, expires_at=expires_at, created_at=now))
            await session.commit()

    async def consume_oauth_state(self, state_hash: str, now: datetime) -> bool:
        await self.initialize()
        async with self.sessions() as session:
            result = await session.execute(select(MetaOAuthStateRow).where(MetaOAuthStateRow.state_hash == state_hash))
            row = result.scalar_one_or_none()
            if row is None or row.expires_at < now:
                if row is not None:
                    await session.delete(row)
                    await session.commit()
                return False
            await session.execute(delete(MetaOAuthStateRow).where(MetaOAuthStateRow.state_hash == state_hash))
            await session.commit()
            return True


def build_meta_credential_store() -> CredentialStore:
    if not settings.database_url:
        return InMemoryCredentialStore()
    if not settings.meta_oauth_encryption_key:
        return UnavailableCredentialStore("META_OAUTH_ENCRYPTION_KEY is required when DATABASE_URL is configured")
    try:
        return PostgresCredentialStore(settings.database_url, settings.meta_oauth_encryption_key)
    except MetaCredentialError as exc:
        return UnavailableCredentialStore(str(exc))
