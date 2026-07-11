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
docker compose up --build -d db redis go-api go-web

# 4. Appliquer les migrations (crée users, machines, metrics [hypertable], alerts)
docker compose exec go-api alembic upgrade head

# 5. Créer le premier compte admin
docker compose exec go-api python -m app.cli create-admin admin@guardianops.ai 'MotDePasseFort!'
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
# éditer agent/data/agent.toml : coller enroll_token ; api_url = http://go-api:8000
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

## 4. Règles d'alerte (configurables via `.env`)

**Seuils absolus** (cf. PLAN.md §3) :

| Alerte       | Condition par défaut                      | Sévérité  | Variable                        |
|--------------|-------------------------------------------|-----------|---------------------------------|
| `cpu_high`   | CPU > 90 % sur 3 points consécutifs       | warning   | `ALERT_CPU_THRESHOLD` / `…_CONSECUTIVE_POINTS` |
| `mem_high`   | RAM > 90 % (1 point)                      | warning   | `ALERT_MEM_THRESHOLD`           |
| `disk_full`  | Disque > 90 % (1 point)                   | critical  | `ALERT_DISK_THRESHOLD`          |
| `offline`    | Pas de heartbeat depuis > 2 min           | critical  | `ALERT_OFFLINE_MINUTES`         |

**Anomalies statistiques** (z-score robuste médiane/MAD, *par machine*) — détectent
un écart au comportement habituel de la machine, même sous les seuils absolus
(ex. CPU à 60 % sur une machine qui tourne d'habitude à 10 %) :

| Alerte         | Condition                                              | Sévérité | Variables |
|----------------|--------------------------------------------------------|----------|-----------|
| `cpu_anomaly`  | z-score robuste du CPU ≥ seuil sur N points consécutifs | warning  | `ANOMALY_Z_THRESHOLD`, `ANOMALY_WINDOW`, `ANOMALY_CONSECUTIVE_POINTS` |
| `mem_anomaly`  | idem pour la RAM                                       | warning  | idem |
| `disk_anomaly` | idem pour le disque                                   | warning  | idem |

Message explicable, ex. : `CPU 85.0% anormal (z=+9.1, au-dessus de la base 10.0%±0.5)`.
Activable/désactivable via `ANOMALY_ENABLED`. Nécessite `ANOMALY_MIN_SAMPLES`
d'historique avant de s'activer (démarrage à froid).

Toutes les alertes se résolvent automatiquement quand la condition disparaît (ou au
retour du heartbeat pour `offline`). Une tâche de fond vérifie les machines
silencieuses toutes les 30 s (cf. `scheduler`).

---

## 5. Exploitation

```bash
# Logs
docker compose logs -f go-api
docker compose logs -f go-web

# État des conteneurs
docker compose ps

# Accès SQL direct
docker compose exec db psql -U guardian -d guardianops

# Tests + lint backend (deps de test absentes de l'image runtime)
docker compose run --rm go-api sh -c "pip install -r requirements-dev.txt && pytest -q"
docker compose run --rm go-api ruff check .

# Arrêt (préserve les données) / purge complète
docker compose down
docker compose down -v        # ⚠ supprime le volume DB
```

---

## 6. Dépannage

| Symptôme | Cause probable | Résolution |
|----------|----------------|------------|
| L'API ne démarre pas, erreur `JWT_SECRET est trop faible` | `JWT_SECRET` absent / défaut / < 32 car. | Générer un secret fort (cf. §2) |
| `/health/ready` renvoie `database: error` | Migrations non appliquées ou DB non prête | `docker compose exec go-api alembic upgrade head` |
| Login → 401 | Compte admin non créé | `python -m app.cli create-admin …` |
| Agent : `Token d'enrôlement invalide ou déjà utilisé` | Token déjà consommé (usage unique) | Recréer une machine → nouveau token |
| Dashboard vide alors que l'agent tourne | `api_url` de l'agent incorrect | Compose : `http://go-api:8000` ; natif : `http://localhost:8800` |
| WS ne reçoit pas d'événements | Ticket expiré (TTL 30 s) | Le front régénère un ticket à chaque connexion ; vérifier l'auth |
| Modif de code Python non prise en compte | Cache bytecode du conteneur | `docker compose restart go-api` |

---

## 7. Notes de sécurité (déploiement)

- `JWT_SECRET` validé au démarrage (refus des valeurs faibles/par défaut, min 32 car.).
- **Anti brute-force sur `/auth/login`** (`app/core/ratelimit.py`) : 5 échecs / 5 min par IP
  (fenêtre glissante, sorted set Redis) → `429` + `Retry-After`, **avant** toute vérification
  d'identifiants. Un succès réinitialise le compteur. **Fail-open** sur panne Redis (une panne
  d'infra ne verrouille jamais la seule voie d'accès admin). Devient un prérequis dès que l'API
  est exposée publiquement (cf. §8) — un seul compte admin, sans MFA à ce jour.
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
# migrations + admin (le service go-api n'a pas de port publié → exec dans le conteneur)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec go-api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec go-api \
  python -m app.cli create-admin admin@mon-domaine.com '<motdepasse>'
```

> Nécessite Docker Compose ≥ 2.24 (tag de fusion `!override` pour retirer les ports).

### Variante : déployer via l'IP du serveur, avant que le DNS soit posé

Le lancement ci-dessus **exige** un DNS déjà pointé (Let's Encrypt ne délivre pas de certificat
pour une IP nue). Pour ne pas bloquer le déploiement en attendant la propagation DNS, surcouche
temporaire `docker-compose.prod-ip.yml` : TLS **auto-signé** (`tls internal`), pas de sous-domaine
(impossible sur une IP nue) → dashboard et API distingués **par port** au lieu du nom d'hôte.

```dotenv
DOMAIN=203.0.113.10                    # l'IP du serveur, réutilise la même variable
JWT_SECRET=<valeur forte ≥ 32 car.>
POSTGRES_USER=…  POSTGRES_PASSWORD=<fort>  POSTGRES_DB=…
REDIS_PASSWORD=<fort>
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               -f docker-compose.prod-ip.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.prod-ip.yml \
  exec go-api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.prod-ip.yml \
  exec go-api python -m app.cli create-admin admin@example.com '<motdepasse>'
```

- Dashboard : `https://<IP>:${DASHBOARD_PORT:-443}/` · API : `https://<IP>:${API_PORT:-8443}/` —
  **avertissement navigateur attendu** (certificat auto-signé, normal en attendant le DNS).
- Le rate-limiter de login (§7) et le `--proxy-headers` (§8) restent actifs à l'identique — hérités
  de `docker-compose.prod.yml`, cette surcouche ne touche que `proxy` et `go-web`.

**Co-hébergement avec un autre service sur le même serveur** (80/443 déjà pris — ex. un autre
site derrière son propre Caddy) : surcharger `DASHBOARD_PORT`/`API_PORT` dans `.env` :
```dotenv
DOMAIN=203.0.113.10
DASHBOARD_PORT=8443            # au lieu de 443, déjà pris par l'autre service
API_PORT=9443                  # au lieu de 8443
```
Aucun autre changement — `docker-compose.prod-ip.yml` republie les ports demandés et les
propage au Caddyfile. Vérifier au préalable qu'ils ne sont pas eux-mêmes déjà occupés
(`sudo ss -tlnp | grep -E ':8443|:9443'`) et que le pare-feu les autorise (`sudo ufw allow
8443/tcp && sudo ufw allow 9443/tcp`).

**Bascule vers le domaine réel dès que le DNS est prêt** — deux chemins selon que 80/443 sont
libres sur ce serveur ou déjà pris par un autre service :

**A. Serveur DÉDIÉ (80/443 libres)** — aucune perte de données, juste une reconfiguration réseau :
```bash
# 1. Poser les DNS A : mon-domaine.com + api.mon-domaine.com → IP du serveur
# 2. .env : DOMAIN=mon-domaine.com (remplace l'IP)
# 3. Relancer SANS la surcouche -ip (retour au Caddyfile normal, Let's Encrypt automatique)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build proxy go-web
```

**B. Serveur CO-HÉBERGÉ (80/443 déjà pris par un autre projet, ex. SGI)** — Let's Encrypt en mode
standard (HTTP-01/TLS-ALPN-01) est IMPOSSIBLE sans ces ports. Solution : faire fronter par le
Caddy de l'AUTRE projet (déjà propriétaire de 80/443 + Let's Encrypt fonctionnel), qui reverse-proxy
directement vers `go-web`/`go-api` via un réseau Docker externe partagé — surcouche
`docker-compose.prod-fronted.yml` :
```bash
# 1. Poser les DNS A : go.mon-domaine.com + api.go.mon-domaine.com → IP du serveur
# 2. Le réseau externe partagé (créé par l'autre projet, ex. `caddy_net` côté SGI) doit exister :
docker network inspect caddy_net >/dev/null 2>&1 || docker network create caddy_net
# 3. .env : DOMAIN=go.mon-domaine.com (remplace l'IP ou le sous-domaine provisoire)
# 4. Démarrer SANS le service `proxy` (son propre Caddy devient inutile — c'est l'AUTRE Caddy
#    qui reverse-proxy). Retirer l'ancien conteneur proxy s'il tournait déjà (mode IP) :
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.prod-ip.yml \
  stop proxy && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.prod-ip.yml rm -f proxy
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.prod-fronted.yml up -d --build db redis go-api scheduler go-web
# 5. Côté AUTRE projet : ajouter 2 blocs Caddyfile (dashboard + API, reverse_proxy vers
#    go-web:3000 / go-api:8000 sur le réseau partagé — CE SONT LES NOMS DE SERVICE eux-mêmes,
#    pas de simples alias, cf. incident 2026-07-11) + variables d'env correspondantes,
#    puis recréer SON Caddy (`up -d --force-recreate caddy`) pour obtenir les certificats.
```
Aucune exposition publique propre à GuardianOps dans ce mode (`go-web`/`go-api` ne rejoignent QUE le
réseau partagé + le réseau interne du projet — 0 port publié). Fermer les règles pare-feu
ouvertes pour le mode IP si elles ne servent plus (`sudo ufw delete allow 8443/tcp` etc.).
Une fois basculé, `agent.toml` doit pointer sur le nouveau domaine public (`api_url =
"https://api.go.mon-domaine.com"`) et **`ca_cert_path` doit être retiré** — le certificat est
désormais un vrai Let's Encrypt, plus besoin de charger le CA auto-signé.

### Mise à l'échelle horizontale de l'API

L'API est **sans état** : la détection périodique des machines offline tourne
dans un process séparé (`app/scheduler.py`, service `scheduler`). On peut donc
scaler l'API librement.

Deux dimensions de scaling, combinables :

**1. Workers uvicorn (un conteneur, N process)** — régler `API_WORKERS` dans
`.env` (défaut 2 ; repère : `(2 × cœurs) + 1`), puis :

```bash
echo "API_WORKERS=4" >> .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d go-api
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

## 8bis. Agent en production (systemd)

Le `cargo run --release` du §3 (option B) ne survit pas à un reboot et ne redémarre pas
après un crash. Pour un déploiement qui tient dans la durée, packaging systemd dans
`agent/packaging/` :

```bash
cd agent
sudo ./packaging/install.sh
```

Le script (à lancer **sur l'hôte à monitorer**, en root) :
- compile en release (`cargo build --release`) — ou saute le build si `INSTALL_BIN=<chemin>`
  pointe vers un binaire déjà compilé (ex. cross-compilé ailleurs) ;
- crée un utilisateur système dédié non-root `guardianops` (sans home, sans shell) ;
- installe le binaire + `agent.toml` (copié depuis `agent.toml.example` **seulement s'il
  n'existe pas déjà** — ne jamais écraser une config existante) dans `/opt/guardianops-agent` ;
- installe et active `guardianops-agent.service` (`Restart=on-failure`, durci —
  `NoNewPrivileges`/`ProtectSystem=strict`/`ProtectHome`/`PrivateTmp` ; aucune capacité réseau
  spéciale requise, le scan est rootless cf. §9).

Après installation : éditer `/opt/guardianops-agent/agent.toml` (`api_url` + `enroll_token`,
obtenu via `POST /machines` comme au §3), puis :

```bash
sudo systemctl start guardianops-agent
sudo systemctl status guardianops-agent
sudo journalctl -u guardianops-agent -f
```

Après le premier enrôlement réussi, `agent_state.toml` apparaît dans `/opt/guardianops-agent/`
(machine_id + agent_token) — `enroll_token` peut alors être retiré de `agent.toml`.

**Mise à jour d'une version ultérieure** : ré-exécuter `sudo ./packaging/install.sh` (rebuild +
réinstalle le binaire, conserve `agent.toml`/`agent_state.toml` existants), puis
`sudo systemctl restart guardianops-agent`.

## 8ter. Durcissement du serveur (pare-feu, anti-bruteforce SSH)

Généralités serveur Linux, valables pour tout hôte exposé publiquement (le VPS qui porte
`docker-compose.prod.yml` §8, comme l'agent installé au §8bis sur l'hôte monitoré) :

```bash
# Pare-feu : seuls SSH + HTTP/HTTPS ouverts au monde
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Anti-bruteforce SSH
sudo apt install fail2ban
sudo systemctl enable --now fail2ban
```

`db`/`redis` ne sont **jamais** publiés hors de l'hôte (§8, `ports: !override []`) — ufw n'a
donc rien de plus à fermer pour eux. Sauvegarder les identifiants `.env` (`POSTGRES_PASSWORD`,
`REDIS_PASSWORD`, `JWT_SECRET`) hors du serveur, comme `CRYPTO_KEY` côté SGI.

## 9. Scan réseau (surveillance in/out)

La rubrique **Réseau** du dashboard découvre les appareils du LAN (type,
système, nom), via le scan léger de l'agent (Phase A). Ports/vulnérabilités
(Phase B) et intrusions/flux sortants (Phase C) s'ajoutent ensuite.

**Activation (côté agent, opt-in).** Dans `agent.toml`, section `[scan]` :

```toml
[scan]
enabled = true
allowlist = ["192.168.1.0/24"]   # refus par défaut hors sous-réseau local
interval_secs = 300
```

Refus par défaut : seules les plages de l'allowlist *qui recoupent un
sous-réseau local de l'hôte* sont scannées. Le scan est rootless (TCP-connect +
lecture de la table ARP `/proc/net/arp` + reverse-DNS + OUI MAC).

**⚠️ Réseau du conteneur.** Dans Docker, l'agent ne voit que le réseau du
conteneur — il ne découvrira pas le vrai LAN. Pour un scan réel, lancez l'agent
**sur l'hôte** :

```bash
# (a) binaire natif sur l'hôte (recommandé)
cargo build --release && ./target/release/guardianops-agent

# (b) conteneur en réseau hôte (Linux uniquement)
docker run --rm --network host -v "$PWD/data":/agent guardianops-agent:dev
```

**Vérification.** Après ~1 intervalle de scan, les appareils apparaissent dans
`GET /network/devices` et sur la page **Réseau** du dashboard ; l'état global du
réseau (Sain / Surveillé / Alarme / Saturé / Critique / Indisponible) est exposé
par `GET /network/summary`.

**Phase B — ports & vulnérabilités.** Sur les hôtes vivants, l'agent scanne le
top-100 des ports TCP et capture les bannières ; l'API en déduit les
vulnérabilités via des **règles d'exposition** + une **base CVE hors-ligne
embarquée** (`apps/api/app/services/vuln.py`, sous-ensemble à étendre).
Endpoints : `GET /network/devices/{id}/ports|vulns`, `GET /network/vulns`.

**Phase C — intrusions & flux sortants.** En plus du scan, l'agent collecte les
flux sortants de l'hôte (`/proc/net/tcp`) et les pousse à `POST /ingest/flows`.
L'API génère des **événements** (`GET /network/events`, page **Intrusions**) :
heuristiques de diff de scan (`new_device`, `new_open_port`, `arp_spoof`) et
analyse des flux (`outbound_suspicious` via blocklists embarquées
`services/threatintel.py`, `port_scan` par fan-out). Les événements sont poussés
en temps réel via Redis → WebSocket et alimentent l'état (Alarme / Saturé /
Critique).

**IDS Suricata (sidecar optionnel).** Inspection de trafic par signatures, via
une surcouche dédiée :
```bash
# 1) créer une machine IDS → enroll_token ; 2) .env : IDS_ENROLL_TOKEN, SURICATA_IFACE
docker compose -f docker-compose.yml -f docker-compose.suricata.yml up -d suricata ids-forwarder
```
Suricata écrit `eve.json` ; un forwarder pousse les alertes à `POST /ingest/ids`
→ événements `ids_alert` dans la page Intrusions. Détails : `infra/suricata/README.md`.

**Feeds de menace.** La blocklist IP est rafraîchie par le `scheduler` (feed
abuse.ch Feodo → Redis, `services/feeds.py`), avec repli sur la liste embarquée
hors-ligne. La base CVE est data-driven (`app/data/cve_signatures.json`).

**Notifications (webhook).** Les signaux ≥ seuil (intrusions et alertes) peuvent
être poussés vers un webhook Slack/Mattermost/Discord/générique. Dans `.env` :
```
NOTIFY_ENABLED=true
NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
NOTIFY_MIN_SEVERITY=high        # info|low|medium|high|critical
NOTIFY_FORMAT=slack             # slack|discord|generic
```
Best-effort : `services/notify.py` poste via `urllib` dans un thread et n'échoue
jamais bruyamment. Branché sur `events.record_event` (intrusions) et
`alerting.open_alert` (alertes seuils/anomalies).
