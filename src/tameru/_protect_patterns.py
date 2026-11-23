"""Bound configured pin searches before they reach the backtracking regex engine."""

from __future__ import annotations

import functools
import re

try:
    from re import _constants as const, _parser as parser
except ImportError:  # Python 3.10
    import sre_constants as const
    import sre_parse as parser

_MAX_PATTERNS = 32
_MAX_CHARS = 200
_MAX_REPEAT = 32
_MAX_COST = 128
_MAX_TOTAL_COST = 256
_REPEATS = tuple(
    getattr(const, name) for name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT")
    if hasattr(const, name)
)
_ATOMIC = getattr(const, "ATOMIC_GROUP", None)
_TERMINALS = frozenset((const.LITERAL, const.NOT_LITERAL, const.ANY, const.IN, const.AT, const.CATEGORY))


@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> tuple[re.Pattern[str], int] | None:
    cost = 1

    def walk(sub, repeat_bound=None):
        nonlocal cost
        has_repeats = False
        width = 0
        for op, value in sub:
            width += 1
            if op in _REPEATS:
                if repeat_bound is not None or value[1] > _MAX_REPEAT:
                    raise ValueError("unbounded or nested protection repeat")
                _, body_width = walk(value[2], value[1])
                cost *= (value[1] + 1) * max(1, body_width)
                has_repeats = True
                width += body_width
            elif op == const.SUBPATTERN:
                inner_repeats, body_width = walk(value[3], repeat_bound)
                has_repeats |= inner_repeats
                width += body_width
            elif op == const.BRANCH:
                if repeat_bound is not None and repeat_bound > 1:
                    raise ValueError("repeated protection alternation")
                branches = [walk(branch, repeat_bound) for branch in value[1]]
                width += sum(size for _, size in branches)
                if any(inner_repeats for inner_repeats, _ in branches):
                    cost *= len(branches)
                    has_repeats = True
            elif op in (const.ASSERT, const.ASSERT_NOT):
                inner_repeats, body_width = walk(value[1], repeat_bound)
                has_repeats |= inner_repeats
                width += body_width
            elif _ATOMIC is not None and op == _ATOMIC:
                inner_repeats, body_width = walk(value, repeat_bound)
                has_repeats |= inner_repeats
                width += body_width
            elif op not in _TERMINALS:
                raise ValueError("unsupported protection regex construct")
            if cost > _MAX_COST:
                raise ValueError("protection regex cost exceeded")
        return has_repeats, width

    try:
        walk(parser.parse(pattern))
        return re.compile(pattern), cost
    except (re.error, ValueError, OverflowError, RecursionError):
        return None


def compile_pin_patterns(patterns) -> tuple[re.Pattern[str], ...] | None:
    """Return bounded expressions, or None when the entire call must preserve its input."""
    if patterns is None:
        return ()
    if not isinstance(patterns, (list, tuple)) or len(patterns) > _MAX_PATTERNS:
        return None
    expressions = []
    total_cost = 0
    for pattern in patterns:
        if type(pattern) is not str or len(pattern) > _MAX_CHARS:
            return None
        compiled = _compile(pattern)
        if compiled is None:
            return None
        expression, cost = compiled
        total_cost += cost
        if total_cost > _MAX_TOTAL_COST:
            return None
        expressions.append(expression)
    return tuple(expressions)
