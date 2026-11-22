"""Engine-owned request and result schema for a host worker process (1.10.0 interface layer).

A host that runs the engine in a worker sends one JSON object per request. This module decides what
is accepted, so every host shares one list of fields, types, ranges and closed enums. It performs no
I/O. Rules:

* Unknown fields are rejected. Fields that would write, reach a network, load code or pick a model
  (``ccr``, ``log_dir``, summary options, ``semantic_tier``) do not exist here; ``ccr`` is always off.
* Version 1 (the field set of 1.9.x workers) validates exactly as before. Fields marked v2 need
  ``protocol`` 2, fields marked v3 need ``protocol`` 3 (no ``protocol`` field means "whatever this
  engine speaks").
* ``pin_patterns`` are at most ``MAX_PIN_PATTERNS`` items of at most ``MAX_PIN_CHARS`` characters,
  each a regex string or ``{"literal": "..."}``. A regex is compiled inside a guarded ``try`` and
  rejected when a conservative static check sees a construct that can backtrack catastrophically
  (a quantified group that holds a quantifier or an alternation, or a back-reference), or a pattern with
  any unbounded quantifier, more than 4 optional ones or more than 6 alternations (see ``regex_risk``).
  Pins are still matched against the full text of each block.
* Version 3 adds ``selector_query`` (passed through to ``compress_context``) and
  ``derive_selector_query`` (a flag the worker resolves into ``selector_query`` from the query parts
  it accepts, via ``transcript.build_selector_query``; it is not a ``compress_context`` parameter,
  so the worker pops it before the call). It also adds the ``plan`` request: a closed ``PlanInput``
  body validated by ``validate_plan_request``, answered with ``plan_to_dict``.
* A rejection is a ``ProtocolError`` whose ``code`` is a fixed identifier. It never contains request
  text, not even a field name.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .compress_context import ENGINE_VERSION, RESULT_SCHEMA
from .decide import _EV_STRENGTHS, EVPolicy, Policy
from .loss import profile_names as loss_profile_names
from .plan import (
    ACTIONS,
    EVENTS,
    HOST_MODES,
    STOCK_ACTIONS,
    CacheState,
    Candidate,
    Plan,
    PlanInput,
    PlanItem,
    _RISK_ORDER,
)
from .presets import preset_names, resolve_preset
from .prices import profile_names as price_profile_names

PROTOCOL_VERSION = 3
MAX_PIN_PATTERNS = 16
MAX_PIN_CHARS = 200
MAX_REPLY_REASONS = 20
MAX_PLAN_ITEMS = 2000
MAX_PLAN_TOKENS = 1_000_000_000    # any token/character quantity in a plan request
MAX_PLAN_STEPS = 1_000_000         # positions, ages and step counts
MAX_ID_CHARS = 256                 # item ids and superseded_by references
MAX_STRATUM_CHARS = 64

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
V3_FIELDS = frozenset({"selector_query", "derive_selector_query"})
ALL_FIELDS = V1_FIELDS | V2_FIELDS | V3_FIELDS

PLAN_FIELDS = frozenset({
    "id", "op", "protocol",
    "event", "host_mode", "prompt_tokens", "trigger_tokens",
    "items", "cache", "policy",
    "steps_since_last_act", "K", "H", "steps_to_trigger", "retained_budget_chars",
    "growth_tokens_per_step", "margin_steps", "replace_compaction",
})
ITEM_FIELDS = frozenset({
    "id", "position", "tokens", "chars", "age_steps", "protected", "stock_action",
    "stock_kept_chars", "candidate", "fact_lines", "superseded_by",
    "facts_covered_by_successor", "stratum",
})
CANDIDATE_FIELDS = frozenset({
    "compressed_chars", "tokens_saved", "confidence", "fail_open",
    "risk", "fingerprints_ok", "fact_lines_dropped",
})
CACHE_FIELDS = frozenset({"warm", "n_eff"})
PLAN_POLICY_FIELDS = frozenset({
    "min_confidence", "max_risk", "require_fingerprints",
    "min_saved_ratio", "min_tokens_saved", "allow_sanitized", "ev",
})
EV_FIELDS = frozenset({"price_profile", "loss_profile", "strength", "quantile"})
RISKS = tuple(_RISK_ORDER)
_BOOL_FIELDS = ("derive_query", "citations", "anchor_errors", "prose_brief", "redact_secrets", "inline_short_gaps")
_BRACE_QUANT = re.compile(r"\{\d*,\d*\}|\{\d+\}")


class ProtocolError(Exception):
    """A rejected request. ``code`` is a fixed identifier; nothing from the request is in it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_SURROGATE = re.compile("[\ud800-\udfff]")


def clean_text(text: str) -> tuple[str, bool]:
    """Lone surrogates (valid in JavaScript strings, not encodable as UTF-8) become U+FFFD."""
    cleaned, count = _SURROGATE.subn("\ufffd", text)
    return cleaned, count > 0


def _number(value: Any, low: float, high: float, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(code)
    try:
        number = float(value)
    except OverflowError:   # an int too large for a float is out of every range
        raise ProtocolError(code) from None
    if not (low <= number <= high):
        raise ProtocolError(code)
    return number


_BRACE_BODY = re.compile(r"\{(\d*)(,?)(\d*)\}")
MAX_UNBOUNDED = 0       # `*`, `+`, `{n,}` and any `{n,m}` with m >= _BIG_BOUND, per pattern
MAX_OPTIONAL = 4        # `?` and small `{n,m}` quantifiers, per pattern
MAX_ALTERNATIONS = 6    # `|`, per pattern
_BIG_BOUND = 50


def regex_risk(pattern: str) -> bool:
    """True when ``pattern`` holds a construct this check refuses (conservative, nothing is matched).

    Refused: back-references, conditionals and the verbose flag ``(?x)`` (its ``#`` comments and
    ignored whitespace would hide constructs from this scan); a quantified group that holds a quantifier or an
    alternation (``(a+)+``, ``(a|a)*b``); any unbounded quantifier (``*``, ``+``,
    ``{n,}``, or a bound of 50 or more), because even one (``a*b``) is quadratic on a long run and
    several (``a*a*b``, ``.*x.*y``) are polynomial, and pins match the full block; more than ``MAX_OPTIONAL`` (4) ``?`` or small-bound quantifiers (``a?a?a?...a`` is
    exponential); more than ``MAX_ALTERNATIONS`` (6) ``|``. Literals (``{"literal": ...}``) are
    escaped and never reach this check."""
    if re.search(r"\\[1-9]|\(\?P=|\(\?\(|\(\?[aiLmsu-]*x", pattern):   # (?x): comments hide syntax
        return True
    unbounded = optional = alternations = 0
    stack: list[list[bool]] = []   # enclosing groups' [has_quantifier, has_alternation]
    cur = [False, False]
    in_class = False
    group_opened = False   # the previous character was an unescaped `(`, so a `?` starts `(?...)`
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        opens_group, group_opened = group_opened, False
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
            group_opened = True
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
        elif ch == "?" and not opens_group:
            cur[0] = True
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


def _declared_protocol(request: Mapping[str, Any], allowed: tuple[int, ...]) -> int:
    declared = request.get("protocol", PROTOCOL_VERSION)
    if isinstance(declared, bool) or declared not in allowed:
        raise ProtocolError("bad_protocol")
    return declared


def validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Check a ``compress`` request and return the keyword arguments for ``compress_context``.

    The result holds ``context`` and ``query`` (lone surrogates replaced) and the options, always
    with ``ccr=False``. Raises ``ProtocolError``."""
    if not isinstance(request, Mapping):
        raise ProtocolError("bad_request")
    if set(request) - ALL_FIELDS:
        raise ProtocolError("unknown_field")
    declared = _declared_protocol(request, (1, 2, 3))
    if declared == 1 and (set(request) & V2_FIELDS) - {"protocol"}:
        raise ProtocolError("field_needs_protocol_2")
    if declared <= 2 and set(request) & V3_FIELDS:
        raise ProtocolError("field_needs_protocol_3")
    text, query = request.get("text"), request.get("query", "")
    if not isinstance(text, str):
        raise ProtocolError("bad_text")
    if not isinstance(query, str):
        raise ProtocolError("bad_query")
    selector_query = request.get("selector_query")
    if selector_query is not None and not isinstance(selector_query, str):
        raise ProtocolError("bad_selector_query")
    if "derive_selector_query" in request:
        if not isinstance(request["derive_selector_query"], bool):
            raise ProtocolError("bad_derive_selector_query")
        if selector_query is not None:
            raise ProtocolError("selector_and_derive")
    options: dict[str, Any] = {}
    if "preset" in request:
        preset = request["preset"]
        if not isinstance(preset, str) or preset not in preset_names():
            raise ProtocolError("bad_preset")
        options.update(resolve_preset(preset))
    options.setdefault("strategy", "extract")   # the 1.x worker defaults, under any preset
    options.setdefault("citations", False)
    mode = request.get("mode", options.get("mode", "adaptive"))
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
    if selector_query is not None:
        options["selector_query"] = clean_text(selector_query)[0]
    if "derive_selector_query" in request:
        # Not a compress_context parameter: the worker pops this flag and resolves it into
        # ``selector_query`` from the query parts it holds (transcript.build_selector_query).
        options["derive_selector_query"] = request["derive_selector_query"]
    options["ccr"] = False
    return {"context": clean_text(text)[0], "query": clean_text(query)[0], **options}


def request_was_sanitized(request: Mapping[str, Any]) -> bool:
    """True when ``validate_request`` replaced a lone surrogate in the text, the query or the
    selector query."""
    return any(
        isinstance(request.get(k), str) and _SURROGATE.search(request[k]) is not None
        for k in ("text", "query", "selector_query")
    )


def result_to_dict(result: Any, *, sanitized: bool = False, preset: str | None = None) -> dict[str, Any]:
    """The reply body for a ``compress`` request: the version 1 keys, plus ``result_schema``, the result schema 2
    fields (``confidence_basis``, ``stable_key``, ``dropped``, ``preset``) and the schema 3 field
    ``fact_lines_dropped``. Every v1 key keeps its meaning."""
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
        "fact_lines_dropped": int(getattr(result, "fact_lines_dropped", 0)),
    }


def _integer(value: Any, low: int, high: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise ProtocolError(code)
    return value


def _choice(value: Any, allowed: tuple[str, ...], code: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ProtocolError(code)
    return value


def _bool_field(body: Mapping[str, Any], name: str, code: str) -> bool:
    value = body.get(name)
    if not isinstance(value, bool):
        raise ProtocolError(code)
    return value


def _opt_bool(body: Mapping[str, Any], name: str, default: bool, code: str) -> bool:
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ProtocolError(code)
    return value


def _bounded_text(value: Any, cap: int, code: str) -> str:
    if not isinstance(value, str) or len(value) > cap:
        raise ProtocolError(code)
    return clean_text(value)[0]


def _plan_candidate(body: Any) -> Candidate | None:
    if body is None:
        return None
    if not isinstance(body, Mapping) or set(body) - CANDIDATE_FIELDS:
        raise ProtocolError("bad_candidate")
    confidence = body.get("confidence")
    if confidence is not None:
        confidence = _number(confidence, 0.0, 1.0, "bad_candidate")
    risk = body.get("risk", "high")
    if risk not in RISKS:
        raise ProtocolError("bad_candidate")
    try:
        return Candidate(
            compressed_chars=_integer(body.get("compressed_chars"), 0, MAX_PLAN_TOKENS, "bad_candidate"),
            tokens_saved=_integer(body.get("tokens_saved"), 0, MAX_PLAN_TOKENS, "bad_candidate"),
            confidence=confidence,
            fail_open=_bool_field(body, "fail_open", "bad_candidate"),
            risk=risk,
            fingerprints_ok=_bool_field(body, "fingerprints_ok", "bad_candidate"),
            fact_lines_dropped=_integer(body.get("fact_lines_dropped", 0), 0, MAX_PLAN_TOKENS, "bad_candidate"),
        )
    except (ValueError, TypeError):
        raise ProtocolError("bad_candidate") from None


def _plan_item(body: Any) -> PlanItem:
    if not isinstance(body, Mapping) or set(body) - ITEM_FIELDS:
        raise ProtocolError("bad_item")
    superseded_by = body.get("superseded_by")
    try:
        return PlanItem(
            id=_bounded_text(body.get("id"), MAX_ID_CHARS, "bad_item"),
            position=_integer(body.get("position"), 0, MAX_PLAN_STEPS, "bad_item"),
            tokens=_integer(body.get("tokens"), 0, MAX_PLAN_TOKENS, "bad_item"),
            chars=_integer(body.get("chars"), 0, MAX_PLAN_TOKENS, "bad_item"),
            age_steps=_integer(body.get("age_steps", 0), 0, MAX_PLAN_STEPS, "bad_item"),
            protected=_opt_bool(body, "protected", False, "bad_item"),
            stock_action=_choice(body.get("stock_action", "keep"), STOCK_ACTIONS, "bad_item"),
            stock_kept_chars=_integer(body.get("stock_kept_chars", 0), 0, MAX_PLAN_TOKENS, "bad_item"),
            candidate=_plan_candidate(body.get("candidate")),
            fact_lines=_integer(body.get("fact_lines", 0), 0, MAX_PLAN_TOKENS, "bad_item"),
            superseded_by=None if superseded_by is None
            else _bounded_text(superseded_by, MAX_ID_CHARS, "bad_item"),
            facts_covered_by_successor=_opt_bool(body, "facts_covered_by_successor", False, "bad_item"),
            stratum=_bounded_text(body.get("stratum", "default"), MAX_STRATUM_CHARS, "bad_item"),
        )
    except (ValueError, TypeError):
        raise ProtocolError("bad_item") from None


def _plan_ev(body: Any) -> EVPolicy | None:
    if body is None:
        return None
    if not isinstance(body, Mapping) or set(body) - EV_FIELDS:
        raise ProtocolError("bad_ev")
    price_profile = body.get("price_profile")
    loss_profile = body.get("loss_profile")
    if not isinstance(price_profile, str) or price_profile not in price_profile_names():
        raise ProtocolError("bad_ev")
    if not isinstance(loss_profile, str) or loss_profile not in loss_profile_names():
        raise ProtocolError("bad_ev")
    strength = body.get("strength", "normal")
    if strength not in _EV_STRENGTHS:
        raise ProtocolError("bad_ev")
    try:
        return EVPolicy(
            price_profile=price_profile,
            loss_profile=loss_profile,
            strength=strength,
            quantile=_number(body.get("quantile", 0.5), 1e-9, 1.0, "bad_ev"),
        )
    except (ValueError, TypeError):
        raise ProtocolError("bad_ev") from None


def _plan_policy(body: Any) -> Policy:
    if body is None:
        raise ProtocolError("bad_policy")
    if not isinstance(body, Mapping) or set(body) - PLAN_POLICY_FIELDS:
        raise ProtocolError("bad_policy")
    fields: dict[str, Any] = {}
    try:
        if "min_confidence" in body:
            value = body["min_confidence"]
            fields["min_confidence"] = None if value is None else _number(value, 0.0, 1.0, "bad_policy")
        if "max_risk" in body:
            if body["max_risk"] not in RISKS:
                raise ProtocolError("bad_policy")
            fields["max_risk"] = body["max_risk"]
        if "require_fingerprints" in body:
            fields["require_fingerprints"] = _bool_field(body, "require_fingerprints", "bad_policy")
        if "min_saved_ratio" in body:
            value = body["min_saved_ratio"]
            fields["min_saved_ratio"] = None if value is None else _number(value, 0.0, 1.0, "bad_policy")
        if "min_tokens_saved" in body:
            value = body["min_tokens_saved"]
            fields["min_tokens_saved"] = None if value is None else _integer(value, 0, MAX_PLAN_TOKENS, "bad_policy")
        if "allow_sanitized" in body:
            fields["allow_sanitized"] = _bool_field(body, "allow_sanitized", "bad_policy")
        if "ev" in body:
            fields["ev"] = _plan_ev(body["ev"])
        return Policy(**fields)
    except (ValueError, TypeError):
        raise ProtocolError("bad_policy") from None


def _plan_cache(body: Any) -> CacheState:
    if not isinstance(body, Mapping) or set(body) - CACHE_FIELDS or not {"warm", "n_eff"} <= set(body):
        raise ProtocolError("bad_cache")
    try:
        return CacheState(
            warm=_bool_field(body, "warm", "bad_cache"),
            n_eff=_number(body.get("n_eff"), 0.0, float(MAX_PLAN_STEPS), "bad_cache"),
        )
    except (ValueError, TypeError):
        raise ProtocolError("bad_cache") from None


STATS_FIELDS = frozenset({"id", "op", "protocol"})


def validate_stats_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Check a ``stats`` request (protocol 3, additive). The worker replies ``{"id", "stats"}``
    carrying ``compress_context.cache_stats()``. Raises ``ProtocolError``."""
    if not isinstance(request, Mapping):
        raise ProtocolError("bad_request")
    if set(request) - STATS_FIELDS:
        raise ProtocolError("unknown_field")
    if request.get("op") != "stats":
        raise ProtocolError("bad_op")
    _declared_protocol(request, (3,))
    return {}


def validate_plan_request(request: Mapping[str, Any]) -> PlanInput:
    """Check a ``plan`` request (protocol 3) and return the ``PlanInput``. Raises ``ProtocolError``.

    The body is a closed ``PlanInput`` mirror; ``policy.ev.calibrator`` has no wire form and does not
    exist here."""
    if not isinstance(request, Mapping):
        raise ProtocolError("bad_request")
    if set(request) - PLAN_FIELDS:
        raise ProtocolError("unknown_field")
    _declared_protocol(request, (3,))
    event, host_mode = request.get("event"), request.get("host_mode")
    if event not in EVENTS:
        raise ProtocolError("bad_event")
    if host_mode not in HOST_MODES:
        raise ProtocolError("bad_host_mode")
    items = request.get("items")
    if not isinstance(items, list) or len(items) > MAX_PLAN_ITEMS:
        raise ProtocolError("bad_items")
    steps_since_last_act = request.get("steps_since_last_act")
    steps_to_trigger = request.get("steps_to_trigger")
    try:
        return PlanInput(
            event=event,
            host_mode=host_mode,
            prompt_tokens=_integer(request.get("prompt_tokens"), 0, MAX_PLAN_TOKENS, "bad_prompt_tokens"),
            trigger_tokens=_integer(request.get("trigger_tokens"), 0, MAX_PLAN_TOKENS, "bad_trigger_tokens"),
            items=tuple(_plan_item(item) for item in items),
            cache=_plan_cache(request.get("cache")),
            policy=_plan_policy(request.get("policy")),
            steps_since_last_act=None if steps_since_last_act is None
            else _integer(steps_since_last_act, 0, MAX_PLAN_STEPS, "bad_steps"),
            K=_integer(request.get("K", 3), 0, MAX_PLAN_STEPS, "bad_K"),
            H=_integer(request.get("H", 0), 0, MAX_PLAN_STEPS, "bad_H"),
            steps_to_trigger=None if steps_to_trigger is None
            else _integer(steps_to_trigger, 0, MAX_PLAN_STEPS, "bad_steps"),
            retained_budget_chars=_integer(
                request.get("retained_budget_chars", 0), 0, MAX_PLAN_TOKENS, "bad_retained_budget"
            ),
            growth_tokens_per_step=_number(
                request.get("growth_tokens_per_step", 0), 0.0, MAX_PLAN_TOKENS, "bad_growth"
            ),
            margin_steps=_integer(request.get("margin_steps", 0), 0, MAX_PLAN_STEPS, "bad_steps"),
            replace_compaction=_opt_bool(request, "replace_compaction", False, "bad_replace_compaction"),
        )
    except (ValueError, TypeError):
        raise ProtocolError("bad_plan") from None


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """The reply body for a ``plan`` request: every action with its reason code and EV numbers, plus totals."""
    return {
        "event": plan.event,
        "host_mode": plan.host_mode,
        "acted": bool(plan.acted),
        "gate": plan.gate,
        "actions": [
            {
                "id": action.id,
                "event": action.event,
                "action": action.action,
                "reason": action.reason,
                "p_hat": action.p_hat,
                "V": action.V,
                "L": action.L,
            }
            for action in plan.actions
        ],
        "predicted_chars_after": int(plan.predicted_chars_after),
        "predicted_chars_stock": int(plan.predicted_chars_stock),
        "predicted_V": float(plan.predicted_V),
        "predicted_L": float(plan.predicted_L),
        "reaches_target": bool(plan.reaches_target),
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
        "capabilities": {
            "selector_query": True,
            "plan": {
                "max_items": MAX_PLAN_ITEMS,
                "events": list(EVENTS),
                "host_modes": list(HOST_MODES),
                "actions": list(ACTIONS),
            },
            "ev": {
                "strengths": list(_EV_STRENGTHS),
                "price_profiles": price_profile_names(),
                "loss_profiles": loss_profile_names(),
            },
        },
    }
