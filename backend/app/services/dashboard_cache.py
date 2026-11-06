"""
In-process cache + single-flight dedup for dashboard aggregation queries.

The dashboard frontend fires several parallel requests (today/yesterday/
current_month/custom, summary/all, summary/comparisons, summary/daily) that
each run heavy CTE queries against orders_raw/billing_raw. With several users
or browser tabs open at once this multiplies into a dozen-plus identical
queries running concurrently against Postgres.

Underlying data only changes on the hourly Allegro sync, so a short TTL cache
is safe. Single-flight collapses concurrent identical requests (same tenant,
account, method, period, currency, search) into one DB call instead of N.

Backend runs a single uvicorn worker (see CLAUDE.md — do not add workers,
would also break the in-memory login rate limiter), so a process-local cache
guarded by threading.Lock is sufficient; no Redis/cross-process cache needed.
Dashboard endpoints are sync `def` routes, so FastAPI runs each one in a
threadpool thread — hence plain `threading.Lock`, not asyncio primitives.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 90.0

_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, object]] = {}
_key_locks: dict[tuple, threading.Lock] = {}


def _evict_expired(now: float) -> None:
    expired = [k for k, (expires_at, _) in _cache.items() if expires_at <= now]
    for k in expired:
        del _cache[k]
        lock = _key_locks.get(k)
        # Only drop the lock if nobody is currently holding it, otherwise a
        # concurrent single-flight computation could end up using a lock
        # object no other thread can see anymore.
        if lock is not None and lock.acquire(blocking=False):
            try:
                del _key_locks[k]
            finally:
                lock.release()


def cached_call(key: tuple, compute: Callable[[], T], ttl: float = DEFAULT_TTL_SECONDS) -> T:
    """Return compute()'s result, cached under `key` for `ttl` seconds.

    Concurrent calls with the same key block on a per-key lock so only one
    of them actually executes compute(); the rest reuse its result.
    `key` must fully identify the tenant/account/method/period/currency/
    search combination — never share a key across tenants.
    """
    now = time.monotonic()
    with _cache_lock:
        _evict_expired(now)
        entry = _cache.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
        key_lock = _key_locks.setdefault(key, threading.Lock())

    with key_lock:
        now = time.monotonic()
        with _cache_lock:
            entry = _cache.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]
        value = compute()
        with _cache_lock:
            _cache[key] = (time.monotonic() + ttl, value)
        return value
