"""Process-local caches shared across modules.

Two layers:

- ``TTLCache``: a bounded LRU that also evicts entries after a TTL. Used for
  GitHub API responses and any other expensive, time-sensitive lookups.
- ``memoize``: decorator for pure functions whose return value never changes
  for a given process (config-derived constants, slug computations).

All caches are process-local and not coordinated across replicas. The webhook
receiver runs as a single replica, and the poller is a background task inside
that same process, so a single shared instance is correct and sufficient.

Tuning knobs live on the cache itself (maxsize / ttl) rather than in env vars,
because the right values depend on call frequency, not on the deployment
environment. Callers pick the values that match their data's staleness budget.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from functools import wraps
from typing import Any, TypeVar

__all__ = ["TTLCache", "memoize"]

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class TTLCache:
    """Bounded LRU cache with per-entry TTL eviction.

    Thread-safe via a single coarse-grained lock. Get/set/contains are O(1).
    Expired entries are evicted lazily on access (and pruned on ``set`` when
    the cache is full), which avoids background timers and keeps the poller
    loop predictable.

    Args:
        maxsize: Maximum number of live entries. Once exceeded, the least
            recently used live entry is evicted.
        ttl: Time-to-live in seconds. Entries older than this are treated as
            misses and evicted on next access.
    """

    def __init__(self, maxsize: int = 128, ttl: float = 60.0) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        self._maxsize = maxsize
        self._ttl = ttl
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the cached value if present and fresh, else ``default``."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                # Expired — drop it so it doesn't waste space.
                self._data.pop(key, None)
                return default
            # Mark as recently used.
            self._data.move_to_end(key)
            return value

    def set(self, key: Any, value: Any) -> None:
        """Insert or update ``key``. Evicts LRU/expired entries when full."""
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            if key in self._data:
                self._data[key] = (expires_at, value)
                self._data.move_to_end(key)
                return
            while len(self._data) >= self._maxsize:
                # Drop the oldest entry; if it's the one we'd evict, so be it.
                self._data.popitem(last=False)
            self._data[key] = (expires_at, value)

    def __contains__(self, key: Any) -> bool:
        """True only if ``key`` is present and still fresh."""
        return self.get(key, _MISSING) is not _MISSING

    def clear(self) -> None:
        """Drop every entry."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


_MISSING: Any = object()


def memoize(fn: Callable[..., _V]) -> Callable[..., _V]:
    """Cache a nullary-or-pure function's result for the process lifetime.

    Intended for functions whose output is constant per process (env-derived
    config, deterministic slugifiers). The wrapped function is called at most
    once; subsequent calls return the cached value. Not size-bounded — only
    use for small, fixed input domains.
    """
    sentinel: list[Any] = []  # mutable cell so the closure can rebind

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> _V:
        if not sentinel:
            sentinel.append(fn(*args, **kwargs))
        return sentinel[0]

    return wrapper
