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


def test_meta_page_post_plan_requires_approval():
    plan = AgentPlanner()._local_plan({"meta_page_post": "عرض جديد على صفحتنا"})
    assert plan.steps[0].action == "meta_page_post"
    assert plan.steps[0].parameters["message"] == "عرض جديد على صفحتنا"
    assert plan.requires_approval is True


def test_meta_page_read_plan_does_not_require_approval():
    plan = AgentPlanner()._local_plan({"meta_page_messages": True, "limit": 10})
    assert plan.steps[0].action == "meta_page_messages"
    assert plan.steps[0].parameters["limit"] == 10
    assert plan.requires_approval is False


def test_inbound_messenger_auto_reply_can_execute_without_approval():
    plan = AgentPlanner()._local_plan(
        {
            "message": "مرحبا، هل المنتج متوفر؟",
            "recipient_id": "123",
            "meta_messenger_inbound": True,
            "meta_messenger_auto_reply": True,
        }
    )
    assert plan.steps[0].action == "meta_page_reply"
    assert plan.steps[0].parameters["recipient_id"] == "123"
    assert plan.requires_approval is False


def test_inbound_messenger_reply_defaults_to_approval():
    plan = AgentPlanner()._local_plan(
        {
            "message": "مرحبا، هل المنتج متوفر؟",
            "recipient_id": "123",
            "meta_messenger_inbound": True,
            "meta_messenger_auto_reply": False,
        }
    )
    assert plan.steps[0].action == "meta_page_reply"
    assert plan.requires_approval is True


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
