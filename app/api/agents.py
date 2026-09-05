from fastapi import APIRouter, HTTPException

from app.core.agent_runtime import agent_runtime
from app.models.agent import AgentResult, AgentTask

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/execute", response_model=AgentResult, status_code=202)
def execute_agent(task: AgentTask) -> AgentResult:
    try:
        return agent_runtime.execute(task)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
