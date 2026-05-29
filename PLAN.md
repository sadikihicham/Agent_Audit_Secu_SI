# GuardianOps AI — Plan d'implémentation MVP

> **Statut** : Plan détaillé (aucun code écrit pour l'instant)
> **Cible de cette itération** : MVP fonctionnel end-to-end → **1 Agent Rust → API FastAPI → 1 Dashboard Next.js**
> **Emplacement** : `/Users/sadiki/Desktop/Agent_Audit_Secu_SI`
> **Date** : 2026-05-29

---

## 1. Objectif du MVP

Prouver la chaîne complète de valeur sur un périmètre minimal mais réel :

```
┌──────────────┐   metrics/heartbeat   ┌──────────────┐   REST + WS   ┌──────────────┐
│  Agent Rust  │ ────────────────────► │ API FastAPI  │ ◄───────────► │  Next.js UI  │
│ (1 machine)  │   POST /ingest (JWT)  │ + PostgreSQL │   dashboard   │  (dark mode) │
└──────────────┘                       │ + TimescaleDB│               └──────────────┘
                                        │ + Redis      │
                                        └──────────────┘
```

**Ce qui est DANS le MVP :**
- Agent Rust collectant CPU / RAM / Disque / uptime + heartbeat, avec offline queue basique.
- API FastAPI : enrôlement agent, auth (JWT machine + JWT user), ingestion métriques, liste machines, alertes simples par seuil, WebSocket temps réel.
- Dashboard Next.js : login, vue globale (santé du parc), détail machine (graphes temps réel), liste d'alertes.
- PostgreSQL + TimescaleDB (hypertable métriques) + Redis (pub/sub WS + cache).
- Docker Compose pour tout lancer.

**Ce qui est HORS MVP (itérations suivantes) :** Mobile RN, moteur IA (anomaly/RCA), SIEM, audit ISO/CIS/NIST automatisé, auto-remediation, notifications WhatsApp/Telegram, RBAC fin, MFA, OpenSearch, NATS, multi-langue complet.

---

## 2. Structure du monorepo (cible)

```
Agent_Audit_Secu_SI/
├── PLAN.md
├── README.md
├── docker-compose.yml
├── .env.example
├── agent/                      # Agent Rust
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs
│       ├── config.rs           # lecture config (toml + env)
│       ├── collector/          # CPU, RAM, disk, uptime
│       ├── transport/          # client HTTP + retry + offline queue
│       └── enroll.rs           # enrôlement + stockage token
├── apps/
│   └── api/                    # Backend FastAPI
│       ├── pyproject.toml
│       ├── alembic/            # migrations
│       └── app/
│           ├── main.py
│           ├── core/           # config, security (JWT), db session
│           ├── models/         # SQLAlchemy: Machine, Metric, Alert, User
│           ├── schemas/        # Pydantic
│           ├── routers/        # auth, agents, machines, metrics, alerts, ws
│           └── services/       # ingestion, alerting (seuils)
│   └── web/                    # Dashboard Next.js (App Router)
│       ├── package.json
│       ├── app/
│       │   ├── login/
│       │   ├── (dash)/dashboard/
│       │   ├── (dash)/machines/[id]/
│       │   └── (dash)/alerts/
│       ├── components/
│       └── lib/                # api client, ws hook, auth
└── docs/
    └── architecture.md
```

> Choix : on réutilise la convention `apps/api` + `apps/web` déjà présente dans ton autre projet (SGI) pour cohérence d'habitudes. L'agent Rust reste à la racine sous `agent/` car ce n'est pas un "app" web.

---

## 3. Data model (MVP)

| Table | Colonnes clés | Notes |
|-------|---------------|-------|
| `users` | id, email, hashed_password, role, created_at | role = `admin` (un seul rôle au MVP) |
| `machines` | id, name, hostname, os, enroll_token_hash, agent_version, last_seen_at, status | status dérivé du heartbeat |
| `metrics` | time, machine_id, cpu_pct, mem_pct, disk_pct, uptime_s | **hypertable Timescale** (clé temporelle) |
| `alerts` | id, machine_id, type, severity, message, value, threshold, status, created_at, resolved_at | type ex: `cpu_high`, `offline` |

**Règles d'alerte MVP (par seuil, en dur configurable via env) :**
- `cpu_pct > 90%` pendant 3 points consécutifs → alerte `cpu_high` (warning).
- `mem_pct > 90%` → `mem_high`.
- `disk_pct > 90%` → `disk_full` (critical).
- Pas de heartbeat depuis > 2 min → `offline` (critical), auto-résolue au retour.

---

## 4. Contrats d'API (MVP)

**Auth**
- `POST /auth/login` → `{access_token}` (user, JWT court).
- `POST /agents/enroll` → body `{enroll_token, hostname, os}` → `{machine_id, agent_token}` (JWT machine longue durée).

**Ingestion (auth = agent_token)**
- `POST /ingest/metrics` → body `{machine_id, samples:[{ts, cpu, mem, disk, uptime}]}` → `202`. Supporte le batch (vidange offline queue).
- `POST /ingest/heartbeat` → met à jour `last_seen_at`.

**Lecture (auth = user)**
- `GET /machines` → liste + statut + dernières métriques.
- `GET /machines/{id}/metrics?range=1h` → série temporelle (depuis Timescale).
- `GET /alerts?status=open` → liste alertes.
- `WS /ws` → push temps réel (nouvelle métrique, nouvelle alerte) via Redis pub/sub.

---

## 5. Sécurité (secure-by-design dès le MVP)

- **Deux types de JWT** : `user` (scope lecture dashboard) et `agent` (scope ingestion seulement). Claims `sub`, `type`, `exp`.
- Enrôlement : token d'enrôlement à usage unique, stocké **hashé** (jamais en clair en base).
- Mots de passe : `argon2` (ou bcrypt).
- Secrets via variables d'environnement (`.env`, jamais commit) ; `.env.example` fourni.
- CORS restreint à l'origine du dashboard.
- TLS : assumé via reverse-proxy en prod (hors MVP local, documenté).
- Validation stricte des entrées (Pydantic) ; payload d'ingestion borné (taille batch max).
- L'agent vérifie le certificat serveur et signe/chiffre sa file offline localement (itération : signature payload).

---

## 6. Découpage en phases (ordre d'exécution recommandé)

### Phase 0 — Socle & infra (fondation)
- [ ] `docker-compose.yml` : postgres+timescale, redis, api, web.
- [ ] `.env.example`, `README.md` (commandes de lancement).
- [ ] Squelette `apps/api` (FastAPI + SQLAlchemy + Alembic) et `apps/web` (Next.js App Router + Tailwind).
- **Livrable** : `docker compose up` démarre tous les services (API `/health` répond, page web blanche).

### Phase 1 — Backend cœur
- [ ] Modèles + migrations (users, machines, metrics hypertable, alerts).
- [ ] Auth user (`/auth/login`) + auth agent (JWT) + dépendances de sécurité.
- [ ] Enrôlement agent (`/agents/enroll`).
- [ ] Ingestion métriques + heartbeat (batch).
- [ ] Service d'alerting par seuils.
- [ ] Endpoints lecture (`/machines`, `/metrics`, `/alerts`).
- [ ] WebSocket `/ws` + Redis pub/sub.
- [ ] Tests : pytest (auth, ingestion, alerting).
- **Livrable** : API testable via `curl`/OpenAPI, alertes générées sur données simulées.

### Phase 2 — Agent Rust
- [ ] Collecteurs CPU/RAM/disque/uptime (crate `sysinfo`).
- [ ] Enrôlement + stockage local du token.
- [ ] Envoi périodique (intervalle configurable) + heartbeat.
- [ ] Offline queue (fichier local) + retry/backoff.
- [ ] Build release léger (`--release`, strip).
- **Livrable** : binaire qui s'enrôle et alimente l'API en continu.

### Phase 3 — Dashboard Next.js
- [ ] Login + stockage token + garde de route.
- [ ] Vue globale : cartes machines + statut santé.
- [ ] Détail machine : graphes CPU/RAM/disque (temps réel via WS).
- [ ] Page alertes.
- [ ] Dark mode.
- **Livrable** : UI affichant en direct les données de l'agent réel.

### Phase 4 — Intégration & durcissement
- [ ] Test end-to-end : agent → API → dashboard sur 1 machine réelle.
- [ ] Revue sécurité légère (`/security-review`).
- [ ] Docs : `docs/architecture.md`, schéma, runbook.
- **Livrable** : MVP démontrable + documentation.

---

## 7. Stack & versions retenues (MVP)

| Composant | Choix | Raison |
|-----------|-------|--------|
| Agent | Rust + `tokio`, `reqwest`, `sysinfo`, `serde` | léger, async, multi-OS |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, `python-jose`, `passlib[argon2]` | productivité + écosystème |
| DB | PostgreSQL 16 + extension TimescaleDB | séries temporelles natives |
| Cache/bus | Redis 7 | pub/sub WS + cache simple |
| Web | Next.js 14 (App Router), TypeScript, Tailwind, Recharts, TanStack Query | moderne, realtime-friendly |
| Conteneurs | Docker + Docker Compose | docker-first |

---

## 8. Risques & décisions ouvertes

- **TimescaleDB** ajoute une dépendance image ; alternative repli = Postgres simple + index temporel si souci. → *à valider.*
- **WebSocket vs SSE** : WS choisi pour bidirectionnel futur ; SSE suffirait au MVP. → *à valider.*
- **Multi-langue (FR/EN/AR)** : reporté post-MVP, mais textes UI isolés dès le départ pour faciliter l'i18n.
- **Ports** : à définir (proposition : API `8000`, web `3000`, postgres `5432`, redis `6379`).

---

## 9. Prochaine étape

Une fois ce plan validé, on attaque la **Phase 0 (socle & infra)**. Dis-moi si tu veux ajuster le périmètre, la stack ou l'ordre des phases avant de générer le code.
