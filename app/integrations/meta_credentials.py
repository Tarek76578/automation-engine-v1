from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


class MetaCredentialError(RuntimeError):
    """Raised when Meta credential storage is unavailable or corrupted."""


class CredentialStore(Protocol):
    async def initialize(self) -> None: ...

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None: ...

    async def load(self) -> dict[str, str] | None: ...


class EncryptedCredentialCodec:
    """Small Fernet codec used to keep access tokens encrypted at rest."""

    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise MetaCredentialError("META_OAUTH_ENCRYPTION_KEY is required")
        try:
            self._fernet = Fernet(encryption_key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise MetaCredentialError(
                "META_OAUTH_ENCRYPTION_KEY must be a valid Fernet key"
            ) from exc

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


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._credentials: dict[str, str] | None = None

    async def initialize(self) -> None:
        return None

    async def save(self, page_id: str, page_name: str, page_access_token: str) -> None:
        self._credentials = {
            "page_id": page_id,
            "page_name": page_name,
            "page_access_token": page_access_token,
        }

    async def load(self) -> dict[str, str] | None:
        return dict(self._credentials) if self._credentials else None


class PostgresCredentialStore:
    """Persist one Meta Page credential set encrypted at rest with Fernet."""

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
        now = datetime.now(timezone.utc)
        ciphertext = self._codec.encrypt(page_access_token)
        async with self.sessions() as session:
            row = await session.get(MetaCredentialRow, "default")
            if row is None:
                row = MetaCredentialRow(
                    key="default",
                    page_id=page_id,
                    page_name=page_name,
                    access_token_ciphertext=ciphertext,
                    created_at=now,
                    updated_at=now,
                )
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
            result = await session.execute(
                select(MetaCredentialRow).where(MetaCredentialRow.key == "default")
            )
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "page_id": row.page_id,
            "page_name": row.page_name,
            "page_access_token": self._codec.decrypt(row.access_token_ciphertext),
        }


def build_meta_credential_store() -> CredentialStore:
    if settings.database_url:
        return PostgresCredentialStore(
            settings.database_url,
            settings.meta_oauth_encryption_key,
        )
    return InMemoryCredentialStore()
