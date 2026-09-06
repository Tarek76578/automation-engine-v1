from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class MetaGraphError(RuntimeError):
    """Raised when the Meta Graph API rejects a request."""


class MetaGraphClient:
    """Small, explicit Meta Graph API client for Facebook Page operations."""

    def __init__(self, access_token: str | None = None, api_version: str | None = None) -> None:
        self.access_token = access_token or settings.meta_page_access_token
        self.api_version = api_version or settings.meta_graph_api_version

    @property
    def configured(self) -> bool:
        return bool(self.access_token and settings.meta_page_id)

    def _url(self, path: str) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}"

    async def page_info(self) -> dict[str, Any]:
        self._require_configured()
        return await self._request("GET", settings.meta_page_id, {"fields": "id,name"})

    async def page_messages(self, limit: int = 25) -> dict[str, Any]:
        self._require_configured()
        limit = max(1, min(limit, 100))
        return await self._request("GET", f"{settings.meta_page_id}/conversations", {"limit": limit})

    async def publish_page_post(self, message: str, link: str | None = None) -> dict[str, Any]:
        self._require_configured()
        message = message.strip()
        if not message:
            raise ValueError("meta_page_post requires a non-empty message")
        data: dict[str, Any] = {"message": message}
        if link:
            data["link"] = link
        return await self._request("POST", f"{settings.meta_page_id}/feed", data)

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
        if not settings.meta_page_id:
            raise MetaGraphError("META_PAGE_ID is not configured")


meta_graph_client = MetaGraphClient()
