import pytest

from app.core.action_executor import ActionExecutor
from app.core.config import settings


@pytest.mark.asyncio
async def test_webhook_requires_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "")
    with pytest.raises(ValueError, match="ALLOWLIST"):
        await ActionExecutor().execute(
            "webhook",
            {"webhook_url": "https://example.com/hook", "webhook_payload": {"ok": True}},
            "test-id",
        )


@pytest.mark.asyncio
async def test_webhook_rejects_http(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        await ActionExecutor().execute(
            "webhook",
            {"webhook_url": "http://example.com/hook"},
            "test-id",
        )


@pytest.mark.asyncio
async def test_webhook_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "internal.example")
    monkeypatch.setattr(
        "app.core.action_executor.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.5", 443))],
    )
    with pytest.raises(ValueError, match="blocked IP"):
        await ActionExecutor().execute(
            "webhook",
            {"webhook_url": "https://internal.example/hook"},
            "test-id",
        )


@pytest.mark.asyncio
async def test_webhook_executes_and_verifies(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "hooks.example")
    monkeypatch.setattr(
        "app.core.action_executor.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    class Response:
        status_code = 204

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            assert url == "https://hooks.example/hook"
            assert json["execution_id"] == "test-id"
            return Response()

    monkeypatch.setattr("app.core.action_executor.httpx.AsyncClient", lambda **kwargs: Client())
    result = await ActionExecutor().execute(
        "webhook",
        {"webhook_url": "https://hooks.example/hook", "webhook_payload": {"message": "hello"}},
        "test-id",
    )
    assert result["status"] == "executed"
    assert result["verified"] is True
    assert result["delivery"]["status_code"] == 204
