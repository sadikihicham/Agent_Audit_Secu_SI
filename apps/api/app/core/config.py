"""Configuration centralisée, lue depuis les variables d'environnement."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_name: str = "GuardianOps AI"
    environment: str = "development"

    # Base de données
    database_url: str = "postgresql+psycopg://guardian:guardian@db:5432/guardianops"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Sécurité
    jwt_secret: str = "change-me-in-production"
    jwt_alg: str = "HS256"
    access_token_ttl_minutes: int = 30
    agent_token_ttl_days: int = 365

    # CORS — liste séparée par des virgules
    cors_origins: str = "http://localhost:3300"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
