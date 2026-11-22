"""Regression tests for protocol.py hardening (request validation and the pin regex check)."""
from __future__ import annotations

import pytest

from tameru import protocol
from tameru.protocol import ProtocolError, validate_plan_request, validate_request

PLAN = {"event": "trigger", "host_mode": "prune", "items": [], "cache": {"warm": True, "n_eff": 1},
        "policy": {}, "prompt_tokens": 1, "trigger_tokens": 1}


def code(fn, request):
    with pytest.raises(ProtocolError) as err:
        fn(request)
    return err.value.code


def test_an_int_too_large_for_a_float_is_a_protocol_error_not_an_overflow():
    assert code(validate_request, {"text": "t", "budget_ratio": 10 ** 400}) == "bad_budget_ratio"
    assert code(validate_request, {"text": "t", "pin_recent": -10 ** 400}) == "bad_pin_recent"
    assert code(validate_plan_request, {**PLAN, "growth_tokens_per_step": 10 ** 400}) == "bad_growth"
    assert code(validate_plan_request, {**PLAN, "cache": {"warm": True, "n_eff": 10 ** 400}}) == "bad_cache"
