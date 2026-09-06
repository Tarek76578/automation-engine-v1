from __future__ import annotations

from typing import Any


class ActionExecutor:
    """Executes safe built-in actions and returns a verifiable result.

    The local message action deliberately does not contact a real customer channel.
    It creates a delivery record in the execution result so the engine can prove
    the execute -> verify lifecycle without pretending that an external message
    was delivered.
    """

    async def execute(
        self, action: str, payload: dict[str, Any], execution_id: str
    ) -> dict[str, Any]:
        if action == "prepare_message":
            message = str(payload.get("message", payload.get("value", ""))).strip()
            if not message:
                raise ValueError("message action requires a non-empty message")
            return {
                "action": action,
                "status": "executed",
                "delivery": {
                    "channel": "local-demo",
                    "execution_id": execution_id,
                    "message": message,
                },
                "verified": True,
                "verification": "local_demo_delivery_record_created",
            }

        return {
            "action": action,
            "status": "planned",
            "verified": False,
            "verification": "no_builtin_action",
        }


action_executor = ActionExecutor()
