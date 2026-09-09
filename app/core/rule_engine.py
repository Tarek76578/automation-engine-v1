from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.planner import AgentPlan, PlanStep


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    name: str
    priority: int


class RuleEngine:
    """Deterministic trigger/condition evaluator; no LLM or external API required."""

    OPERATORS = frozenset(
        {
            "equals",
            "not_equals",
            "contains",
            "not_contains",
            "starts_with",
            "ends_with",
            "greater_than",
            "less_than",
            "greater_or_equal",
            "less_or_equal",
            "exists",
            "not_exists",
            "in",
            "not_in",
        }
    )
    TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")

    def plan(self, task_input: dict[str, Any]) -> AgentPlan:
        rules = task_input.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError("rules must be a list")
        ordered = sorted(
            (
                rule
                for rule in rules
                if isinstance(rule, dict) and rule.get("enabled", True)
            ),
            key=lambda rule: int(rule.get("priority", 0)),
            reverse=True,
        )
        for rule in ordered:
            if self._matches_trigger(
                rule.get("trigger"), task_input
            ) and self._matches_conditions(
                rule.get("conditions", []), task_input
            ):
                actions = rule.get("actions", [])
                if not isinstance(actions, list) or not actions:
                    raise ValueError(
                        f"rule {rule.get('id', rule.get('name', 'unknown'))} has no actions"
                    )
                steps = [self._step(action, task_input) for action in actions]
                return AgentPlan(
                    goal=str(rule.get("name", rule.get("id", "Matched rule"))),
                    steps=steps,
                    requires_approval=bool(rule.get("requires_approval", False)),
                    approval_reason=str(rule.get("approval_reason", "")),
                )
        return AgentPlan(
            goal="No matching rule",
            steps=[
                PlanStep(
                    action="process_request",
                    reason="No rule matched",
                    parameters={},
                )
            ],
        )

    def _matches_trigger(self, trigger: Any, data: dict[str, Any]) -> bool:
        if not trigger:
            return True
        if not isinstance(trigger, dict):
            raise ValueError("trigger must be an object")
        trigger_type = trigger.get("type")
        if trigger_type is None:
            return True
        event = data.get("event")
        if isinstance(event, dict):
            event_type = event.get("type")
        else:
            event_type = data.get("event_type", data.get("trigger_type"))
        return event_type == trigger_type

    def _matches_conditions(self, conditions: Any, data: dict[str, Any]) -> bool:
        if not isinstance(conditions, list):
            raise ValueError("conditions must be a list")
        return all(self._condition(condition, data) for condition in conditions)

    def _condition(self, condition: Any, data: dict[str, Any]) -> bool:
        if not isinstance(condition, dict):
            raise ValueError("condition must be an object")
        if "all" in condition:
            values = condition["all"]
            if not isinstance(values, list):
                raise ValueError("all condition group must be a list")
            return all(self._condition(item, data) for item in values)
        if "any" in condition:
            values = condition["any"]
            if not isinstance(values, list):
                raise ValueError("any condition group must be a list")
            return any(self._condition(item, data) for item in values)
        if "not" in condition:
            return not self._condition(condition["not"], data)
        field = str(condition.get("field", ""))
        operator = str(condition.get("operator", "equals"))
        if operator not in self.OPERATORS:
            raise ValueError(f"unsupported condition operator: {operator}")
        value, exists = self._get(data, field)
        expected = condition.get("value")
        if operator == "exists":
            return exists
        if operator == "not_exists":
            return not exists
        if not exists:
            return operator == "not_equals"
        if operator == "equals":
            return value == expected
        if operator == "not_equals":
            return value != expected
        if operator == "contains":
            return str(expected) in str(value)
        if operator == "not_contains":
            return str(expected) not in str(value)
        if operator == "starts_with":
            return str(value).startswith(str(expected))
        if operator == "ends_with":
            return str(value).endswith(str(expected))
        if operator in {"in", "not_in"}:
            if not isinstance(expected, (list, tuple, set)):
                raise ValueError(f"{operator} requires a list value")
            result = value in expected
            return result if operator == "in" else not result
        try:
            if operator == "greater_than":
                return value > expected
            if operator == "less_than":
                return value < expected
            if operator == "greater_or_equal":
                return value >= expected
            if operator == "less_or_equal":
                return value <= expected
        except TypeError as exc:
            raise ValueError(f"incomparable values for field {field}") from exc
        raise ValueError(f"unsupported condition operator: {operator}")

    @classmethod
    def _resolve_template(cls, value: Any, data: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._resolve_template(item, data)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._resolve_template(item, data) for item in value]
        if not isinstance(value, str):
            return value
        matches = list(cls.TEMPLATE.finditer(value))
        if len(matches) == 1 and matches[0].group(0) == value:
            resolved, exists = cls._get(data, matches[0].group(1))
            return resolved if exists else value

        def replace(match: re.Match[str]) -> str:
            resolved, exists = cls._get(data, match.group(1))
            return str(resolved) if exists else match.group(0)

        return cls.TEMPLATE.sub(replace, value)

    @staticmethod
    def _get(data: dict[str, Any], field: str) -> tuple[Any, bool]:
        current: Any = data
        for part in field.split(".") if field else []:
            if not isinstance(current, dict) or part not in current:
                return None, False
            current = current[part]
        return current, True

    @classmethod
    def _step(cls, action: Any, data: dict[str, Any]) -> PlanStep:
        if not isinstance(action, dict):
            raise ValueError("action must be an object")
        name = str(action.get("type", action.get("action", ""))).strip()
        if not name:
            raise ValueError("action type is required")
        parameters = action.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"parameters for action {name} must be an object")
        return PlanStep(
            action=name,
            reason=str(action.get("reason", "Rule matched")),
            parameters=cls._resolve_template(parameters, data),
        )
