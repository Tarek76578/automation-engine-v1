import pytest

from app.core.action_executor import ActionExecutor


@pytest.mark.asyncio
async def test_sequence_executes_all_actions_in_order() -> None:
    result = await ActionExecutor().execute(
        "sequence",
        {
            "actions": [
                {"action": "prepare_message", "parameters": {"message": "first"}},
                {"action": "prepare_message", "parameters": {"message": "second"}},
            ]
        },
        "execution-1",
    )

    assert result["verified"] is True
    assert [item["action"] for item in result["results"]] == ["prepare_message", "prepare_message"]
    assert [item["result"]["delivery"]["message"] for item in result["results"]] == ["first", "second"]
