import pytest

from app.core.action_executor import ActionExecutor
from app.core.config import settings
from app.integrations.meta import MetaGraphClient


@pytest.mark.asyncio
async def test_webhook_requires_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "")
    with pytest.raises(ValueError, match="ALLOWLIST"):
        await ActionExecutor().execute("webhook", {"webhook_url": "https://example.com/hook", "webhook_payload": {"ok": True}}, "test-id")


@pytest.mark.asyncio
async def test_webhook_rejects_http(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        await ActionExecutor().execute("webhook", {"webhook_url": "http://example.com/hook"}, "test-id")


@pytest.mark.asyncio
async def test_webhook_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "internal.example")
    monkeypatch.setattr("app.core.action_executor.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.5", 443))])
    with pytest.raises(ValueError, match="blocked IP"):
        await ActionExecutor().execute("webhook", {"webhook_url": "https://internal.example/hook"}, "test-id")


@pytest.mark.asyncio
async def test_webhook_executes_and_verifies(monkeypatch):
    monkeypatch.setattr(settings, "action_webhook_allowlist", "hooks.example")
    monkeypatch.setattr("app.core.action_executor.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

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
            assert headers["Idempotency-Key"] == "test-id"
            return Response()

    monkeypatch.setattr("app.core.action_executor.httpx.AsyncClient", lambda **kwargs: Client())
    result = await ActionExecutor().execute("webhook", {"webhook_url": "https://hooks.example/hook", "webhook_payload": {"message": "hello"}}, "test-id")
    assert result["status"] == "executed"
    assert result["verified"] is True
    assert result["delivery"]["status_code"] == 204
    assert result["delivery"]["idempotency_key"] == "test-id"


@pytest.mark.asyncio
async def test_meta_page_post_executes_with_mocked_graph_client():
    class FakeMetaClient:
        async def publish_page_post(self, message, link=None):
            assert message == "hello Meta"
            assert link == "https://example.com"
            return {"id": "post-123"}

    result = await ActionExecutor(meta_client=FakeMetaClient()).execute("meta_page_post", {"message": "hello Meta", "link": "https://example.com"}, "execution-123")
    assert result["verified"] is True
    assert result["delivery"]["channel"] == "meta-graph-api"
    assert result["delivery"]["result"]["id"] == "post-123"


@pytest.mark.asyncio
async def test_meta_page_reply_records_successful_message(monkeypatch):
    recorded: list[tuple[str, str, str, str]] = []

    class FakeMetaClient:
        async def send_page_message(self, recipient_id, message):
            return {"recipient_id": recipient_id, "message_id": "m-123"}

    class FakeMemory:
        async def record_outbound(self, page_id, recipient_id, message, execution_id):
            recorded.append((page_id, recipient_id, message, execution_id))
            return True

    monkeypatch.setattr("app.core.action_executor.messenger_memory", FakeMemory())
    result = await ActionExecutor(meta_client=FakeMetaClient()).execute(
        "meta_page_reply", {"page_id": "page-1", "recipient_id": "user-123", "message": "hello from CarBot"}, "execution-456"
    )
    assert result["verified"] is True
    assert result["delivery"]["result"]["message_id"] == "m-123"
    assert recorded == [("page-1", "user-123", "hello from CarBot", "execution-456")]


@pytest.mark.asyncio
async def test_meta_page_reply_requires_recipient_and_message():
    class FakeMetaClient:
        async def send_page_message(self, recipient_id, message):
            raise AssertionError("should not call Meta")

    with pytest.raises(ValueError, match="recipient_id"):
        await ActionExecutor(meta_client=FakeMetaClient()).execute("meta_page_reply", {"message": "hello"}, "execution-456")


@pytest.mark.asyncio
async def test_meta_graph_client_requires_credentials(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_access_token", "")
    monkeypatch.setattr(settings, "meta_page_id", "")
    client = MetaGraphClient()
    with pytest.raises(RuntimeError, match="META_PAGE_ACCESS_TOKEN"):
        await client.page_info()
