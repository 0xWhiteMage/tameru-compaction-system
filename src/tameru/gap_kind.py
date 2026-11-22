"""Call a caller's gap marker, passing ``kind`` only when it declares a parameter of that name (1.10.0)."""
import functools
import inspect

@functools.lru_cache(maxsize=64)
def _accepts_kind_cached(fn) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    param = params.get("kind")
    return param is not None and param.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
    )


def gap_accepts_kind(fn) -> bool:
    """True when ``fn`` declares a ``kind`` parameter (decided once per callable, cached)."""
    if fn is None:
        return False
    if not (inspect.isfunction(fn) or inspect.isbuiltin(fn)):
        return _accepts_kind_cached.__wrapped__(fn)
    try:
        return _accepts_kind_cached(fn)
    except TypeError:  # unhashable callable: decide without the cache
        return _accepts_kind_cached.__wrapped__(fn)


def call_gap_marker(fn, omitted: int, total: int, kind: str = "lines"):
    """Call a caller's gap marker, passing ``kind`` only when it declares one."""
    if gap_accepts_kind(fn):
        return fn(omitted, total, kind=kind)
    return fn(omitted, total)
