# Architecture — GuardianOps AI (MVP)

> Statut : **MVP complet** — Phases 0→4 livrées. Chaîne end-to-end fonctionnelle :
> Agent Rust → API FastAPI → PostgreSQL/TimescaleDB + Redis → Dashboard Next.js.

## Vue d'ensemble

```
┌──────────────┐  POST /agents/enroll (token)  ┌──────────────────────┐
│  Agent Rust  │  POST /ingest/metrics (JWT)   │      API FastAPI     │
│ (1 machine)  │  POST /ingest/heartbeat       │  ┌────────────────┐  │
└──────────────┘ ────────────────────────────► │  │  routers       │  │
                                                │  │  services      │  │
┌──────────────┐  REST (JWT user)               │  │  models (ORM)  │  │
│  Next.js UI  │  + WS /ws?ticket=…             │  └────────────────┘  │
│ (dashboard)  │ ◄────────────────────────────► └───────┬──────────────┘
└──────────────┘                                        │
                                          ┌─────────────┴─────────────┐
                                   ┌──────▼──────┐            ┌────────▼────────┐
                                   │ PostgreSQL  │            │      Redis      │
                                   │ +TimescaleDB│            │ pub/sub (events)│
                                   │ hypertable  │            │ + tickets WS    │
                                   │  metrics    │            └─────────────────┘
                                   └─────────────┘
```

## Flux de données

1. **Enrôlement** — l'admin crée une machine (`POST /machines`) → `enroll_token` (haute
   entropie) renvoyé **une seule fois**, stocké hashé (sha256). L'agent présente ce token
   (`POST /agents/enroll`) → reçoit un **JWT agent** longue durée ; le token est consommé.
2. **Ingestion** — l'agent collecte CPU/RAM/Disque/uptime, envoie par batch
   (`POST /ingest/metrics`, JWT agent) → insertion bulk dans l'hypertable avec
   `ON CONFLICT DO NOTHING` (idempotence pour la vidange de la file offline). Heartbeat
   met à jour `last_seen_at` + statut.
3. **Alerting** — après chaque ingestion, le service de seuils ouvre/résout les alertes,
   puis le service d'anomalies compare chaque métrique à la base de référence propre à
   la machine (z-score robuste) ; une tâche de fond (30 s) détecte les machines `offline`.
   Chaque changement d'état publie un événement sur le canal Redis `guardianops:events`.
4. **Temps réel** — le dashboard ouvre un WebSocket (`WS /ws?ticket=…`) qui relaie les
   événements Redis ; les vues invalident leur cache TanStack Query à réception.

## Composants

### API FastAPI (`apps/api/app`)
- `core/config.py` — settings via env (pydantic-settings) ; **validation du `jwt_secret`**
  (refus des valeurs faibles, min 32 car.) ; seuils d'alerte configurables.
- `core/db.py` — moteur SQLAlchemy **async** (psycopg 3), `Base`, dépendance `get_session`.
- `core/redis.py` — client Redis async partagé.
- `core/security.py` — argon2 (mots de passe), JWT user/agent (python-jose), génération +
  hash sha256 des tokens d'enrôlement.
- `deps.py` — dépendances d'auth : `get_current_user` / `get_current_agent` (vérifient la
  signature **et le claim `type`**).
- `routers/` — `auth`, `machines`, `agents`, `ingest`, `alerts`, `ws`.
- `services/` — `ingestion` (bulk insert), `alerting` (règles de seuils + pub/sub),
  `anomaly` (détection statistique par machine : z-score robuste médiane/MAD →
  `cpu/mem/disk_anomaly`, complète les seuils absolus).
- `models/` — `User`, `Machine`, `Metric` (hypertable), `Alert`.
- `alembic/` — migrations (`0001` schéma initial + hypertable, `0002` hostname nullable).

### Modèle de données

| Table      | Clés / particularités |
|------------|------------------------|
| `users`    | `id`, `email` (unique), `hashed_password` (argon2), `role` (`admin` au MVP) |
| `machines` | `id`, `name`, `hostname?`, `os?`, `enroll_token_hash?` (unique), `agent_version?`, `last_seen_at?`, `status` |
| `metrics`  | **hypertable** TimescaleDB, PK composite `(machine_id, time)`, `cpu/mem/disk_pct`, `uptime_s` |
| `alerts`   | `id`, `machine_id`, `type`, `severity`, `message`, `value?`, `threshold?`, `status`, `resolved_at?` |

### Endpoints

| Méthode | Chemin | Auth | Rôle |
|---------|--------|------|------|
| POST | `/auth/login` | — | login user → JWT |
| GET  | `/auth/me` | user | profil courant |
| POST | `/machines` | user | créer machine → `enroll_token` |
| GET  | `/machines` | user | liste du parc |
| GET  | `/machines/{id}` | user | détail machine |
| GET  | `/machines/{id}/metrics?range=1h\|6h\|24h\|7d` | user | série temporelle |
| POST | `/agents/enroll` | enroll_token | enrôlement → JWT agent |
| POST | `/ingest/metrics` | agent | ingestion batch |
| POST | `/ingest/heartbeat` | agent | heartbeat |
| GET  | `/alerts?status=open\|resolved` | user | liste des alertes |
| POST | `/ws/ticket` | user | ticket WS à usage unique (TTL 30 s) |
| WS   | `/ws?ticket=…` | ticket | flux d'événements temps réel |

### Agent Rust (`agent/`)
- `tokio` + `reqwest` + `sysinfo`. `config.rs` (TOML), `state.rs` (machine_id + token persistés),
  `collector.rs` (métriques système), `queue.rs` (file offline, écriture atomique),
  `transport.rs` (enroll / ingest avec retry exponentiel / heartbeat).
- Build multi-stage Docker (`rust` → `debian-slim`, ~110 Mo).

### Dashboard Next.js (`apps/web`)
- App Router, TypeScript, Tailwind (dark), TanStack Query, Recharts.
- `middleware.ts` — garde de route (cookie présent → accès, sinon redirection `/login`).
- `lib/` — `auth` (cookie token), `api` (fetch + 401 → logout), `ws` (ticket + WebSocket).
- Pages : `login`, `(dash)/dashboard` (parc), `(dash)/machines/[id]` (graphes temps réel),
  `(dash)/alerts` (table filtrable).

## Sécurité

- **Deux JWT** : `user` (lecture dashboard) et `agent` (ingestion) ; claim `type` vérifié à
  chaque requête → un token agent ne peut pas accéder aux endpoints user et inversement.
- **`jwt_secret`** validé au démarrage (refus des défauts connus, min 32 car.).
- **WebSocket** : auth par **ticket opaque à usage unique** (`GETDEL` Redis) — le JWT ne
  transite jamais dans une URL ni dans les access logs.
- Token d'enrôlement à usage unique, stocké hashé. Mots de passe argon2. CORS restreint à
  l'origine du dashboard. Secrets via variables d'environnement uniquement.
- TLS : assuré par reverse-proxy en production (hors périmètre MVP local).

## Décisions techniques
| Décision | Choix | Justification |
|----------|-------|---------------|
| Base séries temporelles | TimescaleDB | hypertables natives, compatible SQL Postgres |
| Temps réel | WebSocket + Redis pub/sub | bidirectionnel, découplé, extensible |
| Auth WS | ticket à usage unique | évite la fuite du JWT dans les URLs/logs |
| Driver DB | psycopg 3 (async) | maintenu, async natif |
| Idempotence ingestion | `ON CONFLICT DO NOTHING` | rejouer la file offline sans erreur |
| Ports | décalés (8800/3300/5433/6380) | éviter conflits avec autres projets locaux |
