from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.rule_engine import RuleEngine
from app.core.rule_store import rule_store
from app.models.rule import AutomationRule, RuleCreate, RuleDryRunRequest, RuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"])
engine = RuleEngine()


@router.get("", response_model=list[AutomationRule])
async def list_rules() -> list[AutomationRule]:
    return await rule_store.list()


@router.post("", response_model=AutomationRule, status_code=201)
async def create_rule(request: RuleCreate) -> AutomationRule:
    rule = AutomationRule(**request.model_dump())
    return await rule_store.save(rule)


@router.get("/{rule_id}", response_model=AutomationRule)
async def get_rule(rule_id: UUID) -> AutomationRule:
    rule = await rule_store.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{rule_id}", response_model=AutomationRule)
async def update_rule(rule_id: UUID, request: RuleUpdate) -> AutomationRule:
    rule = await rule_store.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    values = request.model_dump(exclude_unset=True)
    updated = rule.model_copy(update=values)
    if not updated.actions:
        raise HTTPException(status_code=422, detail="Rule must contain at least one action")
    return await rule_store.save(updated)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID) -> None:
    if not await rule_store.delete(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/{rule_id}/dry-run")
async def dry_run_rule(rule_id: UUID, request: RuleDryRunRequest) -> dict:
    rule = await rule_store.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule_data = rule.model_dump(mode="json", by_alias=True)
    task_input = dict(request.input)
    task_input["rules"] = [rule_data]
    plan = engine.plan(task_input)
    matched = plan.goal == rule.name
    return {
        "matched": matched,
        "rule": rule,
        "plan": plan.model_dump(mode="json"),
        "actions": [step.model_dump(mode="json") for step in plan.steps] if matched else [],
        "would_execute": matched and bool(plan.steps) and plan.steps[0].action != "process_request",
    }
