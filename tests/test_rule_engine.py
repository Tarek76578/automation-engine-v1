from app.core.rule_engine import RuleEngine


def test_matches_nested_condition_and_builds_action() -> None:
    plan = RuleEngine().plan({
        "event": {"type": "messenger_message"},
        "customer": {"is_new": True, "name": "Ahmed"},
        "rules": [{
            "id": "welcome",
            "priority": 10,
            "trigger": {"type": "messenger_message"},
            "conditions": [{"field": "customer.is_new", "operator": "equals", "value": True}],
            "actions": [{"type": "prepare_message", "parameters": {"message": "Welcome {{customer.name}}"}}],
        }],
    })
    assert plan.goal == "welcome"
    assert plan.steps[0].action == "prepare_message"
    assert plan.steps[0].parameters["message"] == "Welcome {{customer.name}}"


def test_priority_wins() -> None:
    plan = RuleEngine().plan({
        "rules": [
            {"id": "low", "priority": 1, "actions": [{"type": "process_request"}]},
            {"id": "high", "priority": 20, "actions": [{"type": "analyze_request"}]},
        ]
    })
    assert plan.goal == "high"
    assert plan.steps[0].action == "analyze_request"


def test_all_conditions_are_required() -> None:
    plan = RuleEngine().plan({
        "customer": {"orders": 2},
        "rules": [{
            "id": "vip",
            "conditions": [
                {"field": "customer.orders", "operator": "greater_than", "value": 5},
                {"field": "customer.name", "operator": "exists"},
            ],
            "actions": [{"type": "prepare_message", "parameters": {"message": "VIP"}}],
        }]
    })
    assert plan.goal == "No matching rule"
    assert plan.steps[0].action == "process_request"
