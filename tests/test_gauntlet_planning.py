from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tameru import loss, markers, presets, prices
from tameru.decide import EVPolicy, Policy, decide, ev_terms
from tameru.gap_kind import gap_accepts_kind
from tameru.plan import CacheState, Candidate, PlanInput, PlanItem, plan


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1])
def test_ev_rejects_invalid_probability_before_capping(confidence):
    assert ev_terms(result(confidence=confidence, fact_lines_dropped=1), EV, 900,
                    n_eff=80, suffix_tokens=0, item_tokens=1000) is None


@pytest.mark.parametrize("calibrator", [lambda r: "invalid", lambda r: 1 / 0])
def test_ev_calibrator_failure_declines(calibrator):
    assert ev_terms(result(), replace(EV, calibrator=calibrator), 900,
                    n_eff=80, suffix_tokens=0, item_tokens=1000) is None


@pytest.mark.parametrize("field", ["saved_tokens", "n_eff", "suffix_tokens", "item_tokens"])
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "bad", None])
def test_ev_invalid_costs_decline(field, value):
    costs = dict(saved_tokens=900, n_eff=80, suffix_tokens=0, item_tokens=1000)
    costs[field] = value
    assert ev_terms(result(), EV, **costs) is None


def test_ev_overflow_declines():
    assert ev_terms(result(), EV, 1e308, n_eff=1e308,
                    suffix_tokens=0, item_tokens=1000) is None


def test_policy_normalizes_numeric_thresholds():
    policy = Policy(min_confidence="0.7", min_saved_ratio="0.1")
    assert decide(result(), policy).accept
    assert policy.min_confidence == 0.7 and policy.min_saved_ratio == 0.1


@pytest.mark.parametrize("value", [0.5, -0.5, True, "1"])
def test_policy_token_threshold_is_integral(value):
    with pytest.raises(ValueError):
        Policy(min_tokens_saved=value)


def test_ev_quantile_is_normalized():
    assert replace(EV, quantile="0.5").quantile == 0.5
    with pytest.raises(ValueError):
        replace(EV, quantile=float("nan"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 10 ** 1000])
def test_loss_rejects_nonfinite_values(value):
    with pytest.raises(ValueError):
        loss._number("test", "lambda_base", {"lambda_base": {"value": value}})


def test_loss_rejects_boolean_numbers():
    with pytest.raises(ValueError):
        loss._number("test", "p_needed", {"p_needed": {"value": True}})


def loss_raw():
    return {"date": "2026-11-21", "values": {
        key: {"value": value} for key, value in
        dict(p_needed=0.25, p_recovered=0.9, recovery_output_tokens=200,
             lambda_base=100).items()},
        "strength_multipliers": {"normal": {"value": 1}}}


def test_loss_rejects_fractional_recovery_tokens():
    raw = loss_raw()
    raw["values"]["recovery_output_tokens"]["value"] = 1.5
    with pytest.raises(ValueError):
        loss._build("test", raw)
    assert loss._build("test", loss_raw()).recovery_output_tokens == 200


def price_raw():
    return {"provider": "test", "date": "2026-11-21", "relative": {"r": 0.1, "w": 1.0}}


@pytest.mark.parametrize("r,w", [(0.1, float("inf")), (float("inf"), float("inf"))])
def test_prices_reject_infinite_cache_prices(r, w):
    raw = price_raw()
    raw["relative"].update(r=r, w=w)
    with pytest.raises(ValueError):
        prices._build("test", raw)


@pytest.mark.parametrize("field", ["o", "ttl_s", "peak_multiplier"])
@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf")])
def test_prices_reject_invalid_optional_figures(field, value):
    raw = price_raw()
    (raw["relative"] if field == "o" else raw)[field] = value
    with pytest.raises(ValueError):
        prices._build("test", raw)
    assert prices._build("test", price_raw()).o is None


def test_price_tiers_need_not_be_sorted():
    profile = replace(prices.profile("deepseek-v4-pro"), tiers=(
        prices.Tier(200, 3), prices.Tier(100, 2)))
    assert profile.tier_multiplier(201) == 3
    assert profile.tier_multiplier(200) == 2
    assert profile.tier_multiplier(100) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_required_share_rejects_nonfinite_forecasts(value):
    with pytest.raises(ValueError):
        prices.required_share(prices.profile("deepseek-v4-pro"), value)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_implied_requests_rejects_nonfinite_share(value):
    with pytest.raises(ValueError):
        prices.implied_later_requests(prices.profile("deepseek-v4-pro"), value)


def test_nested_preset_options_cannot_poison_cache(monkeypatch):
    monkeypatch.setattr(presets, "_cache", {"test": {"pin_patterns": ["first"]}})
    resolved = presets.resolve_preset("test")
    resolved["pin_patterns"].append("second")
    assert presets.resolve_preset("test") == {"pin_patterns": ["first"]}
    assert presets.resolve_preset("test", {"pin_patterns": []})["pin_patterns"] == []


def test_marker_recognition_rejects_trailing_newlines():
    assert markers.marker_name("[…]") == "gap"
    assert markers.marker_name("[…]\n") is None
    assert markers.marker_name("[…]\nordinary") is None
    assert markers.marker_name("") is None


def planning_input(policy, *, chars=1000, compressed_chars=100, tokens=1000, saved=900):
    candidate = Candidate(compressed_chars, saved, 1.0, False, "low", True)
    item = PlanItem("one", 0, tokens, chars, stock_action="cut",
                    stock_kept_chars=compressed_chars, candidate=candidate)
    return PlanInput("trigger", "prune", tokens, tokens, (item,), CacheState(False, 80), policy)


def test_planner_ev_still_enforces_token_savings_gate():
    planned = plan(planning_input(Policy(ev=EV, min_tokens_saved=901)))
    assert planned.actions[0].action == "stub"
    assert planned.actions[0].reason == "not_enough_tokens"
    assert plan(planning_input(Policy(ev=EV, min_tokens_saved=900))).actions[0].action == "extract"


@pytest.mark.parametrize("ev", [None, EV])
def test_planner_ratio_uses_candidate_characters(ev):
    policy = Policy(ev=ev, min_saved_ratio=0.5)
    planned = plan(planning_input(policy, chars=1000, compressed_chars=900))
    assert planned.actions[0].reason == "no_gain"
    assert plan(planning_input(policy, chars=1000, compressed_chars=100)).actions[0].action == "extract"


def test_equal_callable_instances_do_not_share_signature_cache():
    import inspect

    class Marker:
        def __init__(self, kind):
            self.__signature__ = inspect.Signature([
                inspect.Parameter("kind", inspect.Parameter.KEYWORD_ONLY)
            ] if kind else [])

        def __hash__(self):
            return 1

        def __eq__(self, other):
            return isinstance(other, Marker)

        def __call__(self, *args, **kwargs):
            return "gap"

    assert gap_accepts_kind(Marker(True))
    assert not gap_accepts_kind(Marker(False))
    assert not gap_accepts_kind(None)


def result(**changes):
    values = dict(fail_open=False, compression_risk="low", confidence=0.9,
                  compressed_text="short", original_tokens=1000, kept_tokens=100,
                  tokens_saved=900, fact_lines_dropped=0)
    values.update(changes)
    return SimpleNamespace(**values)


EV = EVPolicy("deepseek-v4-pro", "replay-2026-11-21")


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1])
def test_confidence_gate_rejects_invalid_probability(confidence):
    assert not decide(result(confidence=confidence), Policy(min_confidence=0.7)).accept


def test_confidence_gate_valid_boundaries():
    for confidence in (0.0, 1.0):
        assert decide(result(confidence=confidence), Policy(min_confidence=confidence)).accept
    assert not decide(result(confidence=None), Policy(min_confidence=0.7)).accept
