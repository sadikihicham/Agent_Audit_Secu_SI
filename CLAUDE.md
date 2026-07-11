# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**GuardianOps AI** (`Agent_Audit_Secu_SI`) — open-source platform for continuous IT-infrastructure auditing, real-time monitoring, AI analysis, failure prediction, and auto-remediation. The current target is an end-to-end MVP: **1 Rust agent → FastAPI API → 1 Next.js dashboard**, backed by PostgreSQL/TimescaleDB + Redis.

Project docs are in French. `PLAN.md` is the authoritative implementation roadmap (scope, data model, API contracts, phase breakdown); `docs/architecture.md` describes the component layout; `docs/runbook.md` covers operations/production. **Status: MVP complete** — the full end-to-end chain (Rust agent → FastAPI API → Next.js dashboard) is built and working through Phase 4: core backend (models/auth/ingestion/alerting/anomaly/WebSocket), the Rust collector agent, the dashboard UI, and a hardened production overlay all exist. See the per-area sections below for what's implemented.

## Commands

Everything runs through Docker Compose (docker-first). Ports are deliberately offset to avoid clashing with other local projects.

```bash
cp .env.example .env          # required before first run
docker compose up --build     # starts db, redis, go-api (8800), go-web (3300)
```

Verify the stack:
- API liveness: http://localhost:8800/health
- API readiness (checks DB + Redis): http://localhost:8800/health/ready
- OpenAPI docs: http://localhost:8800/docs
- Dashboard: http://localhost:3300 (green badge = web→API chain OK)

Source is bind-mounted into the `go-api` and `go-web` containers, so both hot-reload (uvicorn `--reload`, `next dev`) — no rebuild needed for code changes.

**API (Python 3.12, run inside the `go-api` container or a local venv with `requirements.txt`). All commands below run from `apps/api/` — that's where `pyproject.toml` lives and where the test suite (`apps/api/tests/`) is collected; `testpaths`/`pythonpath` are relative to it, so `pytest` from the repo root finds nothing:**
```bash
ruff check .                                  # lint (line-length 100, target py312)
pip install -r requirements-dev.txt           # test deps (pytest etc.) — NOT in runtime image
pytest                                        # tests (asyncio_mode=auto, testpaths=["tests"], pythonpath=["."])
pytest tests/test_x.py::test_name             # single test
alembic revision --autogenerate -m "msg"      # new migration (TimescaleDB hypertable steps are manual)
alembic upgrade head                          # apply migrations
python -m app.cli create-admin <email> <pw>   # seed an admin user
```

Run these inside the `go-api` container, e.g. `docker compose run --rm go-api <cmd>` (the runtime image lacks test deps; `pip install -r requirements-dev.txt` first when running pytest). Service keys are `go-api`/`go-web` (not `api`/`web`) — Compose always registers a service's plain key as a DNS alias on every network it joins, and generic names would collide with a co-hosted project's own `api`/`web` services on a shared external network (incident 2026-07-11).

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

**Phase 1 backend is complete.** Implemented routers: `auth` (`/auth/login`, `/auth/me`), `machines` (`POST/GET /machines`, `GET /machines/{id}`, `GET /machines/{id}/metrics?range=1h|6h|24h|7d`), `agents` (`POST /agents/enroll`), `ingest` (`POST /ingest/metrics`, `POST /ingest/heartbeat`, plus the network ingest endpoints below), `alerts` (`GET /alerts?status=`), `network` (see below), `ws` (`WS /ws?token=`). Services: `ingestion` (bulk insert with ON CONFLICT DO NOTHING for offline-queue idempotency), `alerting` (threshold rules + Redis pub/sub events on `guardianops:events`), `anomaly` (per-machine statistical anomaly detection). The alert open/resolve primitives are public in `alerting` (`open_alert` / `resolve_alert`) and shared by both `alerting` and `anomaly`.

**Anomaly detection** (`services/anomaly.py`): catches values abnormal *for a given machine* that the static thresholds miss (e.g. CPU 60% on a box that idles at 10%). Pure `evaluate(values_desc)` computes a robust z-score (median + MAD, scaled ×0.6745) over the machine's own trailing baseline (`ANOMALY_WINDOW`, excluding the most recent `ANOMALY_CONSECUTIVE_POINTS`); flags when the last K points all exceed `ANOMALY_Z_THRESHOLD` in the same direction. Falls back to an absolute floor (`ANOMALY_ABS_FLOOR`) when the baseline is ~constant (MAD≈0). Opens `cpu_anomaly` / `mem_anomaly` / `disk_anomaly` alerts (warning) with explainable messages, auto-resolving on return to normal. Called from the ingest router after threshold checks; needs `ANOMALY_MIN_SAMPLES` history before it activates. Alert opening is **idempotent under concurrency**: `_open_alert` uses `INSERT … ON CONFLICT DO NOTHING RETURNING` against the partial unique index `uq_alerts_open_per_machine_type` (migration `0003`, `alerts(machine_id, type) WHERE status='open'`) — so multiple API workers can't create duplicate open alerts. The partial index is created in the migration and ignored by alembic autogenerate (`env.py` `_MANUALLY_MANAGED_INDEXES`).

**Scheduler is a separate process** (`app/scheduler.py`, run via `python -m app.scheduler` / the `scheduler` compose service). It runs the periodic offline-machine check every 30 s **and** refreshes the network threat-intel blocklist every `NETWORK_FEED_REFRESH_MINUTES` (`feeds.refresh_blocklist`, best-effort). The API (`main.py`) no longer runs any background loop, so it is **stateless and horizontally scalable**. The scheduler must stay **single-instance** (don't replicate it); duplicate runs are harmless thanks to the idempotent alert index but wasteful.

**Network monitoring (Rubrique Réseau)** — surveillance of devices *around* the agent's host (in/out), separate from the host metrics pipeline. Three ingest phases, all agent-authed and 202-accepted: `POST /ingest/scan` (device discovery snapshot — devices + open ports), `POST /ingest/flows` (outbound TCP connections), `POST /ingest/ids` (Suricata alerts). User-facing read API under `routers/network.py` (all `CurrentUser`): `GET /network/summary` (computed state `sain|surveille|alarme|sature|critique|indisponible` + KPI counts + recent events), `GET /network/devices[?type=&status=]`, `GET /network/devices/{id}` + `/ports` + `/vulns`, `GET /network/events[?kind=&severity=&status=&device_id=&limit=]`, `POST /network/events/{id}/ack`, `GET /network/vulns[?severity=]`.
- **Models/tables** (migrations `0004`–`0007`, under `apps/api/alembic/versions/`): `devices` (discovered hosts, FK→machines, unique `(discovered_by_machine_id, mac)`; SNMP cols `snmp_reachable/sys_descr/sys_uptime_secs/sys_location/sys_contact` added in `0007`), `device_ports` (unique `(device_id, port, protocol)`), `device_vulns` (severity `info|low|medium|high|critical`, FK→devices/device_ports), `network_events` (kinds `new_device|new_open_port|port_scan|arp_spoof|outbound_suspicious|ids_alert`, JSONB `details`, status `open|acknowledged`), `device_interfaces` (SNMP ifTable: `if_index/name/mac/admin_up/oper_up/speed_bps/mtu/in_octets/out_octets`, unique `(device_id, if_index)`, migration `0007`). Schemas in `schemas/network.py`.
- **SNMP enrichment** (agent `src/snmp.rs`, opt-in `[snmp]`): after the TCP scan, the agent queries discovered devices over UDP 161 (read-only, async `snmp2` crate) for the MIB-II system group (sysDescr/sysName/sysUpTime/sysLocation/sysContact) and, optionally, the interface table (ifTable, walked via getbulk). Supports **both v2c** (community) **and v3/USM** (`version="v2c"|"v3"`): v3 does auth (MD5/SHA family) + privacy (DES/AES128), level derived from which passwords are set (none→noAuthNoPriv, auth only→authNoPriv, both→authPriv), with automatic engine-ID discovery (`init`) and `Error::AuthUpdated` retry. Sent on the same `POST /ingest/scan` payload (`ScanDevice.snmp_reachable` + `interfaces`); `services/network.py` sets the device SNMP columns (only when `snmp_reachable`, so a non-SNMP scan never clobbers prior values) and recomputes `device_interfaces` (delete+insert). Read via `GET /network/devices/{id}/interfaces`; the device detail page shows uptime/location/contact + an interfaces table.
- **Services**: `network.py` (orchestration: upsert scan, mark-down absent devices, sync ports/vulns, emit events, compute summary state, enrich devices with `risk`/port/vuln counts), `vuln.py` (**offline** engine: port-exposure rules + embedded CVE signatures from `app/data/cve_signatures.json`), `threatintel.py` (`evaluate_flow` against embedded + Redis blocklist `guardianops:blocklist:ips` and suspicious-port list), `feeds.py` (refresh blocklist from `NETWORK_BLOCKLIST_FEED_URL`, abuse.ch Feodo by default), `events.py` (`record_event` with dedup window + Redis pub/sub), `notify.py` (best-effort webhook, slack/discord/generic, gated by `NOTIFY_MIN_SEVERITY`). All detection is offline/self-contained — no paid threat APIs required.
- **Config** (`core/config.py`): `NETWORK_*` knobs (scan-stale window, new-device/event/dedup/saturation windows, port-scan fan-out threshold), `NETWORK_FEEDS_ENABLED`/`NETWORK_BLOCKLIST_FEED_URL`/`NETWORK_FEED_REFRESH_MINUTES`/`NETWORK_FEED_TTL_HOURS`, and `NOTIFY_*` (disabled by default).
- **Agent** (`agent/src/netscan.rs`, `flows.rs`): TCP-connect sweep + ARP/`/proc/net/arp` MAC discovery + OUI vendor + device-type heuristic; outbound flows from `/proc/net/tcp{,6}`. **Opt-in and default-deny**: `[scan]` section in `agent.toml` (`enabled=false` by default, `allowlist` CIDRs intersected with local subnets so it never scans outside the LAN).
- **Suricata IDS sidecar (optional, deferred default)**: `docker-compose.suricata.yml` runs `suricata` (host network) + an `ids-forwarder` (`infra/suricata/forwarder.py`) that tails `eve.json`, enrolls as an agent, and POSTs alerts to `/ingest/ids`. See `infra/suricata/README.md`.
- **Web routes**: `app/(dash)/network/page.tsx` (KPIs + device table + state badge), `network/[id]` (device detail), `network/events` (intrusions, ack), `network/vulns` (fleet vulns). UI badges/labels in `components/network-state.tsx`. Real-time via the same `useRealtimeEvents` WS.

**Scaling the API** — two combinable dimensions, both safe because the API is stateless (JWT sessions, WS tickets + events via shared Redis): (1) uvicorn workers via `API_WORKERS` in the prod overlay; (2) **replicas** via `docker-compose.scale.yml` (`API_REPLICAS`, drops the go-api `container_name` with `!reset`), load-balanced by Caddy's `dynamic a` DNS upstreams (`infra/caddy/Caddyfile`) which re-resolves the `go-api` service name against Docker DNS (`127.0.0.11`) every 5 s. Apply with `-f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.scale.yml`.

When adding backend features, follow the layout in `PLAN.md §2`: `models/` (SQLAlchemy), `schemas/` (Pydantic), `routers/`, `services/`.

**Web internals (`apps/web`):** Next.js 14 App Router, TypeScript, Tailwind CSS. Dependencies: `@tanstack/react-query` v5 (data fetching + cache invalidation), `recharts` v2 (line charts), `js-cookie` (token storage). Shared UI lives in `components/` (`logo.tsx`, `health-badge.tsx`, `theme.tsx`, `theme-toggle.tsx`).

- **Theming**: light/dark toggle (not dark-only). `components/theme.tsx` `ThemeProvider`/`useTheme` resolve the theme from `localStorage` key `guardian_theme`, falling back to the OS `prefers-color-scheme` (default dark), and apply it by toggling the `dark` class + `color-scheme` on `<html>`. An inline anti-FOUC script in `app/layout.tsx` applies the same logic before first paint (`suppressHydrationWarning`). Tailwind dark styles use the `dark:` variant; light is the base.
- **Auth flow**: JWT stored in `guardian_token` cookie (set by `lib/auth.ts` via `js-cookie`). `middleware.ts` guards all routes server-side — unauthenticated → `/login`, already-authed on `/login` → `/dashboard`. `lib/api.ts` auto-adds `Authorization: Bearer` and clears the cookie + redirects on 401.
- **Routes**: `app/login/page.tsx` (with footer + demo-account hint), `app/(dash)/layout.tsx` (sidebar + logout), `app/(dash)/dashboard/page.tsx` (fleet grid), `app/(dash)/machines/[id]/page.tsx` (3 line charts: CPU/RAM/Disk), `app/(dash)/alerts/page.tsx` (filterable table).
- **Real-time**: `lib/ws.ts` `useRealtimeEvents(cb)` first fetches a single-use ticket via `POST /ws/ticket`, then opens `WS /ws?ticket=<opaque>` once on mount (the JWT never transits in the URL); callback is a stable ref (avoids reconnects). On `alert.created`/`alert.resolved` events, the relevant pages invalidate their TanStack Query cache. The WS URL is derived from `NEXT_PUBLIC_API_URL` with `http` → `ws`.
- **Charts**: `app/(dash)/machines/[id]/page.tsx` uses `recharts` `LineChart` with `ResponsiveContainer`, domain `[0, 100]`, refetch every 15 s. Range selector (1h/6h/24h/7d) changes the `queryKey` so each range is cached independently.
- **`app/providers.tsx`** wraps children in `QueryClientProvider` (staleTime 15 s, retry 1). Imported in `app/layout.tsx`.

## Rust agent (`agent/`)

Built with `tokio`, `reqwest` 0.12, `sysinfo` 0.31, `serde`/`serde_json`, `anyhow`, `tracing`. Requires Rust ≥ 1.85 (edition 2024 deps).

**Files:** `src/config.rs` (TOML config), `src/state.rs` (persisted machine_id + agent_token), `src/collector.rs` (`Collector` struct, `system_info()` for hostname/OS), `src/queue.rs` (offline queue, atomic write via rename), `src/transport.rs` (enroll, send_metrics with 3-attempt exponential backoff, heartbeat, plus scan/flows upload), `src/netscan.rs` + `src/flows.rs` (network monitoring — see the Network monitoring section above; opt-in via `[scan]`), `src/snmp.rs` (SNMP v2c **and v3/USM** enrichment via the async `snmp2` crate; opt-in via `[snmp]`, runs after `run_scan` to fill `ScanDevice` SNMP fields + interfaces).

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
- **Production overlay**: `docker-compose.prod.yml` (apply with `-f docker-compose.yml -f docker-compose.prod.yml`) hardens the dev stack without changing it — db/redis not published, Redis `--requirepass`, API on the built image (no source mount, no `--reload`, `--workers ${API_WORKERS:-2}`), web via `apps/web/Dockerfile.prod` (Next standalone), and Caddy (`infra/caddy/Caddyfile`) terminating TLS as the only exposed service (`DOMAIN` + `api.DOMAIN`). Uses Compose `!override` (needs Compose ≥ 2.24). See `docs/runbook.md §8`.
- **Enrollment flow**: an admin creates a machine via `POST /machines` (user auth) → the response returns a high-entropy `enroll_token` **once** (only its sha256 hash is stored, in `machines.enroll_token_hash`). The agent then calls `POST /agents/enroll` with `{enroll_token, hostname, os}` (no JWT — the enroll token *is* the auth) → receives `{machine_id, agent_token}`. Enrollment **consumes** the token (sets `enroll_token_hash = NULL`), so it is strictly single-use. `machines.hostname` is nullable because it's unknown until the agent enrolls.
- All DB access is **async** — use `get_session` / `AsyncSession`, never sync SQLAlchemy.
- Inside Docker the DB/Redis hosts are `db`/`redis` on their internal ports (5432/6379); `docker-compose.yml` overrides `DATABASE_URL`/`REDIS_URL` accordingly, while host-facing ports come from `.env` (`API_PORT`, `WEB_PORT`, `DB_PORT`, `REDIS_PORT`).
- Threshold-based alert rules (CPU/mem/disk > 90%, no heartbeat > 2 min) are defined in `PLAN.md §3`; keep them env-configurable.
- UI text is French and should stay isolated for future i18n (FR/EN/AR), which is deferred post-MVP.
