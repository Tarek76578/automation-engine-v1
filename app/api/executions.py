from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.execution_store import store
from app.models.execution import Execution, ExecutionRequest, ExecutionStatus

router = APIRouter(prefix="/executions", tags=["executions"])


@router.post("", response_model=Execution, status_code=202)
def create_execution(request: ExecutionRequest) -> Execution:
    execution = Execution(workflow=request.workflow, input=request.input)
    return store.create(execution, request.idempotency_key)


@router.get("/{execution_id}", response_model=Execution)
def get_execution(execution_id: UUID) -> Execution:
    execution = store.get(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/{execution_id}/complete", response_model=Execution)
def complete_execution(execution_id: UUID, output: dict | None = None) -> Execution:
    execution = store.get(str(execution_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    execution.status = ExecutionStatus.succeeded
    execution.output = output or {}
    return execution
