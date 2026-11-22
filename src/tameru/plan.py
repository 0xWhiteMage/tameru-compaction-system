"""Pure prune/compact planner (1.10.0 interface layer; no measured claim yet).

``plan(PlanInput) -> Plan`` decides, for one moment, what every item becomes. It is pure: no I/O, no clock,
deterministic, O(n log n) in the item count, and it holds no host numbers — the trigger formulas and the stock
behaviour (which items the host would cut or demote, and how much of each it keeps) arrive as inputs.

Two modes. ``prune``: at a cache-broken event every stock-cut item is covered — ``extract`` when the precomputed
engine candidate passes the hard vetoes and the EV rule and fits the stock cut, else ``stub`` (a stock-equivalent
cut the adapter renders); non-cut items are never touched. ``compact``: the retained budget is allocated over the
stock-demote set by fact rows first, then EV per retained character, then recency — not newest-first by position.
Supersession commits only when the successor covers the item's facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .decide import EVPolicy, Policy, decide, ev_terms

EVENTS = ("trigger", "cache_cold", "prefix_rewritten", "step")
"""Moments a plan may be asked for. The first three are cache-broken: the suffix is rewritten anyway."""
BROKEN_EVENTS = ("trigger", "cache_cold", "prefix_rewritten")
HOST_MODES = ("prune", "compact")
ACTIONS = ("keep", "extract", "stub", "brief", "header", "superseded")
STOCK_ACTIONS = ("keep", "cut", "demote")
GATES = ("acted", "not_trigger_step", "no_forecast", "hysteresis", "no_runway")
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Candidate:
    """The engine result for one item, precomputed by the caller (no compression happens inside ``plan``)."""

    compressed_chars: int
    tokens_saved: int
    confidence: float | None
    fail_open: bool
    risk: str
    fingerprints_ok: bool                 # every error fingerprint of the original survives the extract
    fact_lines_dropped: int = 0


@dataclass(frozen=True)
class PlanItem:
    """One candidate item: its identity, cost, stock fate and (optional) engine candidate."""

    id: str
    position: int                         # place in the prompt; a rewrite at p rewrites everything after p
    tokens: int
    chars: int
    age_steps: int = 0                    # steps since the item arrived (smaller = newer)
    protected: bool = False               # a host-level keep; never rewritten by a plan
    stock_action: str = "keep"            # what the stock mechanism would do to this item
    stock_kept_chars: int = 0             # chars the stock action leaves of this item
    candidate: Candidate | None = None
    fact_lines: int = 0                   # fact-shaped lines this item holds
    superseded_by: str | None = None      # id of a later item that makes this one stale
    facts_covered_by_successor: bool = False  # the superseding item carries this item's facts
    stratum: str = "default"

    def __post_init__(self) -> None:
        if self.stock_action not in STOCK_ACTIONS:
            raise ValueError(f"stock_action must be one of {STOCK_ACTIONS}")


@dataclass(frozen=True)
class CacheState:
    warm: bool                            # the provider prefix cache is currently warm
    n_eff: float                          # later requests the cache is expected to serve


@dataclass(frozen=True)
class PlanInput:
    """Everything a plan needs; the caller computes trigger formulas, stock actions and candidates."""

    event: str                            # one of EVENTS
    host_mode: str                        # one of HOST_MODES
    prompt_tokens: int
    trigger_tokens: int
    items: tuple[PlanItem, ...]
    cache: CacheState
    policy: Policy                        # acceptance rule; its ``ev`` field selects the EV check
    steps_since_last_act: int | None = None
    K: int = 3                            # hysteresis: steps a non-trigger act must wait after the last act
    H: int = 0                            # forecast horizon in steps; 0 disables acting on warm steps
    steps_to_trigger: int | None = None   # the caller's distance estimate; the forecast hook compares it to H
    retained_budget_chars: int = 0        # compact mode: body chars the demoted set may keep in all
    growth_tokens_per_step: float = 0.0   # mean tokens the prompt adds per step; 0 disables warm acts
    margin_steps: int = 0                 # extra runway steps the act must leave beyond H
    replace_compaction: bool = False      # compact+trigger: aim the prune at trigger − growth × margin


@dataclass(frozen=True)
class PlanAction:
    """The plan for one item. ``p_hat``, ``V`` and ``L`` are filled when the EV check ran for it."""

    id: str
    event: str
    action: str                           # one of ACTIONS
    reason: str
    p_hat: float | None = None
    V: float | None = None
    L: float | None = None


@dataclass(frozen=True)
class Plan:
    """Per-item actions plus totals. ``gate`` says why the pass acted or stood down."""

    event: str
    host_mode: str
    acted: bool
    gate: str                             # one of GATES
    actions: tuple[PlanAction, ...]
    predicted_chars_after: int
    predicted_chars_stock: int
    predicted_V: float
    predicted_L: float
    reaches_target: bool = False          # replace_compaction only: the prune alone meets the runway target


def _veto(item: PlanItem, policy: Policy) -> str | None:
    """The hard vetoes on ``item.candidate``, in decide()'s order; the reason code or None."""
    c = item.candidate
    if c is None:
        return "no_candidate"
    if c.fail_open:
        return "fail_open"
    if _RISK_ORDER.get(c.risk or "", 2) > _RISK_ORDER[policy.max_risk]:
        return "risk"
    if policy.require_fingerprints and not c.fingerprints_ok:
        return "lost_fingerprint"
    return None


def _evaluate(item: PlanItem, policy: Policy, *, n_eff: float, suffix_tokens: float, cache_broken: bool):
    """The decision and the EV terms for one item with a veto-clean candidate, via ``decide``."""
    c = item.candidate
    result = SimpleNamespace(
        compressed_text="", fail_open=c.fail_open, compression_risk=c.risk, confidence=c.confidence,
        fact_lines_dropped=c.fact_lines_dropped, tokens_saved=c.tokens_saved,
        original_tokens=item.tokens, kept_tokens=item.tokens - c.tokens_saved,
    )
    if policy.ev is not None:
        terms = ev_terms(result, policy.ev, c.tokens_saved, n_eff=n_eff, suffix_tokens=suffix_tokens,
                         item_tokens=item.tokens, cache_broken=cache_broken)
        if terms is None:
            return "low_confidence", (None, None, None)
        p_hat, V, L = terms
        if p_hat * V - (1 - p_hat) * L <= 0:
            return "negative_ev", (p_hat, V, L)
        return "ok", (p_hat, V, L)
    # no EV policy: the configured numeric gates decide (confidence included). The fingerprint veto
    # already ran on c.fingerprints_ok, so the recheck passes an empty wanted set.
    verdict = decide(result, policy, fingerprints={})
    if not verdict.accept:
        return verdict.reason, (None, None, None)
    return "ok", (None, None, None)


def _gate(inp: PlanInput) -> str | None:
    """Why the pass must not act, or None when it may."""
    if inp.event in BROKEN_EVENTS:
        if inp.event != "trigger" and inp.steps_since_last_act is not None and inp.steps_since_last_act < inp.K:
            return "hysteresis"
        return None
    # a warm step: act only inside the forecast horizon
    if inp.H <= 0 or inp.steps_to_trigger is None or inp.steps_to_trigger > inp.H:
        return "no_forecast"
    if inp.steps_since_last_act is not None and inp.steps_since_last_act < inp.K:
        return "hysteresis"
    return None


def _stand_down(inp: PlanInput, gate: str) -> Plan:
    """The keep-everything plan for a moment the pass must not act on."""
    actions = tuple(PlanAction(i.id, inp.event, "keep", gate) for i in inp.items)
    return Plan(inp.event, inp.host_mode, False, gate, actions,
                sum(i.chars for i in inp.items), _stock_chars(inp.items, inp.host_mode), 0.0, 0.0)


def _projected_tokens_after(inp: PlanInput, planned: Plan) -> float:
    """Prompt tokens after the plan commits: every rewritten item keeps the token share its
    kept characters imply (extracts their compressed size, other rungs the stock remnant)."""
    saved = 0.0
    for item, action in zip(inp.items, planned.actions):
        if item.chars <= 0:
            continue
        if action.action == "extract":
            kept = item.candidate.compressed_chars
        elif action.action == "keep":
            kept = item.chars
        else:
            kept = min(item.stock_kept_chars, item.chars)
        saved += item.tokens * (1.0 - kept / item.chars)
    return inp.prompt_tokens - saved


def plan(inp: PlanInput) -> Plan:
    """Plan one moment. Deterministic: the same input always yields the same plan."""
    if inp.event not in EVENTS:
        raise ValueError(f"event must be one of {EVENTS}")
    if inp.host_mode not in HOST_MODES:
        raise ValueError(f"host_mode must be one of {HOST_MODES}")
    gate = _gate(inp)
    if gate is not None:
        return _stand_down(inp, gate)
    if inp.event == "step":
        # A warm forecast act needs a stock-demote set (compact) and a growth estimate, and it
        # must leave H + margin_steps of runway after committing; prune mode has no warm act.
        if inp.host_mode != "compact" or inp.growth_tokens_per_step <= 0:
            return _stand_down(inp, "no_runway")
        planned = _plan_compact(inp)
        after = _projected_tokens_after(inp, planned)
        runway = (inp.trigger_tokens - after) / inp.growth_tokens_per_step
        if runway < inp.H + inp.margin_steps:
            return _stand_down(inp, "no_runway")
        return planned
    if inp.host_mode == "prune":
        return _plan_prune(inp)
    if inp.event == "trigger" and inp.replace_compaction:
        return _plan_compact_replace(inp)
    return _plan_compact(inp)


def _stock_chars(items: tuple[PlanItem, ...], host_mode: str) -> int:
    """Total chars stock leaves in this mode: items the stock action touches shrink to
    ``stock_kept_chars`` (``cut`` under prune, ``demote`` under compact), the rest stay whole."""
    touched = "cut" if host_mode == "prune" else "demote"
    return sum(min(i.stock_kept_chars, i.chars) if i.stock_action == touched else i.chars
               for i in items)


def _suffix_after(items: tuple[PlanItem, ...]) -> dict[str, float]:
    """Suffix tokens each position rewrites: the tokens of every item after it, in prompt order."""
    ordered = sorted(items, key=lambda i: i.position)
    suffix: dict[str, float] = {}
    running = 0.0
    for item in reversed(ordered):
        suffix[item.id] = running
        running += item.tokens
    return suffix


def _plan_prune(inp: PlanInput) -> Plan:
    """Every stock-cut item is covered: an accepted, stock-sized extract, else a stub."""
    cache_broken = inp.event in BROKEN_EVENTS or not inp.cache.warm
    suffix = _suffix_after(inp.items)
    actions: list[PlanAction] = []
    chars_after = 0
    V_total = L_total = 0.0
    for item in inp.items:
        if item.protected or item.stock_action != "cut":
            chars_after += item.chars
            actions.append(PlanAction(item.id, inp.event, "keep", "protected" if item.protected else "not_cut"))
            continue
        c = item.candidate
        stub_chars = min(item.stock_kept_chars, item.chars)
        veto = _veto(item, inp.policy)
        if veto is not None:
            chars_after += stub_chars
            actions.append(PlanAction(item.id, inp.event, "stub", veto))
            continue
        S = 0.0 if cache_broken else suffix[item.id]
        verdict, (p_hat, V, L) = _evaluate(item, inp.policy, n_eff=inp.cache.n_eff, suffix_tokens=S,
                                           cache_broken=cache_broken)
        if V is not None:
            V_total += V
            L_total += L or 0.0
        if verdict == "ok" and c.compressed_chars <= item.stock_kept_chars:
            chars_after += c.compressed_chars
            actions.append(PlanAction(item.id, inp.event, "extract", "ok", p_hat, V, L))
            continue
        chars_after += stub_chars
        actions.append(PlanAction(item.id, inp.event, "stub",
                                  verdict if verdict != "ok" else "longer_than_stock_cut", p_hat, V, L))
    return Plan(inp.event, inp.host_mode, True, "acted", tuple(actions), chars_after,
                _stock_chars(inp.items, inp.host_mode), V_total, L_total)


def _score_demote(inp: PlanInput):
    """Veto- and EV-score every demote candidate; returns (scored, demote). ``scored`` maps item id
    to ``(verdict, ev_per_char, p_hat, V, L)`` for candidates that passed the hard vetoes."""
    cache_broken = inp.event in BROKEN_EVENTS or not inp.cache.warm
    suffix = _suffix_after(inp.items)
    scored: dict[str, tuple[str, float, float | None, float | None, float | None]] = {}
    demote: list[PlanItem] = []
    for item in inp.items:
        if item.protected or item.stock_action != "demote":
            continue
        demote.append(item)
        if item.candidate is None or _veto(item, inp.policy) is not None:
            continue
        S = 0.0 if cache_broken else suffix[item.id]
        verdict, (p_hat, V, L) = _evaluate(item, inp.policy, n_eff=inp.cache.n_eff, suffix_tokens=S,
                                           cache_broken=cache_broken)
        scored[item.id] = (verdict, (p_hat * V - (1 - p_hat) * L) / max(1, item.candidate.compressed_chars)
                           if p_hat is not None else float("-inf"), p_hat, V, L)
    return scored, demote


def _demote_rank(scored):
    """The compact-mode grant order: fact rows first, then EV per retained character, then recency
    (newest first), then position for determinism."""
    def rank(item: PlanItem) -> tuple:
        entry = scored.get(item.id)
        ev_per_char = entry[1] if entry else float("-inf")
        return (-(item.fact_lines > 0), -ev_per_char, item.age_steps, item.position, item.id)

    return rank


def _assemble_compact(inp: PlanInput, decisions: dict[str, PlanAction], *, reaches_target: bool = False) -> Plan:
    """Turn per-item compact decisions into a ``Plan``: ``keep`` for untouched items, kept chars by rung."""
    actions: list[PlanAction] = []
    chars_after = 0
    V_total = L_total = 0.0
    for item in inp.items:
        action = decisions.get(item.id)
        if action is None:
            chars_after += item.chars
            actions.append(PlanAction(item.id, inp.event, "keep",
                                      "protected" if item.protected else "not_demote"))
            continue
        if action.action == "extract":
            chars_after += item.candidate.compressed_chars
        else:
            chars_after += min(item.stock_kept_chars, item.chars)
        if action.V is not None:
            V_total += action.V
            L_total += action.L or 0.0
        actions.append(action)
    return Plan(inp.event, inp.host_mode, True, "acted", tuple(actions), chars_after,
                _stock_chars(inp.items, inp.host_mode), V_total, L_total, reaches_target)


def _plan_compact_replace(inp: PlanInput) -> Plan:
    """Compact-mode trigger with ``replace_compaction``: grant extracts in the usual rank order only
    while the projected prompt stays under ``trigger_tokens − growth × margin_steps``. Everything a
    demote item cannot fund drops to ``header``. When the target is unreachable even with every
    demotable row at its header remnant, fall back to the normal allocation with
    ``reaches_target = False``."""
    scored, demote = _score_demote(inp)
    ordered = sorted(demote, key=_demote_rank(scored))
    target = inp.trigger_tokens - inp.growth_tokens_per_step * inp.margin_steps

    # Floor: the projected prompt when every demotable row falls to its stock remnant.
    floor_after = float(inp.prompt_tokens)
    for item in ordered:
        if item.chars > 0:
            floor_after -= item.tokens * (1.0 - min(item.stock_kept_chars, item.chars) / item.chars)
    if floor_after > target:
        return _plan_compact(inp)

    slack = target - floor_after           # tokens the extracts may cost back over the remnant
    room = inp.retained_budget_chars       # the host's retained-budget cap still applies
    decisions: dict[str, PlanAction] = {}
    for item in ordered:
        if item.superseded_by is not None and item.facts_covered_by_successor:
            decisions[item.id] = PlanAction(item.id, inp.event, "superseded",
                                            f"superseded_by:{item.superseded_by}")
            continue
        entry = scored.get(item.id)
        if entry is None:
            decisions[item.id] = PlanAction(item.id, inp.event, "header",
                                            _veto(item, inp.policy) or "no_candidate")
            continue
        verdict, _epc, p_hat, V, L = entry
        kept = min(item.stock_kept_chars, item.chars)
        cost = (item.tokens * max(0, item.candidate.compressed_chars - kept) / item.chars
                if item.chars > 0 else 0.0)
        if verdict == "ok" and item.candidate.compressed_chars <= room and cost <= slack:
            room -= item.candidate.compressed_chars
            slack -= cost
            decisions[item.id] = PlanAction(item.id, inp.event, "extract", "ok", p_hat, V, L)
        elif verdict == "ok":
            reason = "over_budget" if item.candidate.compressed_chars > room else "no_runway"
            decisions[item.id] = PlanAction(item.id, inp.event, "header", reason, p_hat, V, L)
        else:
            decisions[item.id] = PlanAction(item.id, inp.event, "header", verdict, p_hat, V, L)
    return _assemble_compact(inp, decisions, reaches_target=True)


def _plan_compact(inp: PlanInput, *, reaches_target: bool = False) -> Plan:
    """Allocate ``retained_budget_chars`` over the stock-demote set.

    Order: fact rows first, then expected value per retained character, then recency (newest first),
    then position for determinism. An item takes ``extract`` when its candidate passes the vetoes and
    the EV rule and its compressed form fits the budget left; ``brief`` when the candidate is clean but
    loses on EV or fit; ``header`` otherwise. ``superseded`` requires the successor to cover the facts.
    """
    scored, demote = _score_demote(inp)
    rank = _demote_rank(scored)

    room = inp.retained_budget_chars
    decisions: dict[str, PlanAction] = {}
    for item in sorted(demote, key=rank):
        if item.superseded_by is not None and item.facts_covered_by_successor:
            decisions[item.id] = PlanAction(item.id, inp.event, "superseded", f"superseded_by:{item.superseded_by}")
            continue
        entry = scored.get(item.id)
        if entry is None:
            decisions[item.id] = PlanAction(item.id, inp.event, "header",
                                            _veto(item, inp.policy) or "no_candidate")
            continue
        verdict, _epc, p_hat, V, L = entry
        if verdict == "ok" and item.candidate.compressed_chars <= room:
            room -= item.candidate.compressed_chars
            decisions[item.id] = PlanAction(item.id, inp.event, "extract", "ok", p_hat, V, L)
        elif verdict == "ok":
            decisions[item.id] = PlanAction(item.id, inp.event, "brief", "over_budget", p_hat, V, L)
        else:
            decisions[item.id] = PlanAction(item.id, inp.event, "brief", verdict, p_hat, V, L)

    return _assemble_compact(inp, decisions, reaches_target=reaches_target)
