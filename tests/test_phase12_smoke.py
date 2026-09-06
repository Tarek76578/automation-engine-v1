from dataclasses import asdict

import pytest

from app.core.planner import AgentPlanner
from app.integrations.messenger_memory import ConversationMessage, InMemoryMessengerMemory, conversation_key


class CaptureProvider:
    def __init__(self):
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return type(
            "Response",
            (),
            {
                "text": '{"goal":"continue customer conversation","steps":[{"action":"meta_page_reply","reason":"answer using context","parameters":{"recipient_id":"customer-1","message":"نعم، أتذكر السيارة Peugeot 208."}}],"requires_approval":false,"approval_reason":""}'
            },
        )()


@pytest.mark.asyncio
async def test_phase12_memory_to_planner_context_smoke():
    memory = InMemoryMessengerMemory(max_messages_per_conversation=12)
    key = conversation_key("page-1", "customer-1")
    inbound = ConversationMessage(key, "inbound", "customer-1", "لدي سيارة Peugeot 208", "event-1")

    assert await memory.append(inbound)
    assert not await memory.append(inbound)

    context = await memory.recent(key, limit=12)
    assert len(context) == 1
    assert context[0].message == "لدي سيارة Peugeot 208"

    provider = CaptureProvider()
    planner = AgentPlanner(provider=provider)
    plan = await planner.plan(
        {
            "message": "هل تتذكر سيارتي؟",
            "recipient_id": "customer-1",
            "conversation_context": [asdict(item) for item in context],
        }
    )

    assert provider.requests
    prompt = provider.requests[0].prompt
    assert "لدي سيارة Peugeot 208" in prompt
    assert plan.steps[0].action == "meta_page_reply"
    assert plan.steps[0].parameters["recipient_id"] == "customer-1"

    outbound = ConversationMessage(
        key, "outbound", "page-1", plan.steps[0].parameters["message"], "execution:smoke-1"
    )
    assert await memory.append(outbound)
    final_context = await memory.recent(key, limit=12)
    assert [item.direction for item in final_context] == ["inbound", "outbound"]
    assert "Peugeot 208" in final_context[-1].message
