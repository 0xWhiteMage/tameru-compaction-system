"""1.10.0 price profiles and the closed-form pay-back share (pure helper; no host default uses it yet)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tameru import prices

PRICES_SHA256 = "070dcfa3551e875c310334781f534346817c3d73008299d872a432c17543faa0"
DATA = Path(prices.__file__).with_name("prices.json")


def test_prices_file_is_hash_pinned():
    assert hashlib.sha256(DATA.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == PRICES_SHA256


def test_profile_names():
    assert prices.profile_names() == sorted([
        "deepseek-v4-pro", "deepseek-flash",
        "anthropic-opus-5.5-5m", "anthropic-opus-5.5-1h", "anthropic-sonnet-5.5-5m", "anthropic-sonnet-5.5-1h",
        "anthropic-haiku-5.5-5m", "anthropic-haiku-5.5-1h", "openai-generic-30m", "openai-generic-12h",
    ])
    with pytest.raises(ValueError) as err:
        prices.profile("SECRET-NAME")
    assert "SECRET-NAME" not in str(err.value)


def test_every_profile_has_a_date_a_source_and_verification_flags():
    raw = json.loads(DATA.read_text(encoding="utf-8"))["profiles"]
    for name, p in prices.load_profiles().items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.date), name
        assert p.sources and all(s for s in p.sources), name
        assert any(s.startswith("https://") for s in p.sources), name
        assert p.verified and all(isinstance(v, bool) for v in p.verified.values()), name
        assert p.unverified, name  # every profile records what is not verified
        if p.provider == "openai":
            assert raw[name]["status"] == "secondary, verify"


def test_relative_prices_match_the_absolute_prices():
    raw = json.loads(DATA.read_text(encoding="utf-8"))["profiles"]
    for name, entry in raw.items():
        a = entry["absolute"]
        if a is None:
            continue
        rel = entry["relative"]
        assert rel["r"] == pytest.approx(a["cache_read"] / a["input"], abs=1e-6), name
        assert rel["w"] == pytest.approx(a["cache_write"] / a["input"], abs=1e-6), name
        assert rel["o"] == pytest.approx(a["output"] / a["input"], abs=1e-6), name


def test_tiers():
    haiku = prices.profile("anthropic-haiku-5.5-5m")
    assert haiku.tier_multiplier(100_000) == 1.0 and haiku.tier_multiplier(100_001) == 5.0
    assert prices.profile("anthropic-opus-5.5-5m").tier_multiplier(900_000) == 1.0
    assert prices.profile("openai-generic-30m").tier_multiplier(272_001) == 2.0
    assert prices.profile("deepseek-v4-pro").peak_multiplier == 2.0


# The implied later-request count for the hand-set pay-back share 0.35 the DeepSeek plugin used:
# N = (w - r) / (r * 0.35) - 1, computed exactly from the stored relative prices.
TABLE_035 = {
    "deepseek-v4-pro": 81.858,          # r = 1/30 (stored 0.033333), w = 1
    "deepseek-flash": 139.0,            # r = 0.02, w = 1
    "anthropic-haiku-5.5-5m": 31.857,   # Anthropic 5 min at the standard read (r = 0.1, w = 1.25)
    "openai-generic-30m": 31.857,       # same prices (r = 0.1, w = 1.25)
    "anthropic-opus-5.5-5m": 67.571,    # Opus / Sonnet 5.5 read at 0.05 (w = 1.25)
    "anthropic-sonnet-5.5-5m": 67.571,
    "openai-generic-12h": 67.571,       # r = 0.1, w = 2.5
    "anthropic-haiku-5.5-1h": 53.286,   # Anthropic 1 h at the standard read (r = 0.1, w = 2); S2 rounded this to 54
    "anthropic-opus-5.5-1h": 110.429,   # r = 0.05, w = 2
    "anthropic-sonnet-5.5-1h": 110.429,
}


def test_implied_later_requests_table_for_share_035():
    for name, expected in TABLE_035.items():
        assert prices.implied_later_requests(prices.profile(name), 0.35) == pytest.approx(expected, abs=1e-3), name
    # The old replay assumption for DeepSeek (r = 0.1, w = 1.0) implied about 25 later requests, i.e. it treated a
    # share of 0.35 as paying back three times sooner than the real pro price (r = 1/30) does.
    old = prices.PriceProfile("old-deepseek", "deepseek", "2026-11-19", r=0.1, w=1.0, o=None, ttl_s=None,
                              ttl_refresh_on_use=None)
    assert prices.implied_later_requests(old, 0.35) == pytest.approx(24.714, abs=1e-3)


def test_required_share_inverts_implied_later_requests():
    for p in prices.load_profiles().values():
        n = prices.implied_later_requests(p, 0.35)
        assert prices.required_share(p, n) == pytest.approx(0.35)
        assert prices.required_share(p, 0) == pytest.approx((p.w - p.r) / p.r)


def test_cold_cache_needs_no_share():
    for p in prices.load_profiles().values():
        assert prices.required_share(p, 0, cold=True) == 0.0
        assert prices.required_share(p, 500, cold=True) == 0.0


def test_monotonicity():
    for p in prices.load_profiles().values():
        shares = [prices.required_share(p, n) for n in (0, 1, 5, 20, 100, 1000)]
        assert all(a > b for a, b in zip(shares, shares[1:])), p.name
        ns = [prices.implied_later_requests(p, s) for s in (0.05, 0.1, 0.35, 0.65, 1.0)]
        assert all(a > b for a, b in zip(ns, ns[1:])), p.name
    # a dearer write needs a larger share; a dearer read a smaller one
    assert prices.required_share(prices.profile("anthropic-opus-5.5-1h"), 10) > prices.required_share(
        prices.profile("anthropic-opus-5.5-5m"), 10)
    assert prices.required_share(prices.profile("anthropic-haiku-5.5-5m"), 10) < prices.required_share(
        prices.profile("anthropic-sonnet-5.5-5m"), 10)


def test_bad_arguments():
    p = prices.profile("deepseek-v4-pro")
    with pytest.raises(ValueError):
        prices.required_share(p, -1)
    with pytest.raises(ValueError):
        prices.implied_later_requests(p, 0)
