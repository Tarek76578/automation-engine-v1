from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.agent_runtime import agent_runtime
from app.core.config import settings
from app.core.job_queue import queue
from app.core.orchestrator import ExecutionOrchestrator
from app.core.persistence import execution_repository
from app.integrations.meta import meta_graph_client, verify_webhook_signature
from app.integrations.meta_messenger import parse_page_messenger_events
from app.integrations.meta_oauth import MetaOAuthError, meta_oauth_manager
from app.integrations.messenger_memory import messenger_memory
from app.models.execution import Execution

router = APIRouter(prefix="/meta", tags=["meta"])

_meta_orchestrator = ExecutionOrchestrator(execution_repository, queue, agent_runtime)


@router.get("/oauth/start")
async def meta_oauth_start(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        url, _ = await meta_oauth_manager.authorization_url()
    except MetaOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.get("/oauth/callback")
async def meta_oauth_callback(
    response: Response, code: str = "", state: str = "", error: str = ""
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    if error:
        raise HTTPException(status_code=400, detail=f"Meta OAuth denied: {error}")
    try:
        result = await meta_oauth_manager.callback(code, state)
        credentials = meta_oauth_manager.credentials()
        if credentials:
            meta_graph_client.configure(credentials["page_id"], credentials["page_access_token"])
        return result
    except MetaOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/status")
async def meta_oauth_status() -> dict[str, object]:
    credentials = meta_oauth_manager.credentials()
    return {
        "oauth_configured": meta_oauth_manager.configured,
        "storage_configured": meta_oauth_manager.storage_configured,
        "connected": bool(credentials),
        "page_id": credentials.get("page_id") if credentials else None,
        "page_name": credentials.get("page_name") if credentials else None,
    }


@router.get("/webhook")
async def meta_webhook_verify(request: Request) -> JSONResponse:
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    if mode != "subscribe" or not settings.meta_webhook_verify_token:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    if not token or token != settings.meta_webhook_verify_token:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return JSONResponse(content=int(challenge) if challenge.isdigit() else challenge)


@router.post("/webhook")
async def meta_webhook_receive(request: Request) -> dict[str, object]:
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid Meta webhook signature")
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload") from exc
    if not isinstance(payload, dict) or payload.get("object") not in {"page", "instagram"}:
        raise HTTPException(status_code=400, detail="Unsupported Meta webhook object")

    events = parse_page_messenger_events(payload)
    accepted: list[dict[str, object]] = []
    for event in events:
        event_id = str(event["event_id"])
        page_id = str(event["page_id"])
        sender_id = str(event["sender_id"])
        message = str(event["message"])
        await messenger_memory.record_inbound(page_id, sender_id, message, event_id, event.get("timestamp"))
        context = await messenger_memory.recent_context(page_id, sender_id, limit=settings.meta_messenger_context_messages)
        execution = Execution(
            workflow="meta_messenger",
            input={
                "message": message,
                "recipient_id": sender_id,
                "page_id": page_id,
                "event_id": event_id,
                "message_id": event.get("message_id"),
                "timestamp": event.get("timestamp"),
                "conversation_key": f"meta:{page_id}:{sender_id}",
                "conversation_context": context,
                "meta_messenger_inbound": True,
                "meta_messenger_auto_reply": settings.meta_messenger_auto_reply,
            },
        )
        saved = await _meta_orchestrator.submit(execution, event_id)
        accepted.append({"event_id": event_id, "execution_id": str(saved.id), "status": saved.status.value, "deduplicated": str(saved.id) != str(execution.id)})

    return {
        "received": True,
        "entries": len(payload.get("entry", [])) if isinstance(payload.get("entry"), list) else 0,
        "messenger_events": len(events),
        "accepted": accepted,
    }
