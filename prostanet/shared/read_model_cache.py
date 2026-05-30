"""In-memory TTL cache for read-only clinical read models.

This cache is intentionally process-local and never persists PHI to disk. It is
used only to avoid recomputing deterministic read models during short UI/audit
bursts.
"""
from __future__ import annotations

from copy import deepcopy
import json
from threading import RLock
from time import monotonic
from typing import Any, Callable


PATIENT_TTL_SECONDS = 30
AGGREGATE_TTL_SECONDS = 300

_LOCK = RLock()
_CACHE: dict[str, tuple[float, Any]] = {}


def build_cache_key(namespace: str, *parts: Any, **params: Any) -> str:
    """Build a stable cache key from a namespace, positional parts and params."""
    payload = {"namespace": namespace, "parts": parts, "params": params}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def get_read_model(key: str) -> Any | None:
    """Return a deep-copied cached value, or None if missing/expired."""
    now = monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= now:
            _CACHE.pop(key, None)
            return None
        return deepcopy(value)


def set_read_model(key: str, value: Any, ttl_seconds: int | float) -> Any:
    """Store a deep-copied value and return a fresh copy for the caller."""
    ttl = max(0.0, float(ttl_seconds or 0))
    with _LOCK:
        _CACHE[key] = (monotonic() + ttl, deepcopy(value))
        return deepcopy(value)


def get_or_build_read_model(
    key: str,
    builder: Callable[[], Any],
    *,
    ttl_seconds: int | float,
    refresh: bool = False,
) -> Any:
    """Return cached value unless refresh is requested, otherwise build/store."""
    if not refresh:
        cached = get_read_model(key)
        if cached is not None:
            return cached
    return set_read_model(key, builder(), ttl_seconds)


def invalidate_read_model_cache(prefix: str | None = None) -> int:
    """Invalidate all entries, or only keys containing a namespace/prefix string."""
    with _LOCK:
        if prefix is None:
            count = len(_CACHE)
            _CACHE.clear()
            return count
        keys = [key for key in _CACHE if str(prefix) in key]
        for key in keys:
            _CACHE.pop(key, None)
        return len(keys)


def cache_size() -> int:
    """Expose cache size for tests and diagnostics."""
    with _LOCK:
        return len(_CACHE)
