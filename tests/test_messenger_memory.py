import pytest

from app.integrations.messenger_memory import InMemoryMessengerMemory, MessengerMemory, conversation_key


@pytest.mark.asyncio
async def test_memory_records_context_and_deduplicates_event() -> None:
    memory = MessengerMemory(InMemoryMessengerMemory())

    assert await memory.record_inbound("page-1", "user-7", "مرحبا", "mid-1") is True
    assert await memory.record_inbound("page-1", "user-7", "مرحبا", "mid-1") is False
    assert await memory.record_outbound("page-1", "user-7", "أهلا بك", "exec-1") is True

    assert await memory.recent_context("page-1", "user-7") == [
        {"direction": "inbound", "message": "مرحبا"},
        {"direction": "outbound", "message": "أهلا بك"},
    ]
    assert conversation_key("page-1", "user-7") == "meta:page-1:user-7"


@pytest.mark.asyncio
async def test_memory_limits_recent_context() -> None:
    memory = MessengerMemory(InMemoryMessengerMemory(max_messages_per_conversation=3))
    for index in range(5):
        await memory.record_inbound("page-1", "user-7", f"m{index}", f"mid-{index}")

    assert [item["message"] for item in await memory.recent_context("page-1", "user-7", 10)] == ["m2", "m3", "m4"]
