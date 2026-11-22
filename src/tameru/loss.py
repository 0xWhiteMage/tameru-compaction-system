"""Dated, sourced loss profiles for the EV accept rule (1.10.0, pure helper).

Profiles are plain data in ``loss_profiles.json`` next to this file, read as text and parsed as JSON; it is never
executed. A loss profile prices what a *wrong* prune is expected to cost, in units of the item's own tokens: the
probability a kept line is needed later (``p_needed``), the probability a missing line is recovered through
read-back (``p_recovered``), the output cost of that recovery, and a catastrophic-loss unit (``lambda_base``) scaled
by a strength multiplier. Every number in the file carries its source and an ``unverified`` flag; a flagged figure
is an assumption, and the profile's ``unverified`` tuple names those fields.

Nothing here is a host default: a host (or ``tameru.plan``) names the profile it prices with. The file is read
with ``pathlib`` rather than ``importlib.resources``, as ``prices.py`` documents for the host-rule check.
"""
from __future__ import annotations

import json
from math import isfinite
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PATH = Path(__file__).with_name("loss_profiles.json")
_cache: dict[str, "LossProfile"] | None = None

_VALUE_FIELDS = ("p_needed", "p_recovered", "recovery_output_tokens", "lambda_base")


@dataclass(frozen=True)
class LossProfile:
    """What a wrong prune costs. ``strength_multipliers`` is keyed by strength name (``less``/``normal``/``more``)."""

    name: str
    date: str
    p_needed: float                   # probability a kept line is needed by a later request
    p_recovered: float                # probability a missing line is recovered via read-back
    recovery_output_tokens: int       # output tokens one read-back answer costs
    lambda_base: float                # catastrophic-loss unit, in multiples of the item's own tokens
    strength_multipliers: dict[str, float] = field(default_factory=dict, compare=False, hash=False)
    sources: tuple[str, ...] = ()
    field_sources: dict[str, str] = field(default_factory=dict, compare=False, hash=False)
    unverified: tuple[str, ...] = ()

    def multiplier(self, strength: str) -> float:
        """The loss multiplier for a strength name; ``ValueError`` for a name the profile lacks."""
        try:
            return float(self.strength_multipliers[strength])
        except (KeyError, TypeError, ValueError):
            raise ValueError("unknown strength") from None


def _number(name: str, field_name: str, raw: dict[str, Any]) -> tuple[float, str, bool]:
    entry = raw.get(field_name)
    if not isinstance(entry, dict) or not isinstance(entry.get("value"), (int, float)):
        raise ValueError(f"loss profile {name}: {field_name} needs a numeric value")
    try:
        value = float(entry["value"])
    except OverflowError:
        raise ValueError(f"loss profile {name}: {field_name} must be finite") from None
    if not isfinite(value):
        raise ValueError(f"loss profile {name}: {field_name} must be finite")
    return value, str(entry.get("source", "")), bool(entry.get("unverified"))


def _build(name: str, raw: dict[str, Any]) -> LossProfile:
    values, field_sources, unverified = {}, {}, []
    for field_name in _VALUE_FIELDS:
        value, source, flagged = _number(name, field_name, raw.get("values") or {})
        values[field_name], field_sources[field_name] = value, source
        if flagged:
            unverified.append(field_name)
    multipliers: dict[str, float] = {}
    for strength, entry in (raw.get("strength_multipliers") or {}).items():
        value, source, flagged = _number(name, f"strength_multipliers.{strength}", {f"strength_multipliers.{strength}": entry})
        multipliers[str(strength)] = value
        field_sources[f"strength_multipliers.{strength}"] = source
        if flagged:
            unverified.append(f"strength_multipliers.{strength}")
    if not multipliers:
        raise ValueError(f"loss profile {name}: no strength_multipliers")
    if not (0.0 <= values["p_needed"] <= 1.0) or not (0.0 <= values["p_recovered"] <= 1.0):
        raise ValueError(f"loss profile {name}: probabilities must be within 0..1")
    if values["recovery_output_tokens"] < 0 or values["lambda_base"] < 0:
        raise ValueError(f"loss profile {name}: token and lambda figures must be >= 0")
    if any(m <= 0 for m in multipliers.values()):
        raise ValueError(f"loss profile {name}: strength multipliers must be > 0")
    return LossProfile(
        name=name,
        date=str(raw["date"]),
        p_needed=values["p_needed"],
        p_recovered=values["p_recovered"],
        recovery_output_tokens=int(values["recovery_output_tokens"]),
        lambda_base=values["lambda_base"],
        strength_multipliers=multipliers,
        sources=tuple(raw.get("sources") or ()),
        field_sources=field_sources,
        unverified=tuple(unverified),
    )


def load_profiles() -> dict[str, LossProfile]:
    """Every profile in ``loss_profiles.json`` by name (a copy of the cached mapping)."""
    global _cache
    if _cache is None:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        _cache = {name: _build(name, raw) for name, raw in data["profiles"].items()}
    return dict(_cache)


def profile_names() -> list[str]:
    return sorted(load_profiles())


def profile(name: str) -> LossProfile:
    """The named profile; ``ValueError`` for an unknown name (the message never echoes the caller's value)."""
    profiles = load_profiles()
    if not isinstance(name, str) or name not in profiles:
        raise ValueError("unknown loss profile")
    return profiles[name]
