"""Engine-owned request and result schema for a host worker process (1.10.0 interface layer).

A host that runs the engine in a worker sends one JSON object per request. This module decides what
is accepted, so every host shares one list of fields, types, ranges and closed enums. It performs no
I/O. Rules:

* Unknown fields are rejected. Fields that would write, reach a network, load code or pick a model
  (``ccr``, ``log_dir``, summary options, ``semantic_tier``) do not exist here; ``ccr`` is always off.
* Version 1 (the field set of 1.9.x workers) validates exactly as before. Fields marked v2 need
  ``protocol`` 2 (or no ``protocol`` field, which means "whatever this engine speaks").
* ``pin_patterns`` are at most ``MAX_PIN_PATTERNS`` items of at most ``MAX_PIN_CHARS`` characters,
  each a regex string or ``{"literal": "..."}``. A regex is compiled inside a guarded ``try`` and
  rejected when a conservative static check sees a construct that can backtrack catastrophically
  (a quantified group that holds a quantifier or an alternation, or a back-reference), or a pattern with
  any unbounded quantifier, more than 4 optional ones or more than 6 alternations (see ``regex_risk``).
  Pins are still matched against the full text of each block.
* A rejection is a ``ProtocolError`` whose ``code`` is a fixed identifier. It never contains request
  text, not even a field name.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .compress_context import ENGINE_VERSION, RESULT_SCHEMA
from .presets import preset_names, resolve_preset

PROTOCOL_VERSION = 2
MAX_PIN_PATTERNS = 16
MAX_PIN_CHARS = 200
MAX_REPLY_REASONS = 20

MODES = ("adaptive", "fixed", "compiler", "precision")
STRATEGIES = ("extract",)
CONTENT_HINTS = ("code", "numbered_code", "log", "json", "text", "diff", "grep", "test")

V1_FIELDS = frozenset({
    "id", "op", "text", "query", "mode", "budget_ratio", "pin_recent", "min_savings_ratio",
    "derive_query", "citations",
})
V2_FIELDS = frozenset({
    "protocol", "preset", "content_hint", "pin_patterns", "anchor_errors", "prose_brief",
    "strategy", "redact_secrets", "inline_short_gaps",
})
ALL_FIELDS = V1_FIELDS | V2_FIELDS
_BOOL_FIELDS = ("derive_query", "citations", "anchor_errors", "prose_brief", "redact_secrets", "inline_short_gaps")
_BRACE_QUANT = re.compile(r"\{\d*,\d*\}|\{\d+\}")


class ProtocolError(Exception):
    """A rejected request. ``code`` is a fixed identifier; nothing from the request is in it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def clean_text(text: str) -> tuple[str, bool]:
    """Lone surrogates (valid in JavaScript strings, not encodable as UTF-8) become U+FFFD."""
    try:
        text.encode("utf-8")
        return text, False
    except UnicodeEncodeError:
        return "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in text), True


def _number(value: Any, low: float, high: float, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (low <= float(value) <= high):
        raise ProtocolError(code)
    return float(value)


_BRACE_BODY = re.compile(r"\{(\d*)(,?)(\d*)\}")
MAX_UNBOUNDED = 0       # `*`, `+`, `{n,}` and any `{n,m}` with m >= _BIG_BOUND, per pattern
MAX_OPTIONAL = 4        # `?` and small `{n,m}` quantifiers, per pattern
MAX_ALTERNATIONS = 6    # `|`, per pattern
_BIG_BOUND = 50


def regex_risk(pattern: str) -> bool:
    """True when ``pattern`` holds a construct this check refuses (conservative, nothing is matched).

    Refused: back-references and conditionals; a quantified group that holds a quantifier or an
    alternation (``(a+)+``, ``(a|a)*b``); any unbounded quantifier (``*``, ``+``,
    ``{n,}``, or a bound of 50 or more), because even one (``a*b``) is quadratic on a long run and
    several (``a*a*b``, ``.*x.*y``) are polynomial, and pins match the full block; more than ``MAX_OPTIONAL`` (4) ``?`` or small-bound quantifiers (``a?a?a?...a`` is
    exponential); more than ``MAX_ALTERNATIONS`` (6) ``|``. Literals (``{"literal": ...}``) are
    escaped and never reach this check."""
    if re.search(r"\\[1-9]|\(\?P=|\(\?\(", pattern):
        return True
    unbounded = optional = alternations = 0
    stack: list[list[bool]] = []   # enclosing groups' [has_quantifier, has_alternation]
    cur = [False, False]
    in_class = False
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "[":
            in_class = True
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            continue
        if ch == "(":
            stack.append(cur)
            cur = [False, False]
        elif ch == ")":
            if not stack:
                return False  # unbalanced: compile rejects it
            inner, cur = cur, stack.pop()
            nxt = pattern[i + 1] if i + 1 < n else ""
            quantified = nxt in ("+", "*") or (nxt == "{" and _BRACE_QUANT.match(pattern, i + 1) is not None)
            if quantified and (inner[0] or inner[1]):
                return True
            if quantified or inner[0]:
                cur[0] = True
            if inner[1]:
                cur[1] = True
        elif ch == "|":
            cur[1] = True
            alternations += 1
        elif ch in "+*":
            cur[0] = True
            unbounded += 1
        elif ch == "?" and pattern[i - 1:i] != "(":
            optional += 1
        elif ch == "{" and _BRACE_QUANT.match(pattern, i):
            cur[0] = True
            low, comma, high = _BRACE_BODY.match(pattern, i).groups()
            if (comma and not high) or (high or low) and int(high or low) >= _BIG_BOUND:
                unbounded += 1
            else:
                optional += 1
        i += 1
    return unbounded > MAX_UNBOUNDED or optional > MAX_OPTIONAL or alternations > MAX_ALTERNATIONS


def _pin_patterns(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_PIN_PATTERNS:
        raise ProtocolError("bad_pin_patterns")
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            if set(item) != {"literal"} or not isinstance(item["literal"], str):
                raise ProtocolError("bad_pin_patterns")
            text = item["literal"]
            if not text or len(text) > MAX_PIN_CHARS:
                raise ProtocolError("bad_pin_patterns")
            out.append(re.escape(text))
            continue
        if not isinstance(item, str) or not item or len(item) > MAX_PIN_CHARS or regex_risk(item):
            raise ProtocolError("bad_pin_patterns")
        try:
            re.compile(item)
        except (re.error, RecursionError, ValueError, OverflowError):
            raise ProtocolError("bad_pin_patterns") from None
        out.append(item)
    return out


def validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Check a ``compress`` request and return the keyword arguments for ``compress_context``.

    The result holds ``context`` and ``query`` (lone surrogates replaced) and the options, always
    with ``ccr=False``. Raises ``ProtocolError``."""
    if not isinstance(request, Mapping):
        raise ProtocolError("bad_request")
    if set(request) - ALL_FIELDS:
        raise ProtocolError("unknown_field")
    declared = request.get("protocol", PROTOCOL_VERSION)
    if isinstance(declared, bool) or declared not in (1, 2):
        raise ProtocolError("bad_protocol")
    if declared == 1 and (set(request) & V2_FIELDS) - {"protocol"}:
        raise ProtocolError("field_needs_protocol_2")
    text, query = request.get("text"), request.get("query", "")
    if not isinstance(text, str):
        raise ProtocolError("bad_text")
    if not isinstance(query, str):
        raise ProtocolError("bad_query")
    options: dict[str, Any] = {}
    if "preset" in request:
        preset = request["preset"]
        if not isinstance(preset, str) or preset not in preset_names():
            raise ProtocolError("bad_preset")
        options.update(resolve_preset(preset))
    options.setdefault("strategy", "extract")   # the 1.x worker defaults, under any preset
    options.setdefault("citations", False)
    mode = request.get("mode", "adaptive")
    if mode not in MODES:
        raise ProtocolError("bad_mode")
    options["mode"] = mode
    if "strategy" in request:
        if request["strategy"] not in STRATEGIES:
            raise ProtocolError("bad_strategy")
        options["strategy"] = request["strategy"]
    if "content_hint" in request:
        if request["content_hint"] not in CONTENT_HINTS:
            raise ProtocolError("bad_content_hint")
        options["content_hint"] = request["content_hint"]
    if "budget_ratio" in request:
        options["budget_ratio"] = _number(request["budget_ratio"], 0.01, 1.0, "bad_budget_ratio")
    if "min_savings_ratio" in request:
        options["min_savings_ratio"] = _number(request["min_savings_ratio"], 0.0, 1.0, "bad_min_savings_ratio")
    if "pin_recent" in request:
        options["pin_recent"] = int(_number(request["pin_recent"], 0, 50, "bad_pin_recent"))
    for flag in _BOOL_FIELDS:
        if flag in request:
            if not isinstance(request[flag], bool):
                raise ProtocolError(f"bad_{flag}")
            options[flag] = request[flag]
    if "pin_patterns" in request:
        options["pin_patterns"] = _pin_patterns(request["pin_patterns"])
    options["ccr"] = False
    return {"context": clean_text(text)[0], "query": clean_text(query)[0], **options}


def request_was_sanitized(request: Mapping[str, Any]) -> bool:
    """True when ``validate_request`` replaced a lone surrogate in the text or the query."""
    return any(isinstance(request.get(k), str) and clean_text(request[k])[1] for k in ("text", "query"))


def result_to_dict(result: Any, *, sanitized: bool = False, preset: str | None = None) -> dict[str, Any]:
    """The reply body for a ``compress`` request: the version 1 keys, plus ``result_schema`` and the result schema 2
    fields (``confidence_basis``, ``stable_key``, ``dropped``, ``preset``). Every v1 key keeps its meaning."""
    return {
        "text": result.compressed_text,
        "fail_open": bool(result.fail_open),
        "original_tokens": int(result.original_tokens),
        "kept_tokens": int(result.kept_tokens),
        "tokens_saved_pct": float(result.tokens_saved_pct),
        "risk": result.compression_risk,
        "confidence": result.confidence,
        "content_type": result.content_type,
        "reasons": [str(r)[:120] for r in list(result.reasons)[:MAX_REPLY_REASONS]],
        "sanitized": bool(sanitized),
        "result_schema": RESULT_SCHEMA,
        "confidence_basis": str(getattr(result, "confidence_basis", "none")),
        "stable_key": str(getattr(result, "stable_key", "")),
        "dropped": [[str(c), int(n), str(loc)[:80]] for c, n, loc in (getattr(result, "dropped", None) or ())[:3]],
        "preset": preset if preset is not None else getattr(result, "preset", None),
    }


def describe(result: Any, *, preset: str | None = None, decision: Any = None) -> dict[str, Any]:
    """Additive 1.10.0 facts about a result, kept outside ``CompressResult`` so its
    ``dataclasses.asdict`` (and the golden hash) do not change: schema, preset and decision."""
    out: dict[str, Any] = {"result_schema": RESULT_SCHEMA, "preset": preset}
    if decision is not None:
        out["decision"] = {"accept": decision.accept, "reason": decision.reason, "basis": decision.basis}
    return out


def version_info() -> dict[str, Any]:
    return {
        "engine": ENGINE_VERSION,
        "protocol": PROTOCOL_VERSION,
        "result_schema": RESULT_SCHEMA,
        "presets": preset_names(),
    }
