"""Schémas machine."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MachineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hostname: str | None
    os: str | None
    agent_version: str | None
    last_seen_at: datetime | None
    status: str
    created_at: datetime


class MachineCreated(BaseModel):
    """Réponse de création : le token d'enrôlement n'est montré qu'ici, une fois."""

    machine: MachineOut
    enroll_token: str
