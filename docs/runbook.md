# Runbook — GuardianOps AI (MVP)

Guide opérationnel : bootstrap, démo end-to-end, exploitation et dépannage.

---

## 1. Prérequis

- Docker + Docker Compose
- `python3` (pour générer le secret JWT) ; `curl` (pour le bootstrap API)

---

## 2. Bootstrap (première installation)

```bash
# 1. Configuration d'environnement
cp .env.example .env

# 2. Générer un secret JWT fort (OBLIGATOIRE — l'API refuse de démarrer sinon)
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
# → coller la valeur dans .env (remplacer JWT_SECRET=…)

# 3. Lancer l'infra + l'API + le dashboard
docker compose up --build -d db redis api web

# 4. Appliquer les migrations (crée users, machines, metrics [hypertable], alerts)
docker compose exec api alembic upgrade head

# 5. Créer le premier compte admin
docker compose exec api python -m app.cli create-admin admin@guardianops.ai 'MotDePasseFort!'
```

Vérifier :
- API liveness : <http://localhost:8800/health>
- API readiness (DB + Redis) : <http://localhost:8800/health/ready>
- OpenAPI : <http://localhost:8800/docs>
- Dashboard : <http://localhost:3300> → se connecter avec le compte admin

---

## 3. Démo end-to-end (agent → API → dashboard)

```bash
BASE=http://localhost:8800

# (a) S'authentifier
TOKEN=$(curl -s -X POST $BASE/auth/login \
  -d "username=admin@guardianops.ai&password=MotDePasseFort!" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# (b) Créer une machine → renvoie l'enroll_token UNE SEULE FOIS
curl -s -X POST $BASE/machines -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"demo-01"}'
#   → noter "enroll_token": "…"
```

Lancer l'agent (deux options) :

**Option A — via Docker Compose (profil `agent`)**
```bash
cp agent/data/agent.toml.example agent/data/agent.toml
# éditer agent/data/agent.toml : coller enroll_token ; api_url = http://api:8000
docker compose --profile agent up agent --build
```

**Option B — agent natif (binaire local)**
```bash
cd agent
cp agent.toml.example agent.toml   # api_url=http://localhost:8800 + enroll_token
cargo run --release                # ou: docker build + docker run -v $(pwd)/data:/agent
```

Après quelques secondes : la machine passe `online` sur le dashboard, les graphes
CPU/RAM/Disque se remplissent en temps réel, et toute alerte de seuil apparaît
instantanément (push WebSocket).

> L'agent persiste `agent_state.toml` (machine_id + token) après le 1er enrôlement.
> L'`enroll_token` n'est alors plus nécessaire et peut être retiré de la config.

---

## 4. Règles d'alerte (seuils, configurables via `.env`)

| Alerte       | Condition par défaut                      | Sévérité  | Variable                        |
|--------------|-------------------------------------------|-----------|---------------------------------|
| `cpu_high`   | CPU > 90 % sur 3 points consécutifs       | warning   | `ALERT_CPU_THRESHOLD` / `…_CONSECUTIVE_POINTS` |
| `mem_high`   | RAM > 90 % (1 point)                      | warning   | `ALERT_MEM_THRESHOLD`           |
| `disk_full`  | Disque > 90 % (1 point)                   | critical  | `ALERT_DISK_THRESHOLD`          |
| `offline`    | Pas de heartbeat depuis > 2 min           | critical  | `ALERT_OFFLINE_MINUTES`         |

Les alertes se résolvent automatiquement quand la condition disparaît (ou au retour
du heartbeat pour `offline`). Une tâche de fond vérifie les machines silencieuses
toutes les 30 s.

---

## 5. Exploitation

```bash
# Logs
docker compose logs -f api
docker compose logs -f web

# État des conteneurs
docker compose ps

# Accès SQL direct
docker compose exec db psql -U guardian -d guardianops

# Tests + lint backend (deps de test absentes de l'image runtime)
docker compose run --rm api sh -c "pip install -r requirements-dev.txt && pytest -q"
docker compose run --rm api ruff check .

# Arrêt (préserve les données) / purge complète
docker compose down
docker compose down -v        # ⚠ supprime le volume DB
```

---

## 6. Dépannage

| Symptôme | Cause probable | Résolution |
|----------|----------------|------------|
| L'API ne démarre pas, erreur `JWT_SECRET est trop faible` | `JWT_SECRET` absent / défaut / < 32 car. | Générer un secret fort (cf. §2) |
| `/health/ready` renvoie `database: error` | Migrations non appliquées ou DB non prête | `docker compose exec api alembic upgrade head` |
| Login → 401 | Compte admin non créé | `python -m app.cli create-admin …` |
| Agent : `Token d'enrôlement invalide ou déjà utilisé` | Token déjà consommé (usage unique) | Recréer une machine → nouveau token |
| Dashboard vide alors que l'agent tourne | `api_url` de l'agent incorrect | Compose : `http://api:8000` ; natif : `http://localhost:8800` |
| WS ne reçoit pas d'événements | Ticket expiré (TTL 30 s) | Le front régénère un ticket à chaque connexion ; vérifier l'auth |
| Modif de code Python non prise en compte | Cache bytecode du conteneur | `docker compose restart api` |

---

## 7. Notes de sécurité (déploiement)

- `JWT_SECRET` validé au démarrage (refus des valeurs faibles/par défaut, min 32 car.).
- WebSocket : authentification par **ticket à usage unique** (`POST /ws/ticket`, TTL 30 s)
  — le JWT ne transite jamais dans une URL (donc jamais dans les access logs).
- Tokens d'enrôlement stockés **hashés** (sha256), affichés en clair une seule fois.
- Mots de passe hashés **argon2**.
- En production : terminaison **TLS** via reverse-proxy, restreindre l'exposition réseau
  de PostgreSQL/Redis (ne pas publier 5433/6380 hors de l'hôte), changer les
  identifiants DB par défaut. → automatisé par la surcouche `docker-compose.prod.yml` (§8).

---

## 8. Déploiement production (durcissement)

La surcouche `docker-compose.prod.yml` applique le durcissement sans toucher au
workflow de dev :

| Aspect | Dev (`docker-compose.yml`) | Prod (`+ docker-compose.prod.yml`) |
|--------|----------------------------|------------------------------------|
| `/docs`, `/redoc`, `/openapi.json` | exposés | **désactivés** (`ENVIRONMENT=production`) |
| PostgreSQL / Redis | ports publiés sur l'hôte | **non exposés** (réseau interne) |
| Redis | sans mot de passe | **`--requirepass`** obligatoire |
| API | code monté + `--reload` | image immuable, sans reload |
| Dashboard | `next dev` | build **standalone** (`Dockerfile.prod`) |
| TLS / entrée | aucune | **Caddy** (HTTPS auto), seul service exposé (80/443) |
| Cookie token | `sameSite=lax` | `+ secure` (auto en HTTPS) |

### Prérequis `.env`
```dotenv
DOMAIN=mon-domaine.com                 # dashboard ; API sur api.mon-domaine.com
JWT_SECRET=<valeur forte ≥ 32 car.>    # python3 -c "import secrets; print(secrets.token_hex(32))"
POSTGRES_USER=…  POSTGRES_PASSWORD=<fort>  POSTGRES_DB=…
REDIS_PASSWORD=<fort>
```
Les DNS `mon-domaine.com` et `api.mon-domaine.com` doivent pointer vers l'hôte
(Caddy obtient alors les certificats Let's Encrypt automatiquement).

### Lancement
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# migrations + admin (le service api n'a pas de port publié → exec dans le conteneur)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api \
  python -m app.cli create-admin admin@mon-domaine.com '<motdepasse>'
```

> Nécessite Docker Compose ≥ 2.24 (tag de fusion `!override` pour retirer les ports).

### Mise à l'échelle horizontale de l'API

L'API est **sans état** : la détection périodique des machines offline tourne
dans un process séparé (`app/scheduler.py`, service `scheduler`). On peut donc
scaler l'API librement.

Deux dimensions de scaling, combinables :

**1. Workers uvicorn (un conteneur, N process)** — régler `API_WORKERS` dans
`.env` (défaut 2 ; repère : `(2 × cœurs) + 1`), puis :

```bash
echo "API_WORKERS=4" >> .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api
```

La commande prod de l'API devient `uvicorn … --workers 4`.

**2. Répliques derrière Caddy (N conteneurs load-balancés)** — surcouche
`docker-compose.scale.yml`. Caddy répartit la charge par résolution DNS
dynamique (`infra/caddy/Caddyfile`, bloc `dynamic a`, rafraîchi toutes les 5 s) :

```bash
echo "API_REPLICAS=3" >> .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               -f docker-compose.scale.yml up -d
```

Les deux sont sûrs uniquement parce que l'API est **sans état** : aucune tâche
de fond (cf. `scheduler`, instance unique), session via JWT, ticket WebSocket et
événements via **Redis partagé** (n'importe quelle réplique sert n'importe quelle
requête, y compris la consommation d'un ticket émis par une autre).

**Résilience** — Caddy détecte les répliques défaillantes par health-check
*passif* + ré-essai (`lb_try_duration`, `fail_duration` dans `infra/caddy/Caddyfile`) :
une réplique qui tombe est éjectée 10 s, et la requête en cours est rejouée sur
une réplique saine → **aucune erreur côté client**. (Les health-checks *actifs*
sont volontairement évités : ils se combinent mal aux upstreams dynamiques.)
Vérifié : arrêt d'une réplique sur 3 → 50 requêtes, 0 échec.

Garde-fous :
- **Ne pas répliquer le `scheduler`** (instance unique). Un doublon ne crée pas
  de doublon d'alerte — l'ouverture est idempotente via l'index unique partiel
  `uq_alerts_open_per_machine_type` — mais c'est du travail inutile.
- L'ouverture d'alerte par seuil (chemin d'ingestion, exécuté dans chaque worker)
  est protégée par ce même index : aucun doublon d'alerte ouverte possible.
