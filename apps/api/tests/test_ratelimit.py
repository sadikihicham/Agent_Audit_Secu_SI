"""Tests unitaires du rate-limiter login (sans Redis réel — sorted set en mémoire)."""
from __future__ import annotations

import time

import pytest
from redis.exceptions import RedisError

from app.core.ratelimit import LoginRateLimiter


class _FakeSortedSetRedis:
    """Reproduit le sous-ensemble de l'API Redis utilisé par LoginRateLimiter
    (zremrangebyscore/zcard/zadd/expire/zrange/delete) sur un dict en mémoire."""

    def __init__(self) -> None:
        self._sets: dict[str, dict[str, float]] = {}

    async def zremrangebyscore(self, key: str, min_: float, max_: float) -> None:
        members = self._sets.get(key, {})
        self._sets[key] = {m: s for m, s in members.items() if not (min_ <= s <= max_)}

    async def zcard(self, key: str) -> int:
        return len(self._sets.get(key, {}))

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._sets.setdefault(key, {}).update(mapping)

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        pass  # TTL non simulé — les tests purgent explicitement via zremrangebyscore

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False):  # noqa: ARG002
        members = sorted(self._sets.get(key, {}).items(), key=lambda kv: kv[1])
        return members[start : end + 1 if end >= 0 else None]

    async def delete(self, key: str) -> None:
        self._sets.pop(key, None)


class _BrokenRedis:
    """Simule une panne Redis : toute opération lève RedisError."""

    async def _fail(self, *_a, **_kw):
        raise RedisError("connexion refusée")

    zremrangebyscore = _fail
    zcard = _fail
    zadd = _fail
    expire = _fail
    zrange = _fail
    delete = _fail


@pytest.mark.asyncio
async def test_allows_under_threshold() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    for _ in range(4):
        await limiter.register_failure("1.2.3.4")
    assert await limiter.is_blocked("1.2.3.4") is False


@pytest.mark.asyncio
async def test_blocks_at_threshold() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    for _ in range(5):
        await limiter.register_failure("1.2.3.4")
    assert await limiter.is_blocked("1.2.3.4") is True


@pytest.mark.asyncio
async def test_keys_are_independent_per_ip() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    for _ in range(5):
        await limiter.register_failure("1.2.3.4")
    assert await limiter.is_blocked("5.6.7.8") is False


@pytest.mark.asyncio
async def test_old_failures_outside_window_are_pruned() -> None:
    redis = _FakeSortedSetRedis()
    limiter = LoginRateLimiter(redis, max_failures=5, window_seconds=300)
    old = time.time() - 400  # hors fenêtre (> 300s)
    await redis.zadd("login_rl:1.2.3.4", {f"{old}:a": old, f"{old}:b": old})
    assert await limiter.is_blocked("1.2.3.4") is False


@pytest.mark.asyncio
async def test_reset_clears_failures() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    for _ in range(5):
        await limiter.register_failure("1.2.3.4")
    await limiter.reset("1.2.3.4")
    assert await limiter.is_blocked("1.2.3.4") is False


@pytest.mark.asyncio
async def test_retry_after_positive_when_blocked() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    for _ in range(5):
        await limiter.register_failure("1.2.3.4")
    retry = await limiter.retry_after("1.2.3.4")
    assert 0 < retry <= 300


@pytest.mark.asyncio
async def test_retry_after_zero_when_no_failures() -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    assert await limiter.retry_after("1.2.3.4") == 0


@pytest.mark.asyncio
async def test_fail_open_on_redis_error() -> None:
    """Une panne Redis ne doit jamais verrouiller la seule voie d'accès admin."""
    limiter = LoginRateLimiter(_BrokenRedis(), max_failures=5, window_seconds=300)
    assert await limiter.is_blocked("1.2.3.4") is False
    await limiter.register_failure("1.2.3.4")  # ne doit pas lever
    await limiter.reset("1.2.3.4")  # ne doit pas lever
    assert await limiter.retry_after("1.2.3.4") == 0
