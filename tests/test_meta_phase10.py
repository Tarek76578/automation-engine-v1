import hashlib
import hmac

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.planner import AgentPlanner
from app.integrations.meta import verify_webhook_signature
from app.integrations.meta_credentials import (
    EncryptedCredentialCodec,
    MetaCredentialError,
    UnavailableCredentialStore,
    build_meta_credential_store,
)
from app.integrations.meta_oauth import MetaOAuthError, MetaOAuthManager


def test_meta_webhook_signature_verification(monkeypatch):
    secret = "app-secret"
    body = b'{"object":"page"}'
    monkeypatch.setattr(settings, "meta_app_secret", secret)
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"sha256={digest}") is True
    assert verify_webhook_signature(body, "sha256=wrong") is False


def test_meta_webhook_signature_requires_secret(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "")
    assert verify_webhook_signature(b"{}", "sha256=anything") is False


def test_meta_credential_codec_encrypts_without_plaintext(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    codec = EncryptedCredentialCodec(key)
    token = "page-token-secret"
    ciphertext = codec.encrypt(token)
    assert ciphertext != token
    assert token not in ciphertext
    assert codec.decrypt(ciphertext) == token
    monkeypatch.setattr(settings, "meta_oauth_encryption_key", "not-a-fernet-key")
    with pytest.raises(MetaCredentialError, match="valid Fernet key"):
        EncryptedCredentialCodec(settings.meta_oauth_encryption_key)


def test_missing_production_encryption_key_disables_credential_store(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://example")
    monkeypatch.setattr(settings, "meta_oauth_encryption_key", "")
    store = build_meta_credential_store()
    assert isinstance(store, UnavailableCredentialStore)


class MemoryStore:
    def __init__(self):
        self.value = None
        self.oauth_states = {}

    async def initialize(self):
        return None

    async def save(self, page_id, page_name, page_access_token):
        self.value = {
            "page_id": page_id,
            "page_name": page_name,
            "page_access_token": page_access_token,
        }

    async def load(self):
        return dict(self.value) if self.value else None

    async def save_oauth_state(self, state_hash, expires_at):
        self.oauth_states[state_hash] = expires_at

    async def consume_oauth_state(self, state_hash, now):
        expires_at = self.oauth_states.pop(state_hash, None)
        return expires_at is not None and expires_at >= now


@pytest.mark.asyncio
async def test_meta_oauth_persists_credentials_in_store(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    monkeypatch.setattr(settings, "meta_redirect_uri", "https://example.com/api/meta/oauth/callback")
    monkeypatch.setattr(settings, "meta_page_id", "page-1")
    store = MemoryStore()
    manager = MetaOAuthManager(store)
    await manager.initialize()
    url, state = await manager.authorization_url()
    assert "client_id=app-id" in url

    class Response:
        status_code = 200

        def json(self):
            return {"access_token": "user-token"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, params):
            if url.endswith("/oauth/access_token"):
                return Response()
            response = Response()
            response.json = lambda: {
                "data": [{"id": "page-1", "name": "Demo Page", "access_token": "page-token"}]
            }
            return response

    monkeypatch.setattr("app.integrations.meta_oauth.httpx.AsyncClient", lambda **kwargs: Client())
    result = await manager.callback("code-1", state)
    assert result["connected"] is True
    assert store.value["page_access_token"] == "page-token"
    assert manager.credentials()["page_access_token"] == "page-token"
    with pytest.raises(MetaOAuthError, match="Invalid or expired"):
        await manager.callback("code-2", state)


@pytest.mark.asyncio
async def test_meta_oauth_restores_credentials_from_store(monkeypatch):
    store = MemoryStore()
    await store.save("page-2", "Stored Page", "stored-token")
    manager = MetaOAuthManager(store)
    await manager.initialize()
    assert manager.credentials() == {
        "page_id": "page-2",
        "page_name": "Stored Page",
        "page_access_token": "stored-token",
    }


def test_meta_reply_requires_approval():
    plan = AgentPlanner()._local_plan(
        {"meta_page_reply": "مرحبا", "recipient_id": "user-1"}
    )
    assert plan.steps[0].action == "meta_page_reply"
    assert plan.requires_approval is True
