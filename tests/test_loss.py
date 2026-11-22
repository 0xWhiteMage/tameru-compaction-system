"""1.10.0 loss profiles for the EV accept rule (pure helper; no host default uses it yet)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tameru import loss

LOSS_SHA256 = "beb5f80b6e91aea257240fc5a03501756e15788b6f5c94c234664398fbc2f10d"
DATA = Path(loss.__file__).with_name("loss_profiles.json")


def test_loss_file_is_hash_pinned():
    assert hashlib.sha256(DATA.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == LOSS_SHA256


def test_profile_names():
    assert loss.profile_names() == ["replay-2026-11-21"]
    with pytest.raises(ValueError) as err:
        loss.profile("SECRET-NAME")
    assert "SECRET-NAME" not in str(err.value)


def test_every_profile_has_a_date_a_source_and_per_number_flags():
    raw = json.loads(DATA.read_text(encoding="utf-8"))["profiles"]
    for name, p in loss.load_profiles().items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.date), name
        assert p.sources and all(s for s in p.sources), name
        entry = raw[name]
        numbers = dict(entry["values"])
        numbers.update({f"strength_multipliers.{k}": v for k, v in entry["strength_multipliers"].items()})
        for field, spec in numbers.items():
            assert spec["source"], (name, field)
            assert isinstance(spec["unverified"], bool), (name, field)
        assert p.unverified, name  # every profile records what is not verified
        assert set(p.unverified) == {f for f, s in numbers.items() if s["unverified"]}, name
        assert set(p.field_sources) == set(numbers), name


def test_replay_2026_11_21_values():
    p = loss.profile("replay-2026-11-21")
    assert p.p_needed == pytest.approx(0.25)
    assert p.p_recovered == pytest.approx(0.90)
    assert p.recovery_output_tokens == 200
    assert p.lambda_base == pytest.approx(100.0)
    assert p.strength_multipliers == {"less": 10.0, "normal": 1.0, "more": 0.1}
    assert "p_needed" in p.unverified and "p_recovered" not in p.unverified


def test_multiplier_lookup():
    p = loss.profile("replay-2026-11-21")
    assert p.multiplier("less") == 10.0
    with pytest.raises(ValueError):
        p.multiplier("SECRET-STRENGTH")


def test_validation_rejects_bad_profiles():
    base = {"date": "2026-11-21", "sources": ["x"],
            "values": {"p_needed": {"value": 0.25, "source": "a", "unverified": True},
                       "p_recovered": {"value": 0.9, "source": "b", "unverified": False},
                       "recovery_output_tokens": {"value": 200, "source": "c", "unverified": True},
                       "lambda_base": {"value": 100, "source": "d", "unverified": True}},
            "strength_multipliers": {"normal": {"value": 1.0, "source": "e", "unverified": True}}}
    assert loss._build("ok", base).p_needed == 0.25
    for mutate in (
        lambda d: d["values"]["p_needed"].update(value=1.5),
        lambda d: d["values"]["p_recovered"].update(value=-0.1),
        lambda d: d["values"]["lambda_base"].update(value=-1),
        lambda d: d["values"].pop("p_needed"),
        lambda d: d["strength_multipliers"].pop("normal"),
        lambda d: d["strength_multipliers"]["normal"].update(value=0),
    ):
        bad = json.loads(json.dumps(base))
        mutate(bad)
        with pytest.raises(ValueError):
            loss._build("bad", bad)
