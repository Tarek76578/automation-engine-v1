from app.core.agent_runtime import registry
from app.main import app
from app.models.agent import AgentDefinition

from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_execution_idempotency() -> None:
    payload = {
        "workflow": "lead-enrichment",
        "input": {"lead": "123"},
        "idempotency_key": "abc-123",
    }
    first = client.post("/api/executions", json=payload)
    second = client.post("/api/executions", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_agent_execution() -> None:
    registry.register(AgentDefinition(name="test-agent"))
    response = client.post(
        "/api/agents/execute",
        json={"agent": "test-agent", "input": {"x": 1}},
    )
    assert response.status_code == 200
    assert response.json()["output"]["status"] == "accepted"
