import hashlib
import hmac

import pytest

from app.core.config import settings
from app.core.planner import AgentPlanner
from app.integrations.meta import verify_webhook_signature
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


@pytest.mark.asyncio
async def test_meta_oauth_consumes_state_once(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    monkeypatch.setattr(settings, "meta_redirect_uri", "https://example.com/api/meta/oauth/callback")
    monkeypatch.setattr(settings, "meta_page_id", "page-1")
    manager = MetaOAuthManager()
    url, state = manager.authorization_url()
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
    assert manager.credentials()["page_access_token"] == "page-token"
    with pytest.raises(MetaOAuthError, match="Invalid or expired"):
        await manager.callback("code-2", state)


def test_meta_reply_requires_approval():
    plan = AgentPlanner()._local_plan(
        {"meta_page_reply": "مرحبا", "recipient_id": "user-1"}
    )
    assert plan.steps[0].action == "meta_page_reply"
    assert plan.requires_approval is True
