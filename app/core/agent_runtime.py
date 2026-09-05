from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.core.router import LLMRouter
from app.models.agent import AgentDefinition, AgentResult, AgentTask
from app.providers.base import LLMProvider, LLMRequest
from app.providers.ollama import OllamaProvider
from app.providers.openai import OpenAIProvider

AgentHandler = Callable[
    [AgentTask, AgentDefinition], dict[str, Any] | Awaitable[dict[str, Any]]
]


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._handlers: dict[str, AgentHandler] = {}

    def register(
        self, definition: AgentDefinition, handler: AgentHandler | None = None
    ) -> None:
        self._agents[definition.name] = definition
        if handler:
            self._handlers[definition.name] = handler

    def get(self, name: str) -> AgentDefinition | None:
        return self._agents.get(name)

    def handler(self, name: str) -> AgentHandler | None:
        return self._handlers.get(name)


class AgentRuntime:
    def __init__(
        self,
        registry: AgentRegistry,
        router: LLMRouter,
        providers: dict[str, LLMProvider] | None = None,
    ) -> None:
        self.registry = registry
        self.router = router
        self.providers = providers or {}

    async def execute_async(self, task: AgentTask) -> AgentResult:
        definition = self.registry.get(task.agent)
        if definition is None:
            raise ValueError(f"Unknown agent: {task.agent}")
        route = self.router.route("agent", definition.provider, definition.model)
        handler = self.registry.handler(task.agent)
        if handler is not None:
            output = handler(task, definition)
            if hasattr(output, "__await__"):
                output = await output
        else:
            provider = self.providers.get(route.provider)
            if provider is None:
                output: dict[str, Any] = {
                    "status": "accepted",
                    "agent": task.agent,
                    "input": task.input,
                }
            else:
                prompt = str(task.input.get("prompt", task.input))
                response = await provider.generate(
                    LLMRequest(
                        model=route.model,
                        prompt=prompt,
                        system=definition.system_prompt or None,
                    )
                )
                output = {"text": response.text, "usage": response.usage or {}}
        return AgentResult(
            task_id=task.id,
            output=output,
            provider=definition.provider or route.provider,
            model=definition.model or route.model,
        )

    def execute(self, task: AgentTask) -> AgentResult:
        raise RuntimeError("AgentRuntime.execute is synchronous; use execute_async")


registry = AgentRegistry()

# Prefer Ollama when configured, so the demo can run without paid API keys.
if settings.ollama_base_url:
    default_provider = "ollama"
    default_model = settings.ollama_model
elif settings.openai_api_key:
    default_provider = "openai"
    default_model = None
else:
    default_provider = None
    default_model = None

registry.register(
    AgentDefinition(
        name=settings.default_agent,
        system_prompt=(
            "You are the default automation agent. Execute the requested "
            "automation task accurately and return concise structured results."
        ),
        provider=default_provider,
        model=default_model,
    )
)

providers: dict[str, LLMProvider] = {}
if settings.ollama_base_url:
    providers["ollama"] = OllamaProvider(settings.ollama_base_url)
if settings.openai_api_key:
    providers["openai"] = OpenAIProvider(settings.openai_api_key)

agent_runtime = AgentRuntime(registry, LLMRouter(), providers)
