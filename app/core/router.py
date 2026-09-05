from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


class LLMRouter:
    """Provider-neutral routing policy; provider clients are added next."""

    def route(self, task: str, preferred_provider: str | None = None) -> ModelRoute:
        provider = preferred_provider or "openai"
        defaults = {
            "openai": "gpt-5",
            "anthropic": "claude-sonnet",
            "google": "gemini-flash",
        }
        return ModelRoute(provider=provider, model=defaults.get(provider, defaults["openai"]))


llm_router = LLMRouter()
