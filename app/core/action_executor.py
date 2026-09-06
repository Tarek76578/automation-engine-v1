from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.integrations.meta import MetaGraphClient
from app.integrations.messenger_memory import messenger_memory


class ActionExecutor:
    """Execute built-in actions with explicit verification and SSRF protection."""

    def __init__(self, meta_client: MetaGraphClient | None = None) -> None:
        self.meta_client = meta_client or MetaGraphClient()

    async def execute(self, action: str, payload: dict[str, Any], execution_id: str) -> dict[str, Any]:
        if action == "prepare_message":
            message = str(payload.get("message", payload.get("value", ""))).strip()
            if not message:
                raise ValueError("message action requires a non-empty message")
            return {
                "action": action, "status": "executed",
                "delivery": {"channel": "local-demo", "execution_id": execution_id, "message": message},
                "verified": True, "verification": "local_demo_delivery_record_created",
            }

        if action in {"webhook", "http_webhook"}:
            return await self._execute_webhook(payload, execution_id)

        if action == "meta_page_info":
            result = await self.meta_client.page_info()
            return self._meta_result(action, result, execution_id)

        if action == "meta_page_messages":
            result = await self.meta_client.page_messages(int(payload.get("limit", 25)))
            return self._meta_result(action, result, execution_id)

        if action == "meta_page_post":
            result = await self.meta_client.publish_page_post(
                str(payload.get("message", "")), str(payload["link"]) if payload.get("link") else None,
            )
            return self._meta_result(action, result, execution_id)

        if action == "meta_page_reply":
            recipient_id = str(payload.get("recipient_id", ""))
            message = str(payload.get("message", "")).strip()
            page_id = str(payload.get("page_id", settings.meta_page_id))
            if not recipient_id or not message:
                raise ValueError("meta_page_reply requires recipient_id and non-empty message")
            result = await self.meta_client.send_page_message(recipient_id, message)
            if page_id:
                await messenger_memory.record_outbound(page_id, recipient_id, message, execution_id)
            return self._meta_result(action, result, execution_id)

        return {"action": action, "status": "planned", "verified": False, "verification": "no_builtin_action"}

    @staticmethod
    def _meta_result(action: str, result: dict[str, Any], execution_id: str) -> dict[str, Any]:
        return {
            "action": action, "status": "executed",
            "delivery": {"channel": "meta-graph-api", "execution_id": execution_id, "result": result},
            "verified": True, "verification": "meta_graph_api_2xx_response",
        }

    async def _execute_webhook(self, payload: dict[str, Any], execution_id: str) -> dict[str, Any]:
        raw_url = str(payload.get("webhook_url", "")).strip()
        if not raw_url:
            raise ValueError("webhook action requires webhook_url")
        url = self._validate_url(raw_url)
        body = payload.get("webhook_payload", payload)
        if not isinstance(body, dict):
            body = {"value": body}
        body = {"execution_id": execution_id, "payload": body}
        timeout = httpx.Timeout(15.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                url, json=body,
                headers={"User-Agent": "automation-engine/0.4", "Idempotency-Key": execution_id},
            )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"webhook returned HTTP {response.status_code}")
        return {
            "action": "webhook", "status": "executed",
            "delivery": {"channel": "http", "url": url, "status_code": response.status_code, "idempotency_key": execution_id},
            "verified": True, "verification": "http_2xx_response",
        }

    @staticmethod
    def _validate_url(raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("webhook_url must use HTTPS")
        host = parsed.hostname.lower().rstrip(".")
        allowed = {item.strip().lower().rstrip(".") for item in settings.action_webhook_allowlist.split(",") if item.strip()}
        if allowed and host not in allowed:
            raise ValueError("webhook host is not in ACTION_WEBHOOK_ALLOWLIST")
        if not allowed:
            raise ValueError("ACTION_WEBHOOK_ALLOWLIST must be configured for webhook actions")
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ValueError("webhook host could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("webhook host resolves to a blocked IP address")
        return raw_url


action_executor = ActionExecutor()
