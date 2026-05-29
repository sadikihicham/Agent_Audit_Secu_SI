"""Schémas d'enrôlement agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class EnrollRequest(BaseModel):
    enroll_token: str = Field(min_length=1)
    hostname: str = Field(min_length=1, max_length=255)
    os: str | None = Field(default=None, max_length=128)
    agent_version: str | None = Field(default=None, max_length=64)


class EnrollResponse(BaseModel):
    machine_id: int
    agent_token: str
