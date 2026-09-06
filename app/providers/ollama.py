from __future__ import annotations

import httpx

from app.providers.base import LLMRequest, LLMResponse, ProviderNotConfigured


class OllamaProvider:
    """Ollama provider using Ollama's OpenAI-compatible chat endpoint."""

    name = "ollama"

    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        if not base_url:
            raise ProviderNotConfigured("OLLAMA_BASE_URL is not configured")
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": request.model,
                    "messages": messages,
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        choice = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage")
        return LLMResponse(provider=self.name, model=request.model, text=choice, usage=usage)
