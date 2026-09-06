from __future__ import annotations

import hashlib
from typing import Any


class MetaMessengerEventError(ValueError):
    """Raised when a Meta Messenger webhook event is malformed."""


def _first_message(event: dict[str, Any]) -> dict[str, Any] | None:
    messaging = event.get("messaging")
    if not isinstance(messaging, list):
        return None
    for item in messaging:
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        sender = item.get("sender")
        if isinstance(message, dict) and isinstance(sender, dict):
            text = message.get("text")
            sender_id = sender.get("id")
            if isinstance(text, str) and text.strip() and sender_id:
                return {
                    "sender_id": str(sender_id),
                    "message": text.strip(),
                    "message_id": str(message.get("mid", "")),
                    "timestamp": item.get("timestamp"),
                }
    return None


def parse_page_messenger_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "page":
        return []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []
    events: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id", ""))
        event = _first_message(entry)
        if event is None:
            continue
        event["page_id"] = page_id
        event["event_id"] = event["message_id"] or stable_event_id(page_id, event)
        events.append(event)
    return events


def stable_event_id(page_id: str, event: dict[str, Any]) -> str:
    raw = "|".join(
        [
            page_id,
            str(event.get("sender_id", "")),
            str(event.get("timestamp", "")),
            str(event.get("message", "")),
        ]
    )
    return "meta:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
