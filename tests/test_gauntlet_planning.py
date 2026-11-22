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
