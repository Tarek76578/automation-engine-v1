from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from app.core.action_executor import action_executor
from app.core.agent_runtime import AgentRuntime
from app.core.approval import approval_manager
from app.core.config import settings
from app.core.job_queue import Job, Queue
from app.core.observability import (
    ACTIONS_TOTAL,
    EXECUTIONS_TOTAL,
    EXECUTION_DURATION_SECONDS,
    EXECUTION_RETRIES_TOTAL,
    IDEMPOTENCY_HITS_TOTAL,
)
from app.core.persistence import ExecutionRepository
from app.core.state_machine import transition
from app.integrations.n8n import N8nClient
from app.models.agent import AgentTask
from app.models.execution import Execution, ExecutionStatus

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """Coordinates planning, approval, action execution, verification, and persistence."""

    def __init__(self, repository: ExecutionRepository, queue: Queue, runtime: AgentRuntime, n8n: N8nClient | None = None, max_attempts: int = 3, retry_base_delay_seconds: float = 2.0, retry_max_delay_seconds: float = 60.0) -> None:
        self.repository = repository
        self.queue = queue
        self.runtime = runtime
        self.n8n = n8n
        self.max_attempts = max(1, max_attempts)
        self.retry_base_delay_seconds = max(0.0, retry_base_delay_seconds)
        self.retry_max_delay_seconds = max(self.retry_base_delay_seconds, retry_max_delay_seconds)

    def _retry_delay(self, attempt: int) -> float:
        exponent = max(0, attempt - 1)
        return min(self.retry_max_delay_seconds, self.retry_base_delay_seconds * (2**exponent))

    @staticmethod
    def _action_payload(output: dict[str, Any], task_input: dict[str, Any]) -> dict[str, Any]:
        plan = output.get("plan")
        if isinstance(plan, dict):
            steps = plan.get("steps")
            if isinstance(steps, list) and steps and isinstance(steps[0], dict):
                parameters = steps[0].get("parameters")
                if isinstance(parameters, dict):
                    return parameters
        return task_input

    async def submit(self, execution: Execution, idempotency_key: str | None = None) -> Execution:
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                IDEMPOTENCY_HITS_TOTAL.labels(workflow=existing.workflow).inc()
                return existing
            execution.idempotency_key = idempotency_key
        existing = await self.repository.get(str(execution.id))
        if existing is not None:
            if idempotency_key:
                IDEMPOTENCY_HITS_TOTAL.labels(workflow=existing.workflow).inc()
            return existing
        saved = await self.repository.save(execution)
        if str(saved.id) != str(execution.id):
            if idempotency_key:
                IDEMPOTENCY_HITS_TOTAL.labels(workflow=saved.workflow).inc()
            return saved
        await self.queue.enqueue(Job(execution_id=execution.id))
        return saved

    async def process(self, execution_id: str) -> Execution | None:
        started = monotonic()
        execution = await self.repository.get(execution_id)
        if execution is None:
            return None
        if execution.status in {ExecutionStatus.succeeded, ExecutionStatus.failed, ExecutionStatus.waiting_approval}:
            return execution
        transition(execution, ExecutionStatus.running)
        execution.attempts += 1
        execution.updated_at = datetime.now(UTC)
        await self.repository.save(execution)
        try:
            requested_agent = execution.input.get("agent")
            if requested_agent:
                agent_name = str(requested_agent)
            elif self.runtime.registry.get(execution.workflow) is not None:
                agent_name = execution.workflow
            else:
                agent_name = settings.default_agent
            task_input = execution.input.get("input", execution.input)
            if not isinstance(task_input, dict):
                task_input = {"value": task_input}
            result = await self.runtime.execute_async(AgentTask(agent=agent_name, input=task_input))
            output: dict[str, Any] = dict(result.output)
            output.update({"agent": agent_name, "workflow": execution.workflow, "provider": result.provider, "model": result.model})

            plan = output.get("plan") if isinstance(output.get("plan"), dict) else {}
            requires_approval = bool(plan.get("requires_approval")) and execution.approval_decision != "approved"
            if requires_approval:
                token, token_hash, expires_at = approval_manager.issue()
                now = datetime.now(UTC)
                execution.approval_token_hash = token_hash
                execution.approval_expires_at = expires_at
                execution.approval_requested_at = now
                execution.approval_decided_at = None
                execution.approval_decided_by = None
                execution.approval_decision = None
                output["approval"] = {
                    "required": True,
                    "status": "awaiting_approval",
                    "reason": plan.get("approval_reason", "Sensitive operation requires approval."),
                    "expires_at": expires_at.isoformat(),
                }
                execution.approval_token = token
                execution.output = output
                execution.error = None
                transition(execution, ExecutionStatus.waiting_approval)
                await self.repository.save(execution)
                logger.warning("execution awaiting approval", extra={"execution_id": execution_id})
                return execution

            action = str(output.get("action", "")).strip()
            if action:
                try:
                    output["execution"] = await action_executor.execute(action, self._action_payload(output, task_input), str(execution.id))
                    ACTIONS_TOTAL.labels(action=action, status="succeeded").inc()
                except Exception:
                    ACTIONS_TOTAL.labels(action=action, status="failed").inc()
                    raise

            webhook = execution.input.get("n8n_webhook")
            if webhook:
                if self.n8n is None:
                    raise RuntimeError("n8n webhook requested but N8nClient is not configured")
                output["n8n"] = await self.n8n.trigger_webhook(str(webhook), {"execution_id": str(execution.id), "output": output})

            if action and output["execution"].get("verified") is not True:
                raise RuntimeError(f"action '{action}' could not be verified")

            if execution.approval_decision == "approved":
                output["approval"] = {
                    "required": True,
                    "status": "approved",
                    "approved_at": execution.approval_decided_at.isoformat() if execution.approval_decided_at else None,
                    "approved_by": execution.approval_decided_by,
                }

            transition(execution, ExecutionStatus.succeeded)
            execution.output = output
            execution.error = None
            EXECUTIONS_TOTAL.labels(workflow=execution.workflow, status="succeeded").inc()
            EXECUTION_DURATION_SECONDS.labels(workflow=execution.workflow, status="succeeded").observe(monotonic() - started)
        except Exception as exc:
            execution.error = str(exc)
            if execution.attempts >= self.max_attempts:
                transition(execution, ExecutionStatus.failed)
                EXECUTIONS_TOTAL.labels(workflow=execution.workflow, status="failed").inc()
                EXECUTION_DURATION_SECONDS.labels(workflow=execution.workflow, status="failed").observe(monotonic() - started)
            else:
                transition(execution, ExecutionStatus.queued)
                await self.repository.save(execution)
                delay = self._retry_delay(execution.attempts)
                await self.queue.enqueue(Job(execution_id=execution.id), delay_seconds=delay)
                EXECUTION_RETRIES_TOTAL.labels(workflow=execution.workflow).inc()
                logger.warning("execution retry scheduled", extra={"execution_id": execution_id, "attempt": execution.attempts, "retry_delay_seconds": delay})
                return execution
        execution.updated_at = datetime.now(UTC)
        await self.repository.save(execution)
        return execution

    async def request_approval(self, execution_id: str) -> tuple[Execution | None, str | None]:
        execution = await self.repository.get(execution_id)
        if execution is None:
            return None, None
        if execution.status is ExecutionStatus.queued:
            execution = await self.process(execution_id)
        if execution.status is not ExecutionStatus.waiting_approval:
            return execution, None
        now = datetime.now(UTC)
        if execution.approval_expires_at and now >= execution.approval_expires_at:
            transition(execution, ExecutionStatus.failed)
            execution.error = "approval request expired"
            execution.updated_at = now
            await self.repository.save(execution)
            return execution, None
        token, token_hash, expires_at = approval_manager.issue(now)
        execution.approval_token_hash = token_hash
        execution.approval_expires_at = expires_at
        execution.approval_requested_at = now
        execution.approval_token = token
        execution.updated_at = now
        await self.repository.save(execution)
        return execution, token

    async def approve(self, execution_id: str, token: str, approved_by: str = "api") -> Execution | None:
        execution = await self.repository.get(execution_id)
        if execution is None:
            return None
        if execution.status is not ExecutionStatus.waiting_approval:
            raise ValueError("execution is not awaiting approval")
        if not approval_manager.verify(token, execution.approval_token_hash or "", execution.approval_expires_at):
            raise ValueError("invalid or expired approval token")
        now = datetime.now(UTC)
        execution.approval_decision = "approved"
        execution.approval_decided_by = approved_by[:200]
        execution.approval_decided_at = now
        execution.approval_token_hash = None
        execution.approval_expires_at = None
        execution.approval_token = None
        transition(execution, ExecutionStatus.running)
        execution.updated_at = now
        await self.repository.save(execution)
        return await self._resume_after_approval(execution)

    async def reject(self, execution_id: str, token: str, rejected_by: str = "api") -> Execution | None:
        execution = await self.repository.get(execution_id)
        if execution is None:
            return None
        if execution.status is not ExecutionStatus.waiting_approval:
            raise ValueError("execution is not awaiting approval")
        if not approval_manager.verify(token, execution.approval_token_hash or "", execution.approval_expires_at):
            raise ValueError("invalid or expired approval token")
        now = datetime.now(UTC)
        execution.approval_decision = "rejected"
        execution.approval_decided_by = rejected_by[:200]
        execution.approval_decided_at = now
        execution.approval_token_hash = None
        execution.approval_expires_at = None
        execution.approval_token = None
        execution.error = "execution rejected by approver"
        transition(execution, ExecutionStatus.failed)
        execution.updated_at = now
        await self.repository.save(execution)
        return execution

    async def _resume_after_approval(self, execution: Execution) -> Execution:
        await self.repository.save(execution)
        return await self._execute_planned_action(execution)

    async def _execute_planned_action(self, execution: Execution) -> Execution:
        started = monotonic()
        output = dict(execution.output or {})
        task_input = execution.input.get("input", execution.input)
        if not isinstance(task_input, dict):
            task_input = {"value": task_input}
        action = str(output.get("action", "")).strip()
        try:
            if action:
                output["execution"] = await action_executor.execute(action, self._action_payload(output, task_input), str(execution.id))
                ACTIONS_TOTAL.labels(action=action, status="succeeded").inc()
                if output["execution"].get("verified") is not True:
                    raise RuntimeError(f"action '{action}' could not be verified")
            webhook = execution.input.get("n8n_webhook")
            if webhook:
                if self.n8n is None:
                    raise RuntimeError("n8n webhook requested but N8nClient is not configured")
                output["n8n"] = await self.n8n.trigger_webhook(str(webhook), {"execution_id": str(execution.id), "output": output})
            output["approval"] = {
                "required": True,
                "status": "approved",
                "approved_at": execution.approval_decided_at.isoformat() if execution.approval_decided_at else None,
                "approved_by": execution.approval_decided_by,
            }
            transition(execution, ExecutionStatus.succeeded)
            execution.output = output
            execution.error = None
            EXECUTIONS_TOTAL.labels(workflow=execution.workflow, status="succeeded").inc()
            EXECUTION_DURATION_SECONDS.labels(workflow=execution.workflow, status="succeeded").observe(monotonic() - started)
        except Exception as exc:
            execution.error = str(exc)
            transition(execution, ExecutionStatus.failed)
            EXECUTIONS_TOTAL.labels(workflow=execution.workflow, status="failed").inc()
            EXECUTION_DURATION_SECONDS.labels(workflow=execution.workflow, status="failed").observe(monotonic() - started)
        execution.updated_at = datetime.now(UTC)
        await self.repository.save(execution)
        return execution
