import pytest

from app.core.agent_runtime import AgentRegistry, AgentRuntime
from app.core.router import LLMRouter
from app.models.agent import AgentDefinition, AgentTask


class FakeProvider:
    name = "fake"

    async def generate(self, request):
        from app.providers.base import LLMResponse

        return LLMResponse(
            provider="fake",
            model=request.model,
            text=(
                '{"goal":"send hello","steps":[{"action":"prepare_message",'
                '"reason":"customer greeting","parameters":{"message":"hello"}}],'
                '"requires_approval":false,"approval_reason":""}'
            ),
        )


@pytest.mark.asyncio
async def test_runtime_uses_structured_llm_plan():
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="automation",
            system_prompt="Return a safe plan.",
            provider="fake",
            model="planner-test",
        )
    )
    runtime = AgentRuntime(registry, LLMRouter(), {"fake": FakeProvider()})

    result = await runtime.execute_async(
        AgentTask(agent="automation", input={"message": "say hello"})
    )

    assert result.provider == "fake"
    assert result.output["planner"] == "llm"
    assert result.output["action"] == "prepare_message"
    assert result.output["plan"]["steps"][0]["action"] == "prepare_message"
