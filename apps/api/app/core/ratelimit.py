"""Anti brute-force du login (`/auth/login`) — devient nécessaire dès que l'API est exposée
publiquement (topologie split : dashboard GuardianOps sur un domaine public, cf. docs/runbook.md).

Compte les ÉCHECS par IP sur une fenêtre glissante (sorted set Redis, 1 par IP) ; au-delà du
seuil → bloqué jusqu'à ce que les échecs les plus anciens sortent de la fenêtre. Un succès
réinitialise le compteur (un admin légitime n'est pas verrouillé par ses propres essais réussis).

**Fail-open** sur panne Redis : une panne d'infra ne doit jamais verrouiller la seule voie
d'accès admin de GuardianOps.
"""
from __future__ import annotations

import logging
import time
import uuid

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# 5 échecs / 5 min : tolère les fautes de frappe d'un humain, coupe court à un bourrage automatisé.
DEFAULT_MAX_FAILURES = 5
DEFAULT_WINDOW_SECONDS = 300


class LoginRateLimiter:
    """Fenêtre glissante des échecs de login, comptée par clé (IP cliente) via un sorted set
    Redis : chaque échec = un membre unique (`<ts>:<uuid>`, anti-collision), score = horodatage.
    `zremrangebyscore` purge hors fenêtre, `zcard` compte, `zadd` enregistre, `expire` auto-nettoie."""

    def __init__(
        self,
        redis,
        max_failures: int = DEFAULT_MAX_FAILURES,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        *,
        prefix: str = "login_rl",
    ) -> None:
        self._r = redis
        self._max = max_failures
        self._window = window_seconds
        self._prefix = prefix

    @property
    def window_seconds(self) -> int:
        return self._window

    def _key(self, ip: str) -> str:
        return f"{self._prefix}:{ip}"

    async def is_blocked(self, ip: str) -> bool:
        key = self._key(ip)
        now = time.time()
        try:
            await self._r.zremrangebyscore(key, 0, now - self._window)
            count = await self._r.zcard(key)
            return count >= self._max
        except RedisError:
            logger.warning("LOGIN_RATE_LIMIT_REDIS_DOWN op=is_blocked — fail-open", exc_info=True)
            return False

    async def register_failure(self, ip: str) -> None:
        key = self._key(ip)
        now = time.time()
        try:
            await self._r.zremrangebyscore(key, 0, now - self._window)
            await self._r.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
            await self._r.expire(key, self._window + 1)
        except RedisError:
            logger.warning(
                "LOGIN_RATE_LIMIT_REDIS_DOWN op=register_failure — fail-open", exc_info=True
            )

    async def reset(self, ip: str) -> None:
        try:
            await self._r.delete(self._key(ip))
        except RedisError:
            logger.warning("LOGIN_RATE_LIMIT_REDIS_DOWN op=reset — fail-open", exc_info=True)

    async def retry_after(self, ip: str) -> int:
        try:
            oldest = await self._r.zrange(self._key(ip), 0, 0, withscores=True)
        except RedisError:
            return 0
        if not oldest:
            return 0
        ts = float(oldest[0][1])
        return max(0, int(self._window - (time.time() - ts)) + 1)
