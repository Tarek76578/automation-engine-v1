from __future__ import annotations

from app.providers.base import LLMRequest, LLMResponse, ProviderNotConfigured

import httpx


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        if not api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": request.model, "messages": messages},
            )
            response.raise_for_status()
            payload = response.json()
        choice = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage")
        return LLMResponse(provider=self.name, model=request.model, text=choice, usage=usage)
