"""Dated, sourced cache price profiles and the closed-form pay-back share (1.10.0, pure helper).

Profiles are plain data in ``prices.json`` next to this file, read as text and parsed as JSON; it is never executed.
Prices are stored per 1M tokens and relative to the uncached input price (= 1): ``r`` cache read, ``w`` cache write,
``o`` output. Nothing here is a host default: a host (or a replay) names the profile it prices with.

The pay-back rule. Pruning ``delta`` tokens in front of a cached suffix ``S`` rewrites the suffix once at ``w`` instead of
reading it at ``r`` (extra cost ``(w - r)·S``) and saves ``delta`` read tokens on that request and on each of the ``N`` later
requests the cache survives (saving ``r·delta·(N + 1)``). It pays back iff::

    delta / S >= (w - r) / (r · (N + 1))

On a cold cache (idle longer than the TTL, evicted, or the host is rewriting the prefix anyway) the rewrite is paid
whatever Tameru does, so the required share is 0.

Every figure computed from these profiles is replay-only until a live billed probe lands within 10%.

The file is read with ``pathlib`` rather than ``importlib.resources``: the host-rule check treats any ``importlib`` import
as dynamic code (E6) and the baseline may not grow.
"""
from __future__ import annotations

import json
from math import isfinite
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PATH = Path(__file__).with_name("prices.json")
_cache: dict[str, "PriceProfile"] | None = None


@dataclass(frozen=True)
class Tier:
    """A long-context price tier: above ``above_prompt_tokens`` the listed prices are multiplied by ``multiplier``."""
    above_prompt_tokens: int
    multiplier: float
    applies_to: str = ""


@dataclass(frozen=True)
class PriceProfile:
    name: str
    provider: str
    date: str
    r: float                      # cache read / uncached input
    w: float                      # cache write / uncached input
    o: float | None               # output / uncached input (None when the profile is generic)
    ttl_s: float | None           # None: best effort, no fixed TTL
    ttl_refresh_on_use: bool | None
    tiers: tuple[Tier, ...] = ()
    peak_multiplier: float = 1.0
    min_cache_tokens: int | None = None
    max_breakpoints: int | None = None
    context_tokens: int | None = None
    sources: tuple[str, ...] = ()
    notes: str = ""
    unverified: tuple[str, ...] = ()
    verified: dict[str, bool] = field(default_factory=dict, compare=False, hash=False)

    def tier_multiplier(self, prompt_tokens: int) -> float:
        """Price multiplier for a prompt of ``prompt_tokens`` (1.0 below every tier)."""
        out = 1.0
        threshold = -1
        for tier in self.tiers:
            if prompt_tokens > tier.above_prompt_tokens and tier.above_prompt_tokens > threshold:
                out = tier.multiplier
                threshold = tier.above_prompt_tokens
        return out


def _build(name: str, raw: dict[str, Any]) -> PriceProfile:
    rel = raw["relative"]
    cache = raw.get("cache") or {}
    r, w = float(rel["r"]), float(rel["w"])
    if not (isfinite(r) and isfinite(w) and 0 < r <= w):
        raise ValueError(f"price profile {name}: need 0 < r <= w")
    for value in (rel.get("o"), raw.get("ttl_s"), raw.get("peak_multiplier", 1.0)):
        if value is not None and (not isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"price profile {name}: prices, TTL and multipliers must be finite and positive")
    notes = "; ".join(str(raw[k]) for k in ("ttl_note", "peak_note") if raw.get(k))
    return PriceProfile(
        name=name,
        provider=str(raw["provider"]),
        date=str(raw["date"]),
        r=r,
        w=w,
        o=None if rel.get("o") is None else float(rel["o"]),
        ttl_s=None if raw.get("ttl_s") is None else float(raw["ttl_s"]),
        ttl_refresh_on_use=raw.get("ttl_refresh_on_use"),
        tiers=tuple(Tier(int(t["above_prompt_tokens"]), float(t["multiplier"]), str(t.get("applies_to", "")))
                    for t in raw.get("tiers") or ()),
        peak_multiplier=float(raw.get("peak_multiplier", 1.0)),
        min_cache_tokens=cache.get("min_tokens"),
        max_breakpoints=cache.get("max_breakpoints"),
        context_tokens=raw.get("context_tokens"),
        sources=tuple(raw.get("sources") or ()),
        notes=notes,
        unverified=tuple(raw.get("unverified") or ()),
        verified=dict(raw.get("verified") or {}),
    )


def load_profiles() -> dict[str, PriceProfile]:
    """Every profile in ``prices.json`` by name (a copy of the cached mapping)."""
    global _cache
    if _cache is None:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        _cache = {name: _build(name, raw) for name, raw in data["profiles"].items()}
    return dict(_cache)


def profile_names() -> list[str]:
    return sorted(load_profiles())


def profile(name: str) -> PriceProfile:
    """The named profile; ``ValueError`` for an unknown name (the message never echoes the caller's value)."""
    profiles = load_profiles()
    if not isinstance(name, str) or name not in profiles:
        raise ValueError("unknown price profile")
    return profiles[name]


def required_share(p: PriceProfile, n_eff: float, cold: bool = False) -> float:
    """Smallest ``delta / S`` at which a prune in front of a cached suffix pays back.

    ``n_eff`` is the number of later requests the cache is expected to serve (S2: the minimum of the steps to the next
    trigger or compaction, the expected cache survival and the steps left). ``cold`` means the prefix is rewritten anyway,
    so any prune is free (share 0)."""
    if cold:
        return 0.0
    if not isfinite(n_eff) or n_eff < 0:
        raise ValueError("n_eff must be finite and >= 0")
    return (p.w - p.r) / (p.r * (n_eff + 1.0))


def implied_later_requests(p: PriceProfile, share: float) -> float:
    """The ``n_eff`` at which ``required_share`` equals ``share``: ``(w - r) / (r · share) - 1``."""
    if not isfinite(share) or share <= 0:
        raise ValueError("share must be finite and > 0")
    return (p.w - p.r) / (p.r * share) - 1.0
