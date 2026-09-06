from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.agent_runtime import agent_runtime
from app.core.config import settings
from app.core.orchestrator import ExecutionOrchestrator
from app.core.persistence import execution_repository
from app.integrations.n8n import N8nClient
from app.models.execution import Execution, ExecutionRequest

router = APIRouter(prefix="/executions", tags=["executions"])

n8n_client = N8nClient(settings.n8n_base_url) if settings.n8n_base_url else None
orchestrator = ExecutionOrchestrator(execution_repository, queue, agent_runtime, n8n_client)


class ApprovalDecision(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    decided_by: str = Field(default="api", min_length=1, max_length=200)


class ApprovalResponse(BaseModel):
    execution: Execution
    approval_token: str | None = None


@router.post("", response_model=Execution, status_code=202)
async def create_execution(request: ExecutionRequest) -> Execution:
    execution = Execution(workflow=request.workflow, input=request.input)
    return await orchestrator.submit(execution, request.idempotency_key)


@router.get("/{execution_id}", response_model=Execution)
async def get_execution(execution_id: UUID) -> Execution:
    execution = await execution_repository.get(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/{execution_id}/run", response_model=ApprovalResponse)
async def run_execution(execution_id: UUID) -> ApprovalResponse:
    execution = await orchestrator.process(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ApprovalResponse(execution=execution, approval_token=execution.approval_token)


@router.post("/{execution_id}/approval/request", response_model=ApprovalResponse)
async def request_approval(execution_id: UUID) -> ApprovalResponse:
    execution, token = await orchestrator.request_approval(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ApprovalResponse(execution=execution, approval_token=token)


@router.post("/{execution_id}/approval/approve", response_model=Execution)
async def approve_execution(execution_id: UUID, request: ApprovalDecision) -> Execution:
    try:
        execution = await orchestrator.approve(str(execution_id), request.token, request.decided_by)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/{execution_id}/approval/reject", response_model=Execution)
async def reject_execution(execution_id: UUID, request: ApprovalDecision) -> Execution:
    try:
        execution = await orchestrator.reject(str(execution_id), request.token, request.decided_by)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution
