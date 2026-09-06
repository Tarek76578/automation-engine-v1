import pytest

from app.core.planner import AgentPlanner, AgentPlan


def test_local_message_plan_is_executable_and_not_sensitive():
    plan = AgentPlanner()._local_plan({"message": "أرسل رسالة ترحيب للعميل أحمد"})

    assert isinstance(plan, AgentPlan)
    assert plan.steps[0].action == "prepare_message"
    assert plan.steps[0].parameters["message"] == "أرسل رسالة ترحيب للعميل أحمد"
    assert plan.requires_approval is False


def test_sensitive_plan_requires_approval():
    plan = AgentPlanner()._local_plan({"message": "نشر الإعلان على الصفحة"})

    assert plan.requires_approval is True
    assert plan.approval_reason


def test_llm_json_plan_is_validated():
    plan = AgentPlanner()._parse(
        '{"goal":"send a message","steps":[{"action":"prepare_message","reason":"customer reply","parameters":{"message":"hello"}}]}'
    )

    assert plan.steps[0].action == "prepare_message"


def test_invalid_action_is_rejected():
    plan = AgentPlanner()._parse(
        '{"goal":"do it","steps":[{"action":"shell_exec","reason":"unsafe","parameters":{}}]}'
    )

    with pytest.raises(ValueError, match="unsupported planned action"):
        AgentPlanner()._validate(plan)
