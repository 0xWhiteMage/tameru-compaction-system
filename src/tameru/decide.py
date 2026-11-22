"""Accept-or-decline decision for a compression result (1.10.0 interface layer).

``decide(result, policy)`` is pure: it reads a ``CompressResult`` (or anything with the same
attributes) and a frozen ``Policy`` and returns a ``Decision`` whose ``reason`` is one of the
closed codes in ``REASONS``. A host keeps the policy as data (``HERMES_POLICY``,
``DSH_POLICY`` express the two acceptance rules that shipped with 1.9.0) and never re-implements
a threshold. The basis string holds numbers and code names only, never request text.

Checks run in this order, the first failure decides: ``fail_open``, ``sanitized``, ``risk``,
``lost_fingerprint``; then, when ``policy.ev`` is set, the EV check in place of the confidence check;
then ``no_gain``, ``low_confidence`` (skipped under EV) and ``not_enough_tokens``.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

REASONS = (
    "ok", "fail_open", "risk", "lost_fingerprint", "low_confidence", "no_gain", "sanitized",
    "not_enough_tokens", "negative_ev",
)
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

_EV_STRENGTHS = ("less", "normal", "more")


@dataclass(frozen=True)
class EVPolicy:
    """The expected-value accept rule: accept iff ``p_hat * V - (1 - p_hat) * L > 0``.

    ``V`` prices the rewrite a prune buys (tokens saved on this and the expected later cached reads, minus the
    suffix rewrite it causes); ``L`` prices a wrong prune (the line turns out to be needed: a read-back, or the
    catastrophic path when read-back fails). ``quantile`` is the conservatism level a calibrator may target —
    0.5 means the point estimate; it is carried for S6 and does not change the raw-confidence path.
    ``calibrator`` is an optional callable ``result -> float | None`` supplying ``p_hat`` (S6 fills it); without
    one the raw confidence is used, capped at 0.98 when the result dropped fact lines."""

    price_profile: str                # a name in prices.json
    loss_profile: str                 # a name in loss_profiles.json
    strength: str = "normal"          # a key of the loss profile's strength_multipliers
    quantile: float = 0.5
    calibrator: Any = None

    def __post_init__(self) -> None:
        if self.strength not in _EV_STRENGTHS:
            raise ValueError(f"strength must be one of {_EV_STRENGTHS}")
        if not 0.0 < float(self.quantile) <= 1.0:
            raise ValueError("quantile must be within (0, 1]")


@dataclass(frozen=True)
class Policy:
    """What a host accepts. ``None`` switches a numeric check off."""

    min_confidence: float | None = None   # reject confidence below this; a null confidence is rejected too
    max_risk: str = "high"                # highest accepted compression_risk (a missing risk counts as high)
    require_fingerprints: bool = False    # every error fingerprint of the original must survive
    min_saved_ratio: float | None = None  # output must be strictly shorter and save at least this share
    min_tokens_saved: int | None = None   # at least this many tokens saved
    allow_sanitized: bool = True          # False: a host-sanitized input is never accepted
    ev: EVPolicy | None = None            # set: the EV rule replaces the confidence check after the hard vetoes

    def __post_init__(self) -> None:
        if self.max_risk not in _RISK_ORDER:
            raise ValueError("max_risk must be low, medium or high")
        for name in ("min_confidence", "min_saved_ratio"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be within 0..1")
        if self.min_tokens_saved is not None and int(self.min_tokens_saved) < 0:
            raise ValueError("min_tokens_saved must be >= 0")
        if self.ev is not None and not isinstance(self.ev, EVPolicy):
            raise ValueError("ev must be an EVPolicy")


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str
    basis: str | None = None


# Hermes plugin 1.9.x ``_acceptable``: not fail-open, risk within the ceiling (default "high"),
# every error fingerprint of the original kept. The ceiling is the plugin's ``max_risk`` setting.
HERMES_POLICY = Policy(max_risk="high", require_fingerprints=True)

# DeepSeek Harness plugin 0.1.x ``shortenPass``: not fail-open, not sanitized, strictly shorter,
# confidence present and at least 0.7 (the ``minConfidence`` setting), at least one token saved.
DSH_POLICY = Policy(
    min_confidence=0.7, max_risk="high", require_fingerprints=False, min_saved_ratio=0.0,
    min_tokens_saved=1, allow_sanitized=False,
)


def surviving_fingerprints(text: str) -> dict[str, str]:
    """Error fingerprints of ``text`` outside lines the engine's trust screen flags.

    A line that reads like an instruction aimed at the model (the engine's own trust-risk
    screen) never counts as a surviving error, so forged text cannot satisfy the check."""
    from .compress_context import (
        _TRUST_RISK_RE, _normalise_instruction_text, error_fingerprints,
    )

    if not text:
        return {}
    kept = [ln for ln in text.split("\n") if _TRUST_RISK_RE.search(_normalise_instruction_text(ln)) is None]
    return error_fingerprints("\n".join(kept), status_rows=False)


def ev_terms(
    result: Any,
    ev: EVPolicy,
    saved_tokens: float,
    *,
    n_eff: float,
    suffix_tokens: float,
    item_tokens: float,
    cache_broken: bool = False,
) -> tuple[float, float, float] | None:
    """``(p_hat, V, L)`` for ``result`` under ``ev``; ``None`` when no confidence exists to price.

    ``V = saved_tokens * r * (n_eff + 1) - S * (w - r)`` with ``S`` the suffix tokens the write makes the
    provider re-cache (0 on a cache-broken event — the rewrite happens anyway). A profile without an output
    price prices recovery output at the uncached input unit (``o = 1``)."""
    p_hat = ev.calibrator(result) if ev.calibrator is not None else getattr(result, "confidence", None)
    if p_hat is None:
        return None
    p_hat = float(p_hat)
    if not isfinite(p_hat) or not 0.0 <= p_hat <= 1.0:
        return None
    if getattr(result, "fact_lines_dropped", 0) and p_hat > 0.98:
        p_hat = 0.98
    from .loss import profile as _loss_profile
    from .prices import profile as _price_profile

    price, loss = _price_profile(ev.price_profile), _loss_profile(ev.loss_profile)
    r, w = price.r, price.w
    o = price.o if price.o is not None else 1.0
    S = 0.0 if cache_broken else float(suffix_tokens)
    V = saved_tokens * r * (n_eff + 1.0) - S * (w - r)
    mult = loss.multiplier(ev.strength)
    L = loss.p_needed * (
        loss.p_recovered * (item_tokens * w + loss.recovery_output_tokens * o)
        + (1 - loss.p_recovered) * loss.lambda_base * mult * item_tokens
    )
    return p_hat, V, L


def _ev_basis(p_hat: float, V: float, L: float, stratum: str | None) -> str:
    return f"p={p_hat:.4g},V={V:.4g},L={L:.4g},stratum={stratum or 'default'}"


def decide(
    result: Any,
    policy: Policy,
    *,
    original: str | None = None,
    fingerprints: Mapping[str, str] | None = None,
    sanitized: bool = False,
    tokens_saved: int | None = None,
    n_eff: float | None = None,
    suffix_tokens: float | None = None,
    item_tokens: float | None = None,
    cache_broken: bool = False,
    stratum: str | None = None,
) -> Decision:
    """Accept or decline ``result`` under ``policy``. Never raises on a well-formed result.

    ``original`` is the text that was compressed: it gives the fingerprints to keep (when
    ``fingerprints`` is not passed) and the character count for ``min_saved_ratio``; without it the
    token counts of the result are used. ``fingerprints`` is ``error_fingerprints(original,
    status_rows=False)`` for a caller that already holds it. ``sanitized`` says the host changed the
    input before the call. ``tokens_saved`` overrides the engine's own count with the host's meter.

    When ``policy.ev`` is set, ``min_confidence`` is ignored and an EV check runs after the hard vetoes:
    ``n_eff``, ``suffix_tokens``, ``item_tokens`` and ``cache_broken`` are the caller's quantities for it
    (all required); ``stratum`` is echoed in the basis. The saved-ratio and tokens-saved checks still
    apply after the EV check."""
    if result is None or getattr(result, "fail_open", True):
        return Decision(False, "fail_open")
    if sanitized and not policy.allow_sanitized:
        return Decision(False, "sanitized")
    risk = getattr(result, "compression_risk", None)
    if _RISK_ORDER.get(risk or "", 2) > _RISK_ORDER[policy.max_risk]:
        return Decision(False, "risk", f"risk={risk}>{policy.max_risk}")
    text = getattr(result, "compressed_text", "")
    if policy.require_fingerprints:
        wanted = fingerprints if fingerprints is not None else (
            _original_fingerprints(original) if original is not None else None
        )
        if wanted is None:
            return Decision(False, "lost_fingerprint", "original_missing")
        lost = len(wanted.keys() - surviving_fingerprints(text).keys())
        if lost:
            return Decision(False, "lost_fingerprint", f"lost={lost}/{len(wanted)}")
    if policy.ev is not None:
        if n_eff is None or suffix_tokens is None or item_tokens is None:
            raise ValueError("an EV policy needs n_eff, suffix_tokens and item_tokens")
        saved = float(tokens_saved if tokens_saved is not None else getattr(result, "tokens_saved", 0) or 0)
        terms = ev_terms(result, policy.ev, saved, n_eff=n_eff, suffix_tokens=suffix_tokens,
                         item_tokens=item_tokens, cache_broken=cache_broken)
        if terms is None:
            return Decision(False, "low_confidence", "confidence=None")
        p_hat, V, L = terms
        if p_hat * V - (1 - p_hat) * L <= 0:
            return Decision(False, "negative_ev", _ev_basis(p_hat, V, L, stratum))
        ev_basis = _ev_basis(p_hat, V, L, stratum)
    else:
        ev_basis = None
    if policy.min_saved_ratio is not None:
        if original is not None:
            before, after, unit = len(original), len(text), "chars"
        else:
            before, after, unit = int(result.original_tokens), int(result.kept_tokens), "tokens"
        saved = before - after
        if saved <= 0 or saved < policy.min_saved_ratio * before:
            return Decision(False, "no_gain", f"saved={saved}/{before} {unit}")
    if policy.min_confidence is not None and policy.ev is None:
        confidence = getattr(result, "confidence", None)
        if confidence is None:
            return Decision(False, "low_confidence", "confidence=None")
        if not isfinite(confidence) or not 0.0 <= confidence <= 1.0 or confidence < policy.min_confidence:
            return Decision(False, "low_confidence", f"confidence={confidence:.3f}<{policy.min_confidence}")
    if policy.min_tokens_saved is not None:
        saved_tokens = int(tokens_saved if tokens_saved is not None else getattr(result, "tokens_saved", 0))
        if saved_tokens < policy.min_tokens_saved:
            return Decision(False, "not_enough_tokens", f"saved={saved_tokens}<{policy.min_tokens_saved}")
    return Decision(True, "ok", ev_basis)


def _original_fingerprints(original: str) -> dict[str, str]:
    from .compress_context import error_fingerprints

    return error_fingerprints(original, status_rows=False)
