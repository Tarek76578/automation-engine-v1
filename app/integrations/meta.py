from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import settings


class MetaGraphError(RuntimeError):
    """Raised when the Meta Graph API rejects a request."""


class MetaGraphClient:
    """Small, explicit Meta Graph API client for Facebook Pages and Messenger."""

    def __init__(
        self,
        access_token: str | None = None,
        api_version: str | None = None,
        page_id: str | None = None,
    ) -> None:
        self.access_token = access_token or settings.meta_page_access_token
        self.api_version = api_version or settings.meta_graph_api_version
        self.page_id = page_id or settings.meta_page_id

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.page_id)

    def configure(self, page_id: str, access_token: str) -> None:
        self.page_id = page_id.strip()
        self.access_token = access_token.strip()

    def _url(self, path: str) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}"

    async def page_info(self) -> dict[str, Any]:
        self._require_configured()
        return await self._request("GET", self.page_id, {"fields": "id,name"})

    async def page_messages(self, limit: int = 25) -> dict[str, Any]:
        self._require_configured()
        limit = max(1, min(limit, 100))
        return await self._request("GET", f"{self.page_id}/conversations", {"limit": limit})

    async def publish_page_post(self, message: str, link: str | None = None) -> dict[str, Any]:
        self._require_configured()
        message = message.strip()
        if not message:
            raise ValueError("meta_page_post requires a non-empty message")
        data: dict[str, Any] = {"message": message}
        if link:
            data["link"] = link
        return await self._request("POST", f"{self.page_id}/feed", data)

    async def send_page_message(self, recipient_id: str, message: str) -> dict[str, Any]:
        self._require_configured()
        recipient_id = recipient_id.strip()
        message = message.strip()
        if not recipient_id:
            raise ValueError("meta_page_reply requires recipient_id")
        if not message:
            raise ValueError("meta_page_reply requires a non-empty message")
        data = {"recipient": {"id": recipient_id}, "message": {"text": message}}
        return await self._request("POST", f"{self.page_id}/messages", data)

    async def _request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = dict(params)
        request_params["access_token"] = self.access_token
        timeout = httpx.Timeout(20.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.request(method, self._url(path), params=request_params)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        if not 200 <= response.status_code < 300:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            message = error.get("message") or f"Meta Graph API returned HTTP {response.status_code}"
            raise MetaGraphError(str(message))
        if not isinstance(body, dict):
            raise MetaGraphError("Meta Graph API returned a non-object response")
        return body

    def _require_configured(self) -> None:
        if not self.access_token:
            raise MetaGraphError("META_PAGE_ACCESS_TOKEN is not configured")
        if not self.page_id:
            raise MetaGraphError("META_PAGE_ID is not configured")


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 using the configured app secret."""
    if not settings.meta_app_secret or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac.new(settings.meta_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[len(prefix):], expected)


meta_graph_client = MetaGraphClient()
