# Architecture — GuardianOps AI (MVP)

## Vue d'ensemble

```
┌──────────────┐   POST /ingest (JWT agent)   ┌──────────────────────┐
│  Agent Rust  │ ───────────────────────────► │      API FastAPI     │
│ (1 machine)  │   POST /ingest/heartbeat     │  ┌────────────────┐  │
└──────────────┘                              │  │  routers       │  │
                                              │  │  services      │  │
┌──────────────┐   REST (JWT user) + WS       │  │  models (ORM)  │  │
│  Next.js UI  │ ◄──────────────────────────► │  └────────────────┘  │
│ (dashboard)  │                              └───────┬──────────────┘
└──────────────┘                                      │
                                          ┌───────────┴───────────┐
                                          │                       │
                                   ┌──────▼──────┐         ┌──────▼──────┐
                                   │ PostgreSQL  │         │    Redis    │
                                   │ +TimescaleDB│         │  pub/sub +  │
                                   │ (hypertable │         │   cache     │
                                   │  metrics)   │         └─────────────┘
                                   └─────────────┘
```

## Composants

### API FastAPI (`apps/api`)
- `app/core/config.py` — configuration via variables d'environnement (pydantic-settings).
- `app/core/db.py` — moteur SQLAlchemy **async** (driver `psycopg`) + dépendance `get_session`.
- `app/core/redis.py` — client Redis async partagé (pub/sub temps réel + cache).
- `app/main.py` — app FastAPI, CORS, endpoints `/health` (liveness) et `/health/ready` (DB+Redis).
- `alembic/` — migrations (scaffold prêt ; tables créées en Phase 1).

### Dashboard Next.js (`apps/web`)
- App Router, TypeScript, Tailwind, dark mode par défaut.
- `app/page.tsx` — page d'accueil + `HealthBadge` qui interroge `/health` pour prouver la chaîne web→API.
- `NEXT_PUBLIC_API_URL` — URL de l'API côté navigateur (`http://localhost:8800`).

### Données
- **PostgreSQL 16 + TimescaleDB** — métriques en hypertable (séries temporelles).
- **Redis 7** — bus pub/sub pour le temps réel (WebSocket) et cache léger.

## Sécurité (cible MVP)
- Deux types de JWT : `user` (lecture dashboard) et `agent` (ingestion seulement).
- Token d'enrôlement à usage unique, stocké hashé.
- Mots de passe hashés (argon2). CORS restreint à l'origine du dashboard.
- Secrets exclusivement via variables d'environnement.

## Décisions techniques
| Décision | Choix | Justification |
|----------|-------|---------------|
| Base séries temporelles | TimescaleDB | hypertables natives, compatible SQL Postgres |
| Temps réel | WebSocket + Redis pub/sub | bidirectionnel, extensible |
| Driver DB | psycopg 3 (async) | maintenu, async natif |
| Ports | décalés (8800/3300/5433/6380) | éviter conflits avec autres projets locaux |
