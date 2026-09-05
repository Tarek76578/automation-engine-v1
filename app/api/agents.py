from app.core.agent_runtime import agent_runtime
from app.models.agent import AgentResult, AgentTask

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/execute", response_model=AgentResult, status_code=200)
async def execute_agent(task: AgentTask) -> AgentResult:
    try:
        return await agent_runtime.execute_async(task)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
