"""Byte-capped LRU for query-independent content analyses (S7).

The pre-1.11 memos were entry-count LRUs keyed by the full input string: a handful of
6-entry caches could still pin hundreds of MB in a long-lived host (a 1M-char text as a
dict key is the whole text retained). ``ContentCache`` instead keys every record by a
``content_key`` digest — the text itself is never stored, neither as key nor in the record
— and evicts by *weight* (``sys.getsizeof``-based live record weight, as computed
by ``weight_of``), default 64 MB per process.

Records are the compact analyses the engine already computed: bools, ints, fingerprint
maps, fact tuples, line bundles. They aim at a few percent of the source text and never
contain the text itself; anything that would not fit the cap is simply not stored.
"""

from __future__ import annotations

import functools
import hashlib
import os
import sys
import threading
from collections import OrderedDict
from typing import Any

_DEFAULT_MAX_BYTES = 64 << 20
_MAX_ANALYSIS_COUNTS = 4096
_MISS = object()


def _env_max_bytes() -> int:
    raw = os.environ.get("TAMERU_CACHE_MAX_BYTES", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return _DEFAULT_MAX_BYTES


def weight_of(value: Any, _depth: int = 0) -> int:
    """Live memory of a record — the accounting weight the cache evicts on."""
    w = sys.getsizeof(value)
    if _depth >= 6 or value is None or isinstance(value, (int, float, bool, str, bytes)):
        return w
    if isinstance(value, dict):
        for k, v in value.items():
            w += weight_of(k, _depth + 1) + weight_of(v, _depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            w += weight_of(item, _depth + 1)
    elif hasattr(value, "__dict__"):
        w += weight_of(vars(value), _depth + 1)
    return w


class ContentCache:
    """Thread-safe LRU evicting by accumulated record weight."""

    def __init__(self, max_bytes: int | None = None) -> None:
        self.max_bytes = _env_max_bytes() if max_bytes is None else max_bytes
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[Any, int]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.analyses = 0
        self.evictions = 0
        self.bytes = 0
        self.analysis_counts: dict[str, int] = {}

    def get(self, key: str) -> Any:
        """The stored record or ``_MISS``; never returns ``None`` so ``None`` may be stored."""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self.misses += 1
                return _MISS
            self._items.move_to_end(key)
            self.hits += 1
            return item[0]

    def set(self, key: str, value: Any) -> None:
        weight = weight_of(value)
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self.bytes -= old[1]
            self.analyses += 1
            self.analysis_counts[key] = self.analysis_counts.get(key, 0) + 1
            if len(self.analysis_counts) > _MAX_ANALYSIS_COUNTS:
                self.analysis_counts.pop(next(iter(self.analysis_counts)))
            if weight > self.max_bytes or self.max_bytes <= 0:
                self.evictions += 1
                return
            self._items[key] = (value, weight)
            self.bytes += weight
            while self.bytes > self.max_bytes:
                _k, (_v, w) = self._items.popitem(last=False)
                self.bytes -= w
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.bytes = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_bytes": self.max_bytes,
                "bytes": self.bytes,
                "entries": len(self._items),
                "hits": self.hits,
                "misses": self.misses,
                "analyses": self.analyses,
                "evictions": self.evictions,
                "analysis_counts": dict(self.analysis_counts),
            }


def content_key(version: str, name: str, text: str, extra: tuple = ()) -> str:
    """``sha256(engine version, analysis name, text, options)`` — the key leaks nothing."""
    digest = hashlib.sha256()
    for part in (version, name, *(str(e) for e in extra), text):
        encoded = part.encode("utf-8", errors="surrogatepass")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()[:32]


# The process-wide cache the engine's query-independent analyses share. ``compress_context``
# also keeps a second instance for the scored-blocks memo (its key includes the query).
CACHE = ContentCache()


def content_memo(name: str, *, max_chars: int | None = None, version: Any = ""):
    """Decorator: cache ``fn(text, *extra)`` in ``CACHE`` under a ``content_key`` digest.

    Texts longer than ``max_chars`` bypass the cache (same bound the old memos had).
    ``version`` may be a string or a zero-arg callable (for lazy ``ENGINE_VERSION`` lookups
    in modules ``compress_context`` itself imports). The wrapper's ``cache_clear``
    clears the whole shared ``CACHE``, not just this analysis."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(text, *extra):
            if type(text) is not str or (max_chars is not None and len(text) > max_chars):
                return fn(text, *extra)
            v = version() if callable(version) else version
            key = content_key(str(v), name, text, extra)
            hit = CACHE.get(key)
            if hit is _MISS:
                hit = fn(text, *extra)
                CACHE.set(key, hit)
            return hit

        wrapper.cache_clear = CACHE.clear
        return wrapper

    return deco


@functools.lru_cache(maxsize=1)
def _engine_version() -> str:
    from .compress_context import ENGINE_VERSION

    return ENGINE_VERSION
