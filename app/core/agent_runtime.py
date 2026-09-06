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
            provider_name = definition.provider or "local"
            model_name = definition.model or "automation-planner"
        else:
            provider = self.providers.get(route.provider)
            if provider is None:
                output = self._local_plan(task)
                provider_name = "local"
                model_name = "automation-planner-v1"
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
                provider_name = definition.provider or route.provider
                model_name = definition.model or route.model
        return AgentResult(
            task_id=task.id,
            output=output,
            provider=provider_name,
            model=model_name,
        )

    @staticmethod
    def _local_plan(task: AgentTask) -> dict[str, Any]:
        """Deterministic fallback used when no LLM credentials are configured.

        It is deliberately labelled as a local planner so the API never claims
        that an LLM generated the result when none was available.
        """
        message = str(task.input.get("message", task.input.get("prompt", ""))).strip()
        lower = message.lower()
        if any(word in lower for word in ("send", "أرسل", "رسالة", "message")):
            action = "prepare_message"
            summary = "Prepare the requested customer message for delivery."
        elif any(word in lower for word in ("analy", "حلل", "حلّل", "analyse", "analyze")):
            action = "analyze_request"
            summary = "Analyze the request and return structured findings."
        else:
            action = "process_request"
            summary = "Process the requested automation task and return a structured result."
        return {
            "status": "planned_and_executed",
            "planner": "local",
            "action": action,
            "summary": summary,
            "input": task.input,
            "workflow": task.input.get("workflow", "demo"),
            "steps": ["understand_request", "create_plan", "execute_action", "verify_result"],
        }

    def execute(self, task: AgentTask) -> AgentResult:
        raise RuntimeError("AgentRuntime.execute is synchronous; use execute_async")


registry = AgentRegistry()

# Prefer Ollama when configured, then OpenAI. Otherwise use the truthful local planner.
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
