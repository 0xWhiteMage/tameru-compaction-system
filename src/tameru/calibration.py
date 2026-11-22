"""S6 calibrators: the probability that an accepted extract lost nothing needed (1.10.0, pure helper).

``calibration.json`` next to this file (fit by ``benchmarks/engine_bench/calibrate.py`` on the round-2 dev split, read
as text and parsed as JSON, never executed) holds one Beta distribution per stratum: what the confidence rests on
(``confidence_basis``) x the objective's style (``specific`` when it names distinctive selectors, else ``vague``, the
reading the engine's own fact-drop confidence rule uses). Families are a stratum's units: each family of the fit adds
its success rate to alpha and its loss rate to beta, on top of ``prior.strength`` pseudo-families at the global
family-mean rate, so a stratum is as certain as the number of families behind it, not the number of rows. Losses
cluster by family (one output format the engine misreads), and every runtime prediction is a prediction for a family
the fit never saw.

The label is "kept every gold line and dropped no protected fact line". A result that reports
``fact_lines_dropped > 0`` lost a protected fact line by that definition, so its probability is 0; what a lost line
costs (whether it is needed later, whether read-back recovers it) is the loss profile's business, not this one's.

Where a stratum's raw confidence ranks its losses (cluster-bootstrap AUROC lower bound >= 0.65), the table also holds
an isotonic step map of raw confidence. A vague or structural stratum never reaches ``cap`` (0.99) unless its own
Beta's 5th percentile does (``lifts_cap``).
"""
from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_PATH = Path(__file__).with_name("calibration.json")
_cache: "Calibration | None" = None
STYLES = ("specific", "vague")


@dataclass(frozen=True)
class Stratum:
    alpha: float
    beta: float
    families: int = 0
    rows: int = 0
    losses: int = 0
    lifts_cap: bool = False
    iso: tuple[tuple[float, float], ...] = ()   # (upper raw-confidence edge, probability), edges ascending

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


@dataclass(frozen=True)
class Calibration:
    method: str
    prior_mean: float
    prior_strength: float
    cap: float
    strata: Mapping[str, Stratum]
    source: Mapping[str, Any]

    def prior(self) -> Stratum:
        return Stratum(self.prior_mean * self.prior_strength, (1.0 - self.prior_mean) * self.prior_strength)


def stratum_key(basis: str | None, specific: bool) -> str:
    return f"{basis or 'none'}|{'specific' if specific else 'vague'}"


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny, eps = 1e-300, 1e-15
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """The ``q`` quantile of Beta(a, b), by bisection on :func:`beta_cdf` (to 1e-12)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be within (0, 1)")
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2.0


def _parse(data: dict[str, Any]) -> Calibration:
    strata = {}
    for key, raw in (data.get("strata") or {}).items():
        alpha, beta = float(raw["alpha"]), float(raw["beta"])
        if alpha <= 0 or beta <= 0:
            raise ValueError("calibration: a stratum needs alpha > 0 and beta > 0")
        iso = tuple((float(edge), float(p)) for edge, p in raw.get("iso") or ())
        if any(not 0.0 <= p <= 1.0 for _e, p in iso) or [e for e, _p in iso] != sorted(e for e, _p in iso):
            raise ValueError("calibration: iso steps need ascending edges and probabilities within 0..1")
        strata[str(key)] = Stratum(alpha, beta, int(raw.get("families", 0)), int(raw.get("rows", 0)),
                                   int(raw.get("losses", 0)), bool(raw.get("lifts_cap")), iso)
    prior = data["prior"]
    mean, strength, cap = float(prior["mean"]), float(prior["strength"]), float(data["cap"]["value"])
    if not (0.0 < mean < 1.0 and strength > 0 and 0.0 < cap <= 1.0):
        raise ValueError("calibration: prior mean within (0, 1), strength > 0, cap within (0, 1]")
    return Calibration(str(data["method"]), mean, strength, cap, strata, dict(data.get("source") or {}))


def load() -> Calibration:
    """The shipped table (cached)."""
    global _cache
    if _cache is None:
        _cache = _parse(json.loads(_PATH.read_text(encoding="utf-8")))
    return _cache


def p_hat(
    basis: str | None,
    specific: bool,
    fact_lines_dropped: int = 0,
    raw_confidence: float | None = None,
    *,
    quantile: float = 0.5,
    table: Calibration | None = None,
) -> float:
    """P(the extract kept every needed line) for one accepted result.

    ``quantile`` 0.5 is the point estimate (the posterior mean, the value expected utility needs); any other level in
    (0, 1) is that quantile of the stratum's Beta, the conservatism a host's EV policy may ask for. A stratum the table
    lacks uses the prior alone, which is wide on purpose."""
    if fact_lines_dropped and fact_lines_dropped > 0:
        return 0.0
    cal = table or load()
    s = cal.strata.get(stratum_key(basis, specific)) or cal.prior()
    shift = 0.0 if quantile == 0.5 else beta_ppf(quantile, s.alpha, s.beta) - s.mean
    if s.iso and raw_confidence is not None:
        edges = [edge for edge, _p in s.iso]
        at = min(bisect.bisect_left(edges, float(raw_confidence)), len(s.iso) - 1)
        value = s.iso[at][1] + shift
    else:
        value = s.mean + shift
    if (not specific or basis == "structural") and not s.lifts_cap:
        value = min(value, cal.cap)
    return min(1.0, max(0.0, value))
