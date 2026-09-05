from __future__ import annotations

from typing import Any

import httpx


class N8nClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)

    async def trigger_webhook(self, webhook_path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("N8N_BASE_URL is not configured")
        path = webhook_path.lstrip("/")
        url = f"{self.base_url}/{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            if not response.content:
                return {"status": "accepted"}
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}
