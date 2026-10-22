"""Private compiled-regex cache for patterns built from queries or input text.

Python's ``re`` module cache is small; dynamic patterns routed through it evict each
other (and tameru's literal patterns) on large workloads. ``cached_compile`` keeps
them in a dedicated LRU cache instead.
"""

from __future__ import annotations

import functools
import re


@functools.lru_cache(maxsize=4096)
def cached_compile(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """``re.compile(pattern, flags)``, memoised independently of the ``re`` cache."""
    return re.compile(pattern, flags)
