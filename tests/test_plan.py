"""1.10.0 plan(): pure prune/compact planner over precomputed candidates (interface layer)."""
from __future__ import annotations

import random
import re
import time
from dataclasses import replace
from pathlib import Path

import pytest

import tameru.plan as plan_mod
from tameru.decide import EVPolicy, Policy
from tameru.plan import (
    ACTIONS, EVENTS, CacheState, Candidate, PlanInput, PlanItem, plan,
)

EV = EVPolicy("deepseek-v4-pro", "replay-2026-11-21")
EV_POLICY = Policy(ev=EV)
# A high-V candidate: saved 50_000 at n_eff 80 clears the suffix-rewrite term comfortably.
GOOD = Candidate(compressed_chars=2000, tokens_saved=50_000, confidence=0.99, fail_open=False,
                 risk="low", fingerprints_ok=True)


def item(i, *, stock_action="cut", candidate=GOOD, fact_lines=0, chars=40_000, tokens=10_000,
         position=None, age_steps=0, protected=False, stock_kept_chars=3000,
         superseded_by=None, facts_covered_by_successor=False, stratum="default"):
    return PlanItem(id=f"i{i}", position=i if position is None else position, tokens=tokens,
                    chars=chars, age_steps=age_steps, protected=protected, stock_action=stock_action,
                    stock_kept_chars=stock_kept_chars, candidate=candidate, fact_lines=fact_lines,
                    superseded_by=superseded_by, facts_covered_by_successor=facts_covered_by_successor,
                    stratum=stratum)


def inp(items, *, event="trigger", host_mode="prune", warm=False, n_eff=80,
        steps_since_last_act=None, K=3, H=0, steps_to_trigger=None, retained_budget_chars=0,
        prompt_tokens=200_000, trigger_tokens=180_000, growth_tokens_per_step=0.0,
        margin_steps=0, policy=EV_POLICY):
    return PlanInput(event=event, host_mode=host_mode, prompt_tokens=prompt_tokens,
                     trigger_tokens=trigger_tokens,
                     items=tuple(items), cache=CacheState(warm=warm, n_eff=n_eff), policy=policy,
                     steps_since_last_act=steps_since_last_act, K=K, H=H,
                     steps_to_trigger=steps_to_trigger, retained_budget_chars=retained_budget_chars,
                     growth_tokens_per_step=growth_tokens_per_step, margin_steps=margin_steps)


def by_id(p):
    return {a.id: a for a in p.actions}


# --- gating -----------------------------------------------------------------

def test_broken_events_act():
    for event in ("trigger", "cache_cold", "prefix_rewritten"):
        p = plan(inp([item(0)], event=event))
        assert p.acted and p.gate == "acted"
        assert all(a.event == event for a in p.actions)


def test_warm_step_does_not_act_without_forecast():
    for kw in ({}, {"steps_to_trigger": 0}, {"H": 4}):
        p = plan(inp([item(0)], event="step", warm=True, **kw))
        assert not p.acted and p.gate == "no_forecast"
        assert all(a.action == "keep" for a in p.actions)


def test_forecast_hook_acts_inside_horizon_only():
    items = [item(0, stock_action="demote")]
    kw = dict(event="step", host_mode="compact", warm=True, H=4, steps_to_trigger=None,
              prompt_tokens=100_000, trigger_tokens=180_000, growth_tokens_per_step=1000,
              retained_budget_chars=50_000)
    assert not plan(inp(items, **{**kw, "steps_to_trigger": 5})).acted
    p = plan(inp(items, **{**kw, "steps_to_trigger": 4}))
    assert p.acted and p.gate == "acted" and all(a.event == "step" for a in p.actions)


def test_warm_step_runway_boundary():
    # after the act the plan must leave H + margin_steps of runway:
    # (trigger - projected_after) / growth >= H + margin_steps
    demote = item(0, stock_action="demote")     # extract keeps 2000 of 40_000 chars: saved ≈ 9500 tokens
    kw = dict(event="step", host_mode="compact", warm=True, H=4, margin_steps=6,
              steps_to_trigger=4, growth_tokens_per_step=1000, retained_budget_chars=50_000,
              prompt_tokens=100_000)
    p = plan(inp([demote], trigger_tokens=180_000, **kw))     # after ≈ 90_500 → runway 89.5 ≥ 10
    assert p.acted and p.actions[0].action == "extract"
    p = plan(inp([demote], trigger_tokens=95_000, **kw))      # runway 4.5 < 10
    assert not p.acted and p.gate == "no_runway"
    assert all(a.action == "keep" and a.reason == "no_runway" for a in p.actions)


def test_warm_step_never_acts_without_growth_or_in_prune_mode():
    demote = item(0, stock_action="demote")
    kw = dict(event="step", warm=True, H=4, steps_to_trigger=4, margin_steps=0,
              prompt_tokens=100_000, trigger_tokens=180_000, retained_budget_chars=50_000)
    # growth 0: no runway estimate, no act
    p = plan(inp([demote], host_mode="compact", **kw))
    assert not p.acted and p.gate == "no_runway"
    # prune mode has no stock cut set on a warm step: no act, even with growth
    p = plan(inp([item(0)], host_mode="prune", growth_tokens_per_step=1000, **kw))
    assert not p.acted and p.gate == "no_runway"


def test_hysteresis_blocks_non_trigger_events():
    items = [item(0)]
    for event in ("cache_cold", "prefix_rewritten"):
        assert plan(inp(items, event=event, steps_since_last_act=2)).gate == "hysteresis"
        assert plan(inp(items, event=event, steps_since_last_act=3)).acted
    # the trigger overrides hysteresis
    assert plan(inp(items, event="trigger", steps_since_last_act=0)).acted
    # the forecast step respects it too
    p = inp(items, event="step", warm=True, H=4, steps_to_trigger=1, steps_since_last_act=1)
    assert plan(p).gate == "hysteresis"


def test_event_carried_on_every_action():
    p = plan(inp([item(0), item(1, stock_action="keep")], event="cache_cold"))
    assert {a.event for a in p.actions} == {"cache_cold"}


def test_input_validation():
    with pytest.raises(ValueError):
        plan(inp([item(0)], event="bang"))
    with pytest.raises(ValueError):
        plan(inp([item(0)], host_mode="delete"))
    with pytest.raises(ValueError):
        PlanItem(id="x", position=0, tokens=1, chars=1, stock_action="explode")


# --- prune mode -------------------------------------------------------------

def test_prune_covers_every_cut_item():
    cands = [GOOD, None,
             replace(GOOD, fail_open=True),
             replace(GOOD, compressed_chars=999_999)]
    items = [item(i, candidate=c) for i, c in enumerate(cands)]
    p = plan(inp(items))
    acts = by_id(p)
    assert acts["i0"].action == "extract"
    assert acts["i1"].action == "stub" and acts["i1"].reason == "no_candidate"
    assert acts["i2"].action == "stub" and acts["i2"].reason == "fail_open"
    assert acts["i3"].action == "stub" and acts["i3"].reason == "longer_than_stock_cut"


def test_prune_never_touches_non_cut_items():
    items = [item(0), item(1, stock_action="keep"), item(2, stock_action="demote"),
             item(3, protected=True)]
    acts = by_id(plan(inp(items)))
    assert acts["i1"].action == "keep" and acts["i1"].reason == "not_cut"
    assert acts["i2"].action == "keep"
    assert acts["i3"].action == "keep" and acts["i3"].reason == "protected"


def test_prune_chars_after_never_exceeds_stock():
    rng = random.Random(20261121)
    for _ in range(50):
        items = [
            item(i, stock_action=rng.choice(["keep", "cut", "demote"]),
                 candidate=(None if rng.random() < 0.3 else
                            replace(GOOD, compressed_chars=rng.randrange(500, 50_000),
                                    tokens_saved=rng.randrange(0, 60_000),
                                    confidence=rng.random(), fail_open=rng.random() < 0.1)),
                 chars=rng.randrange(1_000, 80_000), tokens=rng.randrange(500, 20_000),
                 stock_kept_chars=rng.randrange(200, 8_000))
            for i in range(30)
        ]
        p = plan(inp(items))
        cut = [a for a in p.actions if next(i for i in items if i.id == a.id).stock_action == "cut"]
        assert all(a.action in ("extract", "stub") for a in cut)       # no uncovered cut item
        assert all(a.action == "keep" for a in p.actions
                   if next(i for i in items if i.id == a.id).stock_action != "cut")
        assert p.predicted_chars_after <= p.predicted_chars_stock


def test_warm_step_ev_decline_falls_back_to_brief():
    # on a warm forecast step the rewrite prices the suffix after the item: V goes negative
    weak = replace(GOOD, tokens_saved=10_000, confidence=0.99)
    items = [item(0, stock_action="demote", candidate=weak), item(1, stock_action="keep", tokens=50_000)]
    p = plan(inp(items, event="step", host_mode="compact", warm=True, H=4, steps_to_trigger=1,
                 prompt_tokens=60_000, trigger_tokens=180_000, growth_tokens_per_step=1000,
                 retained_budget_chars=50_000))
    a = p.actions[0]
    assert a.action == "brief" and a.reason == "negative_ev"
    assert a.p_hat is not None and a.V is not None and a.V < 0 and a.L is not None
    # the same item at a cache-broken event pays back: S = 0
    p = plan(inp(items, event="trigger", host_mode="compact", warm=True,
                 retained_budget_chars=50_000))
    assert p.actions[0].action == "extract" and p.actions[0].reason == "ok"


def test_plan_totals():
    p = plan(inp([item(0), item(1)]))
    assert p.predicted_chars_after == 2 * GOOD.compressed_chars
    assert p.predicted_chars_stock == 2 * 3000
    assert p.predicted_V > 0 and p.predicted_L > 0


# --- compact mode -----------------------------------------------------------

def compact(items, budget=10_000, **kw):
    return plan(inp(items, host_mode="compact", retained_budget_chars=budget, **kw))


def test_compact_fact_rows_win_the_budget():
    # budget fits exactly one extract; the fact row must get it even though it is older
    fact = item(0, stock_action="demote", fact_lines=3, age_steps=40)
    plain = item(1, stock_action="demote", age_steps=1)
    p = compact([plain, fact], budget=GOOD.compressed_chars)
    acts = by_id(p)
    assert acts["i0"].action == "extract" and acts["i1"].action == "brief"


def test_compact_orders_by_ev_per_char_then_recency():
    # no fact rows: the higher EV-per-char candidate wins, then the newer item
    rich = item(0, stock_action="demote", candidate=replace(GOOD, tokens_saved=55_000), age_steps=9)
    poor = item(1, stock_action="demote", candidate=replace(GOOD, tokens_saved=40_000), age_steps=1)
    p = compact([rich, poor], budget=GOOD.compressed_chars)
    assert by_id(p)["i0"].action == "extract" and by_id(p)["i1"].action == "brief"
    same = replace(GOOD, tokens_saved=50_000)
    newer = item(2, stock_action="demote", candidate=same, age_steps=1)
    older = item(3, stock_action="demote", candidate=same, age_steps=9)
    p = compact([older, newer], budget=GOOD.compressed_chars)
    assert by_id(p)["i2"].action == "extract" and by_id(p)["i3"].action == "brief"


def test_compact_supersession_needs_fact_coverage():
    covered = item(0, stock_action="demote", superseded_by="i9", facts_covered_by_successor=True,
                   fact_lines=5)
    uncovered = item(1, stock_action="demote", superseded_by="i9", facts_covered_by_successor=False)
    p = compact([covered, uncovered], budget=10_000)
    acts = by_id(p)
    assert acts["i0"].action == "superseded" and acts["i0"].reason == "superseded_by:i9"
    assert acts["i1"].action in ("extract", "brief")  # no coverage: it competes normally


def test_compact_header_when_candidate_fails_veto():
    bad = item(0, stock_action="demote", candidate=replace(GOOD, fail_open=True))
    none = item(1, stock_action="demote", candidate=None)
    p = compact([bad, none], budget=10_000)
    acts = by_id(p)
    assert acts["i0"].action == "header" and acts["i0"].reason == "fail_open"
    assert acts["i1"].action == "header" and acts["i1"].reason == "no_candidate"


def test_compact_non_demote_items_untouched():
    p = compact([item(0, stock_action="keep"), item(1, protected=True, stock_action="demote")],
                budget=10_000)
    assert all(a.action == "keep" for a in p.actions)


# --- determinism and performance --------------------------------------------

def big_items(n, seed=7):
    rng = random.Random(seed)
    return [
        item(i, stock_action=rng.choice(["keep", "cut", "demote", "demote"]),
             candidate=(None if rng.random() < 0.2 else
                        replace(GOOD, compressed_chars=rng.randrange(500, 20_000),
                                tokens_saved=rng.randrange(0, 60_000),
                                confidence=rng.random())),
             fact_lines=rng.randrange(0, 6), chars=rng.randrange(1_000, 80_000),
             tokens=rng.randrange(500, 20_000), age_steps=rng.randrange(0, 200),
             stock_kept_chars=rng.randrange(200, 4_000))
        for i in range(n)
    ]


def test_plan_is_deterministic():
    items = big_items(200)
    a = plan(inp(items, host_mode="compact", retained_budget_chars=100_000))
    b = plan(inp(items, host_mode="compact", retained_budget_chars=100_000))
    assert a == b
    assert plan(inp(items)) == plan(inp(items))


def test_plan_p95_at_1000_items():
    items = big_items(1_000)
    inps = [inp(items, host_mode="compact", retained_budget_chars=200_000), inp(items)]
    times = []
    for _ in range(60):
        for x in inps:
            t0 = time.perf_counter()
            plan(x)
            times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    print(f"\nplan() p95 at 1000 items: {p95:.2f} ms (median {times[len(times)//2]:.2f} ms)")
    assert p95 <= 20.0


# --- no host constants ------------------------------------------------------

def test_plan_py_holds_no_host_constants():
    src = Path(plan_mod.__file__).read_text(encoding="utf-8")
    # DeepSeek trigger formula and Hermes ladder constants must never appear in the planner
    for token in ("8000", "65536", "0.8", "8192", "0.60", "0.85", "0.15"):
        assert not re.search(rf"(?<![\d.]){re.escape(token)}(?![\d])", src), token


def test_action_and_event_vocabularies_are_closed():
    assert set(EVENTS) == {"trigger", "cache_cold", "prefix_rewritten", "step"}
    assert set(ACTIONS) == {"keep", "extract", "stub", "brief", "header", "superseded"}
