from app.core.rule_engine import RuleEngine


def test_condition_groups_and_template_interpolation() -> None:
    engine = RuleEngine()
    plan = engine.plan({
        "event": {"type": "customer.created"},
        "customer": {"name": "Ahmed", "tier": "gold", "active": True},
        "rules": [{
            "id": "r1", "name": "Welcome gold customer", "priority": 10,
            "trigger": {"type": "customer.created"},
            "conditions": [{"all": [
                {"field": "customer.active", "operator": "equals", "value": True},
                {"any": [
                    {"field": "customer.tier", "operator": "equals", "value": "gold"},
                    {"field": "customer.tier", "operator": "equals", "value": "vip"},
                ]},
                {"not": {"field": "customer.name", "operator": "equals", "value": "Unknown"}},
            ]}],
            "actions": [{"type": "prepare_message", "parameters": {"message": "Welcome {{customer.name}}"}}],
        }],
    })
    assert plan.goal == "Welcome gold customer"
    assert plan.steps[0].parameters["message"] == "Welcome Ahmed"


def test_unmatched_group_returns_fallback() -> None:
    plan = RuleEngine().plan({
        "customer": {"tier": "basic"},
        "rules": [{
            "name": "Gold only",
            "conditions": [{"any": [
                {"field": "customer.tier", "operator": "equals", "value": "gold"},
                {"field": "customer.tier", "operator": "equals", "value": "vip"},
            ]}],
            "actions": [{"type": "prepare_message", "parameters": {"message": "no"}}],
        }],
    })
    assert plan.goal == "No matching rule"
    assert plan.steps[0].action == "process_request"
