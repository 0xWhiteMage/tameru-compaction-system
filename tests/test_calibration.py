"""S6 calibrator contracts (1.10.0): p_hat, the beta helpers and the shipped table.

No scipy at test time: the reference values below were computed once with scipy.stats.beta and
frozen as literals.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tameru import calibration
from tameru.calibration import Calibration, Stratum, beta_cdf, beta_ppf, p_hat, stratum_key
from tameru.contract_gates import QUERY_BASES


def _table(strata, prior_mean=0.9, prior_strength=8.0, cap=0.989):
    return Calibration("test", prior_mean, prior_strength, cap, strata, {})


class PHatTests(unittest.TestCase):
    def setUp(self):
        self.specific = Stratum(alpha=9.6, beta=0.4, families=4)  # mean 0.96
        self.vague = Stratum(alpha=9.6, beta=0.4, families=4)
        self.table = _table({
            "lexical|specific": self.specific,
            "lexical|vague": self.vague,
            "structural|specific": self.vague,
            "anchored|vague": self.vague,
        })

    def test_fact_drop_gives_zero(self):
        self.assertEqual(p_hat("lexical", True, fact_lines_dropped=1, table=self.table), 0.0)
        self.assertEqual(p_hat("lexical", True, fact_lines_dropped=3, table=self.table), 0.0)

    def test_vague_and_structural_strata_capped_unless_lifts_cap(self):
        cap = self.table.cap
        high = Stratum(alpha=99.9, beta=0.1)  # mean 0.999
        table = _table({
            "lexical|vague": high,
            "structural|specific": high,
            "lexical|specific": high,
            "anchored|vague": Stratum(alpha=99.9, beta=0.1, lifts_cap=True),
        })
        self.assertEqual(p_hat("lexical", False, table=table), cap)
        self.assertEqual(p_hat("structural", True, table=table), cap)
        self.assertEqual(p_hat("lexical", True, table=table), high.mean)   # specific non-structural: uncapped
        self.assertEqual(p_hat("anchored", False, table=table), high.mean)  # lifts_cap clears the cap

    def test_unknown_stratum_uses_prior(self):
        prior = self.table.prior()
        self.assertAlmostEqual(p_hat("cross_lingual", True, table=self.table), prior.mean)

    def test_quantile_half_is_posterior_mean_other_quantiles_beta_ppf(self):
        s = self.specific
        self.assertAlmostEqual(p_hat("lexical", True, quantile=0.5, table=self.table), s.mean)
        q = 0.1
        self.assertAlmostEqual(
            p_hat("lexical", True, quantile=q, table=self.table),
            beta_ppf(q, s.alpha, s.beta),
            places=9,
        )

    def test_isotonic_lookup_at_between_and_beyond_edges(self):
        iso = Stratum(alpha=9.6, beta=0.4, iso=((0.80, 0.70), (0.90, 0.85), (1.0, 0.97)))
        table = _table({"lexical|specific": iso})
        base = -iso.mean  # quantile-0.5 shift applied on top of the step value? no: shift=0 at 0.5
        del base
        at = p_hat("lexical", True, raw_confidence=0.90, table=table)      # exact edge
        self.assertAlmostEqual(at, 0.85)
        between = p_hat("lexical", True, raw_confidence=0.85, table=table)  # first edge >= value
        self.assertAlmostEqual(between, 0.85)
        below = p_hat("lexical", True, raw_confidence=0.10, table=table)    # below all edges
        self.assertAlmostEqual(below, 0.70)
        above = p_hat("lexical", True, raw_confidence=0.99, table=table)    # between .90 and 1.0
        self.assertAlmostEqual(above, 0.97)
        over = p_hat("lexical", True, raw_confidence=2.0, table=table)      # beyond the last edge
        self.assertAlmostEqual(over, 0.97)


class BetaFunctionTests(unittest.TestCase):
    """Frozen scipy.stats.beta references (computed once at write time)."""

    def test_beta_ppf(self):
        self.assertAlmostEqual(beta_ppf(0.1, 9.6, 0.4), 0.8856797209594427, places=9)
        self.assertAlmostEqual(beta_ppf(0.95, 4.0, 2.0), 0.923559608587671, places=9)

    def test_beta_cdf(self):
        self.assertAlmostEqual(beta_cdf(0.99, 50.0, 3.0), 0.9846473742663409, places=9)
        self.assertAlmostEqual(beta_cdf(0.5, 2.0, 3.0), 0.6875, places=12)

    def test_ppf_inverts_cdf(self):
        for q in (0.05, 0.5, 0.95):
            self.assertAlmostEqual(beta_cdf(beta_ppf(q, 9.6, 0.4), 9.6, 0.4), q, places=9)


class ShippedTableTests(unittest.TestCase):
    def test_calibration_json_parses_and_strata_keys_are_known(self):
        path = Path(calibration.__file__).with_name("calibration.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        cal = calibration._parse(data)  # same parse load() applies: raises on a bad table
        self.assertTrue(cal.strata)
        for key in cal.strata:
            basis, sep, style = key.partition("|")
            self.assertEqual(sep, "|")
            self.assertIn(basis, QUERY_BASES)
            self.assertIn(style, calibration.STYLES)


if __name__ == "__main__":
    unittest.main()
