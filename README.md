# Agent_Audit_Secu_SI — GuardianOps AI

[![CI](https://github.com/HichamSADIKI/Agent_Audit_Secu_SI/actions/workflows/ci.yml/badge.svg)](https://github.com/HichamSADIKI/Agent_Audit_Secu_SI/actions/workflows/ci.yml)

Plateforme open source d'**audit permanent SI**, monitoring temps réel, analyse IA,
prédiction de panne, sécurité IT et auto-remediation.

> **Statut** : **MVP complet** — chaîne end-to-end fonctionnelle (Agent Rust → API → Dashboard).
> Plan complet : [`PLAN.md`](./PLAN.md) · Architecture : [`docs/architecture.md`](./docs/architecture.md) · Exploitation : [`docs/runbook.md`](./docs/runbook.md).

## Architecture (MVP)

```
Agent Rust  ──►  API FastAPI  ◄──►  Dashboard Next.js
   (sysinfo)     + PostgreSQL/TimescaleDB
                 + Redis (pub/sub temps réel)
```

| Service   | Techno                          | Port hôte |
|-----------|---------------------------------|-----------|
| API       | FastAPI (Python 3.12)           | `8800`    |
| Web       | Next.js 14 (App Router, dark)   | `3300`    |
| Base      | PostgreSQL 16 + TimescaleDB     | `5433`    |
| Cache/bus | Redis 7                         | `6380`    |
| Agent     | Rust (tokio, reqwest, sysinfo)  | —         |

> Ports décalés volontairement pour éviter les conflits avec d'autres projets locaux.

## Démarrage rapide

```bash
# 1. Config d'environnement
cp .env.example .env
# Générer un JWT_SECRET fort (l'API refuse de démarrer sinon) :
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"   # → coller dans .env

# 2. Lancer la stack
docker compose up --build -d db redis api web

# 3. Migrations + compte admin
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli create-admin admin@guardianops.ai 'MotDePasseFort!'

# 4. Vérifier
#    - API liveness  : http://localhost:8800/health
#    - API readiness : http://localhost:8800/health/ready   (DB + Redis)
#    - API docs      : http://localhost:8800/docs
#    - Dashboard     : http://localhost:3300   (login avec le compte admin)
```

Pour brancher un agent et voir les métriques temps réel, suivre la **démo end-to-end**
du [runbook](./docs/runbook.md#3-démo-end-to-end-agent--api--dashboard).

## Fonctionnalités (MVP)

- **Auth** — JWT user (dashboard) + JWT agent (ingestion), claim `type` vérifié ; argon2.
- **Enrôlement** — token à usage unique, stocké hashé, échangé contre un JWT agent.
- **Ingestion** — métriques par batch dans une hypertable TimescaleDB ; file offline idempotente.
- **Alerting** — seuils CPU/RAM/Disque + détection offline, auto-résolution, events Redis.
- **Détection d'anomalies** — z-score robuste par machine (médiane/MAD) : repère un écart au comportement habituel même sous les seuils absolus.
- **Temps réel** — WebSocket (auth par ticket à usage unique) → dashboard live.
- **Dashboard** — login, vue parc, détail machine (graphes), alertes filtrables.

## Structure du dépôt

```
.
├── apps/
│   ├── api/        # Backend FastAPI (models, auth, ingestion, alerting, WS, Alembic)
│   └── web/        # Dashboard Next.js (App Router, TanStack Query, Recharts)
├── agent/          # Agent Rust (collecte, enrôlement, file offline)
├── docs/           # architecture.md + runbook.md
├── docker-compose.yml
└── PLAN.md
```

## Tests & qualité

```bash
# Backend (pytest + ruff)
docker compose run --rm api sh -c "pip install -r requirements-dev.txt && pytest -q && ruff check ."

# Frontend (typecheck + lint)
docker compose exec web sh -c "npx tsc --noEmit && npm run lint"
```
