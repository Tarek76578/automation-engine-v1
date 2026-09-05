from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.agent_runtime import agent_runtime
from app.core.config import settings
from app.core.orchestrator import ExecutionOrchestrator
from app.core.persistence import execution_repository
from app.core.job_queue import queue
from app.integrations.n8n import N8nClient
from app.models.execution import Execution, ExecutionRequest

router = APIRouter(prefix="/executions", tags=["executions"])

n8n_client = N8nClient(settings.n8n_base_url) if settings.n8n_base_url else None
orchestrator = ExecutionOrchestrator(execution_repository, queue, agent_runtime, n8n_client)


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


@router.post("/{execution_id}/run", response_model=Execution)
async def run_execution(execution_id: UUID) -> Execution:
    execution = await orchestrator.process(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution
