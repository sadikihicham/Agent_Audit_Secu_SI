# Agent_Audit_Secu_SI — GuardianOps AI

Plateforme open source d'**audit permanent SI**, monitoring temps réel, analyse IA,
prédiction de panne, sécurité IT et auto-remediation.

> **Statut** : MVP en cours — **Phase 0 (Socle & infra)** terminée.
> Voir [`PLAN.md`](./PLAN.md) pour le plan d'implémentation complet.

## Architecture (MVP)

```
Agent Rust  ──►  API FastAPI  ◄──►  Dashboard Next.js
                 + PostgreSQL/TimescaleDB
                 + Redis
```

| Service   | Techno                          | Port hôte |
|-----------|---------------------------------|-----------|
| API       | FastAPI (Python 3.12)           | `8800`    |
| Web       | Next.js 14 (App Router, dark)   | `3300`    |
| Base      | PostgreSQL 16 + TimescaleDB     | `5433`    |
| Cache/bus | Redis 7                         | `6380`    |

> Ports décalés volontairement pour éviter les conflits avec d'autres projets locaux.

## Démarrage rapide

```bash
# 1. Copier la config d'environnement
cp .env.example .env

# 2. Lancer toute la stack
docker compose up --build

# 3. Vérifier
#    - API liveness  : http://localhost:8800/health
#    - API readiness : http://localhost:8800/health/ready   (DB + Redis)
#    - API docs      : http://localhost:8800/docs
#    - Dashboard     : http://localhost:3300
```

Le dashboard affiche en direct l'état de l'API (badge vert = chaîne web→API OK).

## Structure du dépôt

```
.
├── apps/
│   ├── api/        # Backend FastAPI (+ Alembic, prêt pour Phase 1)
│   └── web/        # Dashboard Next.js
├── agent/          # Agent Rust (Phase 2 — à venir)
├── docs/           # Documentation d'architecture
├── docker-compose.yml
└── PLAN.md         # Plan d'implémentation MVP
```

## Prochaines phases

- **Phase 1** — Backend cœur (modèles, auth JWT, ingestion, alerting, WebSocket).
- **Phase 2** — Agent Rust (collecteurs, enrôlement, offline queue).
- **Phase 3** — Dashboard (machines, métriques temps réel, alertes).
- **Phase 4** — Intégration end-to-end & durcissement sécurité.
