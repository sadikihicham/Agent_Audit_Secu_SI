# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**GuardianOps AI** (`Agent_Audit_Secu_SI`) — open-source platform for continuous IT-infrastructure auditing, real-time monitoring, AI analysis, failure prediction, and auto-remediation. The current target is an end-to-end MVP: **1 Rust agent → FastAPI API → 1 Next.js dashboard**, backed by PostgreSQL/TimescaleDB + Redis.

Project docs are in French. `PLAN.md` is the authoritative implementation roadmap (scope, data model, API contracts, phase breakdown); `docs/architecture.md` describes the component layout. **Status: Phase 0 (socle & infra) complete** — only the health-check skeleton exists; backend models/auth/ingestion, the Rust agent, and the dashboard UI are not yet built.

## Commands

Everything runs through Docker Compose (docker-first). Ports are deliberately offset to avoid clashing with other local projects.

```bash
cp .env.example .env          # required before first run
docker compose up --build     # starts db, redis, api (8800), web (3300)
```

Verify the stack:
- API liveness: http://localhost:8800/health
- API readiness (checks DB + Redis): http://localhost:8800/health/ready
- OpenAPI docs: http://localhost:8800/docs
- Dashboard: http://localhost:3300 (green badge = web→API chain OK)

Source is bind-mounted into the `api` and `web` containers, so both hot-reload (uvicorn `--reload`, `next dev`) — no rebuild needed for code changes.

**API (Python 3.12, run inside the `api` container or a local venv with `requirements.txt`):**
```bash
ruff check .                                  # lint (line-length 100, target py312)
pip install -r requirements-dev.txt           # test deps (pytest etc.) — NOT in runtime image
pytest                                        # tests (asyncio_mode=auto, testpaths=["tests"], pythonpath=["."])
pytest tests/test_x.py::test_name             # single test
alembic revision --autogenerate -m "msg"      # new migration (TimescaleDB hypertable steps are manual)
alembic upgrade head                          # apply migrations
python -m app.cli create-admin <email> <pw>   # seed an admin user
```

Run these inside the `api` container, e.g. `docker compose run --rm api <cmd>` (the runtime image lacks test deps; `pip install -r requirements-dev.txt` first when running pytest).

**Web (`apps/web`):**
```bash
npm run dev | build | start | lint            # lint = next lint
```

## Architecture

Monorepo: `apps/api` (FastAPI backend), `apps/web` (Next.js dashboard), and a future `agent/` (Rust collector, not yet present). The `apps/api` + `apps/web` split mirrors a sibling project (SGI) for consistency; the Rust agent lives at the repo root because it is not a web app.

**Data flow:** Rust agent posts metrics + heartbeat to the API (authenticated with an *agent* JWT); the Next.js dashboard reads via REST + WebSocket (authenticated with a *user* JWT). The API persists metrics as a TimescaleDB hypertable and uses Redis for pub/sub (real-time WS fan-out) and caching.

**API internals (`apps/api/app`):**
- `core/config.py` — all configuration via `pydantic-settings` from env vars; the `settings` singleton is imported everywhere. CORS origins are a comma-separated string exposed as `cors_origins_list`.
- `core/db.py` — **async** SQLAlchemy 2 engine (`psycopg` 3 driver), `SessionLocal` sessionmaker, the `Base` declarative class all ORM models must inherit, and the `get_session` FastAPI dependency.
- `core/redis.py` — shared async Redis client.
- `main.py` — app factory, CORS middleware, `lifespan` (disposes engine + Redis on shutdown), and the two `/health` endpoints.
- `alembic/env.py` — async migration runner; **new models must be imported here** (see the commented stub) so autogenerate detects their tables. Migration `sqlalchemy.url` is overridden from `settings.database_url`.

**Phase 1 backend is complete.** Implemented routers: `auth` (`/auth/login`, `/auth/me`), `machines` (`POST/GET /machines`, `GET /machines/{id}`, `GET /machines/{id}/metrics?range=1h|6h|24h|7d`), `agents` (`POST /agents/enroll`), `ingest` (`POST /ingest/metrics`, `POST /ingest/heartbeat`), `alerts` (`GET /alerts?status=`), `ws` (`WS /ws?token=`). Services: `ingestion` (bulk insert with ON CONFLICT DO NOTHING for offline-queue idempotency), `alerting` (threshold rules + offline background checker every 30 s + Redis pub/sub events on `guardianops:events`).

When adding backend features, follow the layout in `PLAN.md §2`: `models/` (SQLAlchemy), `schemas/` (Pydantic), `routers/`, `services/`.

**Web internals (`apps/web`):** Next.js 14 App Router, TypeScript, Tailwind CSS, dark mode by default. Dependencies: `@tanstack/react-query` v5 (data fetching + cache invalidation), `recharts` v2 (line charts), `js-cookie` (token storage).

- **Auth flow**: JWT stored in `guardian_token` cookie (set by `lib/auth.ts` via `js-cookie`). `middleware.ts` guards all routes server-side — unauthenticated → `/login`, already-authed on `/login` → `/dashboard`. `lib/api.ts` auto-adds `Authorization: Bearer` and clears the cookie + redirects on 401.
- **Routes**: `app/login/page.tsx`, `app/(dash)/layout.tsx` (sidebar + logout), `app/(dash)/dashboard/page.tsx` (fleet grid), `app/(dash)/machines/[id]/page.tsx` (3 line charts: CPU/RAM/Disk), `app/(dash)/alerts/page.tsx` (filterable table).
- **Real-time**: `lib/ws.ts` `useRealtimeEvents(cb)` opens `WS /ws?token=` once on mount; callback is a stable ref (avoids reconnects). On `alert.created`/`alert.resolved` events, the relevant pages invalidate their TanStack Query cache. The WS URL is derived from `NEXT_PUBLIC_API_URL` with `http` → `ws`.
- **Charts**: `app/(dash)/machines/[id]/page.tsx` uses `recharts` `LineChart` with `ResponsiveContainer`, domain `[0, 100]`, refetch every 15 s. Range selector (1h/6h/24h/7d) changes the `queryKey` so each range is cached independently.
- **`app/providers.tsx`** wraps children in `QueryClientProvider` (staleTime 15 s, retry 1). Imported in `app/layout.tsx`.

## Rust agent (`agent/`)

Built with `tokio`, `reqwest` 0.12, `sysinfo` 0.31, `serde`/`serde_json`, `anyhow`, `tracing`. Requires Rust ≥ 1.85 (edition 2024 deps).

**Files:** `src/config.rs` (TOML config), `src/state.rs` (persisted machine_id + agent_token), `src/collector.rs` (`Collector` struct, `system_info()` for hostname/OS), `src/queue.rs` (offline queue, atomic write via rename), `src/transport.rs` (enroll, send_metrics with 3-attempt exponential backoff, heartbeat).

**Running:**
```bash
cp agent.toml.example agent.toml   # fill in api_url + enroll_token
docker build -t guardianops-agent:dev .
docker run --rm -v $(pwd)/data:/agent guardianops-agent:dev
RUST_LOG=debug docker run ...      # verbose logging
```

**Enrollment flow:** on first run with `enroll_token` in `agent.toml`, calls `POST /agents/enroll` → saves `agent_state.toml` (machine_id + agent_token). On subsequent runs the state file is used directly; `enroll_token` is no longer needed.

**Offline queue (`queue.json`):** every tick, loads the queue file + adds the current sample, tries to send the whole batch. On success the file is deleted; on failure the batch (old + new) is written back. The API's `ON CONFLICT DO NOTHING` makes re-sending idempotent. Atomic writes via temp-file + rename prevent corruption.

**Docker:** binary at `/usr/local/bin/guardianops-agent`, working directory `/agent` — mount your config/state dir there. Build: `rust:latest` → `debian:bookworm-slim`, ~110 MB runtime image.

## Conventions & constraints

- **Two JWT types**: `user` (dashboard read scope) and `agent` (ingestion only); claims `sub`, `type`, `iat`, `exp`. Primitives live in `core/security.py`; the FastAPI dependencies `get_current_user` / `get_current_agent` (exposed as `CurrentUser` / `CurrentAgent` in `app/deps.py`) decode the token **and enforce the `type` claim** — a user token cannot access an agent endpoint and vice versa. Passwords hashed with argon2 (`passlib[argon2]`). JWT via `python-jose`. User login is `POST /auth/login` (OAuth2 password form: `username`=email).
- **JWT secret validation** (`core/config.py`): `@field_validator` on `jwt_secret` refuses known weak defaults and values shorter than 32 chars — the API won't start. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
- **WebSocket ticket flow** (`routers/ws.py`): `WS /ws` accepts `?ticket=<opaque>` only — never a JWT in the URL (avoids leaking the bearer token into uvicorn/nginx access logs). Obtain a ticket via `POST /ws/ticket` (bearer auth) → 30 s TTL, stored in Redis, consumed atomically with `GETDEL` (single-use). Frontend `lib/ws.ts` calls `fetchWsTicket()` before opening the socket.
- **OpenAPI docs gating** (`main.py`): `should_expose_docs(environment)` disables `/docs`, `/redoc`, `/openapi.json` unless `ENVIRONMENT == "development"`. The prod overlay sets `ENVIRONMENT=production`.
- **Production overlay**: `docker-compose.prod.yml` (apply with `-f docker-compose.yml -f docker-compose.prod.yml`) hardens the dev stack without changing it — db/redis not published, Redis `--requirepass`, API on the built image (no source mount, no `--reload`), web via `apps/web/Dockerfile.prod` (Next standalone), and Caddy (`infra/caddy/Caddyfile`) terminating TLS as the only exposed service (`DOMAIN` + `api.DOMAIN`). Uses Compose `!override` (needs Compose ≥ 2.24). See `docs/runbook.md §8`.
- **Enrollment flow**: an admin creates a machine via `POST /machines` (user auth) → the response returns a high-entropy `enroll_token` **once** (only its sha256 hash is stored, in `machines.enroll_token_hash`). The agent then calls `POST /agents/enroll` with `{enroll_token, hostname, os}` (no JWT — the enroll token *is* the auth) → receives `{machine_id, agent_token}`. Enrollment **consumes** the token (sets `enroll_token_hash = NULL`), so it is strictly single-use. `machines.hostname` is nullable because it's unknown until the agent enrolls.
- All DB access is **async** — use `get_session` / `AsyncSession`, never sync SQLAlchemy.
- Inside Docker the DB/Redis hosts are `db`/`redis` on their internal ports (5432/6379); `docker-compose.yml` overrides `DATABASE_URL`/`REDIS_URL` accordingly, while host-facing ports come from `.env` (`API_PORT`, `WEB_PORT`, `DB_PORT`, `REDIS_PORT`).
- Threshold-based alert rules (CPU/mem/disk > 90%, no heartbeat > 2 min) are defined in `PLAN.md §3`; keep them env-configurable.
- UI text is French and should stay isolated for future i18n (FR/EN/AR), which is deferred post-MVP.
