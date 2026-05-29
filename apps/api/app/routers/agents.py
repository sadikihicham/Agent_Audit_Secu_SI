"""Enrôlement des agents.

L'agent présente son token d'enrôlement (usage unique) et reçoit un JWT agent
longue durée. L'endpoint n'est pas protégé par JWT : le token d'enrôlement fait
office d'authentification, puis il est consommé.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.security import create_agent_token, hash_enroll_token
from app.deps import DbSession
from app.models import Machine
from app.schemas.agent import EnrollRequest, EnrollResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(payload: EnrollRequest, db: DbSession) -> EnrollResponse:
    token_hash = hash_enroll_token(payload.enroll_token)
    machine = await db.scalar(
        select(Machine).where(Machine.enroll_token_hash == token_hash)
    )
    if machine is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'enrôlement invalide ou déjà utilisé",
        )

    # Consommer le token (usage unique) et enregistrer les infos de l'agent.
    machine.enroll_token_hash = None
    machine.hostname = payload.hostname
    machine.os = payload.os
    machine.agent_version = payload.agent_version
    await db.commit()

    return EnrollResponse(
        machine_id=machine.id,
        agent_token=create_agent_token(machine.id),
    )
