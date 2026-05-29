"""WebSocket temps réel — abonnement aux événements via Redis pub/sub.

Authentification en deux étapes pour éviter d'exposer le JWT dans les URLs
(et donc dans les access logs uvicorn/nginx) :

  1. Client POST /ws/ticket  (Authorization: Bearer <jwt_user>)
     → reçoit un ticket opaque à usage unique, TTL 30 s, stocké dans Redis.

  2. Client ouvre WS /ws?ticket=<opaque>
     → serveur récupère + supprime le ticket atomiquement (GETDEL),
       valide que l'utilisateur existe, puis maintient la connexion.

Le JWT ne transite jamais dans une query string.
"""
from __future__ import annotations

import asyncio
import logging
import secrets

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.core.redis import redis_client
from app.deps import CurrentUser
from app.services.alerting import REDIS_EVENTS_CHANNEL

log = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_TICKET_PREFIX = "ws_ticket:"
_TICKET_TTL_S = 30  # ticket valable 30 secondes, usage unique


class WsTicketOut(BaseModel):
    ticket: str
    ttl_seconds: int = _TICKET_TTL_S


# ── Étape 1 : obtenir un ticket ───────────────────────────────────────────────

@router.post(
    "/ws/ticket",
    response_model=WsTicketOut,
    status_code=status.HTTP_201_CREATED,
    summary="Obtenir un ticket WS à usage unique (TTL 30 s)",
)
async def create_ws_ticket(current_user: CurrentUser) -> WsTicketOut:
    """Émet un ticket opaque court-vécu pour ouvrir le WebSocket sans JWT dans l'URL."""
    ticket = secrets.token_urlsafe(16)  # 128 bits d'entropie
    await redis_client.setex(f"{_TICKET_PREFIX}{ticket}", _TICKET_TTL_S, str(current_user.id))
    return WsTicketOut(ticket=ticket)


# ── Étape 2 : connexion WebSocket ─────────────────────────────────────────────

@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, ticket: str = Query(...)) -> None:
    """Flux d'événements temps réel (alertes).

    Nécessite un ticket obtenu via POST /ws/ticket — jamais un JWT directement.
    """
    # Récupération + suppression atomique (GETDEL) → usage unique garanti.
    user_id_str: str | None = await redis_client.getdel(f"{_TICKET_PREFIX}{ticket}")
    if user_id_str is None:
        await websocket.close(code=1008, reason="Ticket invalide ou expiré")
        return

    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(REDIS_EVENTS_CHANNEL)
    log.debug("WS client connected, user_id=%s", user_id_str)

    async def _forward_redis() -> None:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                await websocket.send_text(msg["data"])

    async def _watch_disconnect() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    fwd = asyncio.create_task(_forward_redis())
    watch = asyncio.create_task(_watch_disconnect())
    try:
        _done, pending = await asyncio.wait([fwd, watch], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        await pubsub.unsubscribe(REDIS_EVENTS_CHANNEL)
        await pubsub.aclose()
        log.debug("WS client disconnected, user_id=%s", user_id_str)
