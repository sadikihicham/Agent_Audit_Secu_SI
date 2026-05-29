"""Configuration centralisée, lue depuis les variables d'environnement."""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valeurs par défaut connues — refusées au démarrage.
_WEAK_SECRETS = frozenset(
    {
        "change-me-in-production",
        "change-me-in-production-please-use-a-long-random-string",
        "secret",
        "jwt_secret",
    }
)


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

    # Alerting — seuils configurables (cf. PLAN.md §3)
    alert_cpu_threshold: float = 90.0
    alert_mem_threshold: float = 90.0
    alert_disk_threshold: float = 90.0
    alert_cpu_consecutive_points: int = 3
    alert_offline_minutes: int = 2

    # CORS — liste séparée par des virgules
    cors_origins: str = "http://localhost:3300"

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_strong(cls, v: str) -> str:
        if v in _WEAK_SECRETS or len(v) < 32:
            raise ValueError(
                "JWT_SECRET est trop faible ou utilise une valeur par défaut connue. "
                "Définissez une valeur aléatoire d'au moins 32 caractères dans .env.\n"
                "  python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
