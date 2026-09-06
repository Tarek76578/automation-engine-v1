from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.integrations.meta import meta_graph_client, verify_webhook_signature
from app.integrations.meta_oauth import MetaOAuthError, meta_oauth_manager

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/oauth/start")
async def meta_oauth_start() -> dict[str, str]:
    try:
        url, _ = meta_oauth_manager.authorization_url()
    except MetaOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.get("/oauth/callback")
async def meta_oauth_callback(code: str = "", state: str = "", error: str = "") -> dict[str, object]:
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
        "connected": bool(credentials),
        "page_id": credentials.get("page_id") if credentials else None,
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
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        entries = []
    return {"received": True, "entries": len(entries)}
