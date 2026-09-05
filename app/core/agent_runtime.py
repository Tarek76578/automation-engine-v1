from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.router import LLMRouter
from app.models.agent import AgentDefinition, AgentResult, AgentTask

AgentHandler = Callable[[AgentTask, AgentDefinition], dict[str, Any]]


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._handlers: dict[str, AgentHandler] = {}

    def register(self, definition: AgentDefinition, handler: AgentHandler | None = None) -> None:
        self._agents[definition.name] = definition
        if handler:
            self._handlers[definition.name] = handler

    def get(self, name: str) -> AgentDefinition | None:
        return self._agents.get(name)

    def handler(self, name: str) -> AgentHandler | None:
        return self._handlers.get(name)


class AgentRuntime:
    """Provider-neutral execution boundary for registered agents.

    External LLM calls are deliberately injected as handlers so the runtime
    remains testable and provider adapters can evolve independently.
    """

    def __init__(self, registry: AgentRegistry, router: LLMRouter) -> None:
        self.registry = registry
        self.router = router

    def execute(self, task: AgentTask) -> AgentResult:
        definition = self.registry.get(task.agent)
        if definition is None:
            raise ValueError(f"Unknown agent: {task.agent}")

        route = self.router.route("agent", definition.provider)
        handler = self.registry.handler(task.agent)
        if handler is None:
            output: dict[str, Any] = {
                "status": "accepted",
                "agent": task.agent,
                "input": task.input,
            }
        else:
            output = handler(task, definition)

        return AgentResult(
            task_id=task.id,
            output=output,
            provider=definition.provider or route.provider,
            model=definition.model or route.model,
        )


registry = AgentRegistry()
agent_runtime = AgentRuntime(registry, LLMRouter())
