from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from typing import Any

import httpx

from app.core.config import settings
from app.integrations.meta_credentials import (
    CredentialStore,
    MetaCredentialError,
    build_meta_credential_store,
)


class MetaOAuthError(RuntimeError):
    """Raised when Meta OAuth cannot be completed safely."""


@dataclass(frozen=True)
class OAuthState:
    value: str
    expires_at: float


class MetaOAuthManager:
    """OAuth onboarding with one-time state and durable encrypted Page credentials."""

    REQUIRED_SCOPES = (
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_posts",
        "pages_messaging",
    )

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self._states: dict[str, OAuthState] = {}
        self._credentials: dict[str, dict[str, str]] = {}
        self._store = credential_store or build_meta_credential_store()
        self._storage_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(settings.meta_app_id and settings.meta_app_secret and settings.meta_redirect_uri)

    @property
    def storage_configured(self) -> bool:
        return self._storage_error is None

    async def initialize(self) -> None:
        try:
            await self._store.initialize()
            credentials = await self._store.load()
            if credentials:
                self._credentials["default"] = credentials
        except MetaCredentialError as exc:
            self._storage_error = str(exc)

    def authorization_url(self) -> tuple[str, str]:
        self._require_ready()
        state = secrets.token_urlsafe(32)
        self._states[self._digest(state)] = OAuthState(state, time.time() + 600)

        params = {
            "client_id": settings.meta_app_id,
            "redirect_uri": settings.meta_redirect_uri,
            "state": state,
            "response_type": "code",
        }

        config_id = settings.meta_oauth_config_id.strip()
        if config_id:
            params["config_id"] = config_id
            params["override_default_response_type"] = "true"
        else:
            configured_scopes = [scope.strip() for scope in settings.meta_oauth_scopes.split(",") if scope.strip()]
            scopes = list(dict.fromkeys([*configured_scopes, *self.REQUIRED_SCOPES]))
            params["scope"] = ",".join(scopes)

        return (
            f"https://www.facebook.com/{settings.meta_graph_api_version}/dialog/oauth?{urlencode(params)}",
            state,
        )

    async def callback(self, code: str, state: str) -> dict[str, Any]:
        self._require_ready()
        self._consume_state(state)
        if not code.strip():
            raise MetaOAuthError("Meta OAuth callback is missing code")
        user_token = await self._exchange_code(code)
        pages = await self._list_pages(user_token)
        page = self._select_page(pages)
        page_id = str(page.get("id", "")).strip()
        page_token = str(page.get("access_token", "")).strip()
        page_name = str(page.get("name", "")).strip()
        if not page_id or not page_token:
            raise MetaOAuthError("Meta did not return a usable Page access token")
        credentials = {"page_id": page_id, "page_name": page_name, "page_access_token": page_token}
        try:
            await self._store.save(page_id, page_name, page_token)
        except MetaCredentialError as exc:
            raise MetaOAuthError(str(exc)) from exc
        self._credentials["default"] = credentials
        return {"page_id": page_id, "page_name": page_name, "connected": True}

    def credentials(self) -> dict[str, str] | None:
        value = self._credentials.get("default")
        return dict(value) if value else None

    def _require_ready(self) -> None:
        if not self.configured:
            raise MetaOAuthError("META_APP_ID, META_APP_SECRET and META_REDIRECT_URI are required")
        if self._storage_error:
            raise MetaOAuthError(self._storage_error)

    def _consume_state(self, state: str) -> None:
        key = self._digest(state)
        item = self._states.pop(key, None)
        if item is None or item.value != state or item.expires_at < time.time():
            raise MetaOAuthError("Invalid or expired Meta OAuth state")

    async def _exchange_code(self, code: str) -> str:
        params = {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "redirect_uri": settings.meta_redirect_uri,
            "code": code,
        }
        result = await self._request("GET", "/oauth/access_token", params)
        token = str(result.get("access_token", "")).strip()
        if not token:
            raise MetaOAuthError("Meta OAuth token exchange returned no access token")
        return token

    async def _list_pages(self, user_token: str) -> list[dict[str, Any]]:
        result = await self._request("GET", "/me/accounts", {"access_token": user_token, "fields": "id,name,access_token"})
        data = result.get("data", [])
        if not isinstance(data, list):
            raise MetaOAuthError("Meta returned an invalid Page list")
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _select_page(pages: list[dict[str, Any]]) -> dict[str, Any]:
        if not pages:
            raise MetaOAuthError("No Facebook Pages were returned for this Meta account")
        configured_id = settings.meta_page_id.strip()
        if configured_id:
            for page in pages:
                if str(page.get("id", "")) == configured_id:
                    return page
            raise MetaOAuthError("Configured META_PAGE_ID was not returned by Meta")
        return pages[0]

    async def _request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"https://graph.facebook.com/{settings.meta_graph_api_version}{path}"
        timeout = httpx.Timeout(20.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.request(method, url, params=params)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        if not 200 <= response.status_code < 300:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise MetaOAuthError(str(error.get("message") or f"Meta returned HTTP {response.status_code}"))
        if not isinstance(body, dict):
            raise MetaOAuthError("Meta returned a non-object response")
        return body

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


meta_oauth_manager = MetaOAuthManager()
