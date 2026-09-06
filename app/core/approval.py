from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta


class ApprovalManager:
    """Issue and validate short-lived approval tokens for sensitive executions."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = max(60, ttl_seconds)

    def issue(self, now: datetime | None = None) -> tuple[str, str, datetime]:
        issued_at = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        expires_at = issued_at + timedelta(seconds=self.ttl_seconds)
        return token, self.hash_token(token), expires_at

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def verify(self, token: str, token_hash: str, expires_at: datetime | None, now: datetime | None = None) -> bool:
        if not token or not token_hash or expires_at is None:
            return False
        current = now or datetime.now(UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if current >= expires_at:
            return False
        return hmac.compare_digest(self.hash_token(token), token_hash)


approval_manager = ApprovalManager()
