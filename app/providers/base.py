from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    model: str
    prompt: str
    system: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    text: str
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


class ProviderNotConfigured(RuntimeError):
    pass
