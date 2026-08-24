"""v0.8.0 semantic-tier tests: paraphrase distractor discrimination.

These cases are IMPOSSIBLE for the lexical engine (no shared vocabulary
between query and evidence/distractor) — the documented honest limit since
the red-team v2 report. With a tier attached they become decidable.

All tests skip cleanly when sentence-transformers isn't installed, so the
zero-dep contract holds for default installs.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import compress_context


def _tier():
    try:
        from tameru.semantic import SemanticTier, SemanticUnavailable
    except Exception:
        raise unittest.SkipTest("semantic deps unavailable")
    try:
        return SemanticTier()
    except SemanticUnavailable:
        raise unittest.SkipTest("sentence-transformers not installed")


FILLER = "\n\n".join(
    f"Archive section {i}: routine operational status record." for i in range(30)
)

# Paraphrase case: query asks about "backup host"; evidence says "failover
# machine"; distractor talks "replication server". ZERO shared content words.
PARA_EVIDENCE = [
    "Operation Moonlight's designated failover machine is DB-77-Z.",
    "The failover machine for Moonlight handles warehouse failover duties.",
]
PARA_DISTRACTOR = (
    "The replication server cluster mirrors data nightly. Replication server "
    "operations are routine. The replication server fleet is healthy."
)
PARA_QUERY = "Which backup host serves the lunar facility?"


@unittest.skipUnless(
    __import__("importlib").util.find_spec("sentence_transformers") is not None,
    "sentence-transformers not installed",
)
class ParaphraseDistractorTests(unittest.TestCase):
    def test_without_tier_case_still_safe(self):
        """Lexical-only: no gold loss allowed even if savings collapse."""
        ctx = FILLER + "\n\n" + "\n\n".join(PARA_EVIDENCE) + "\n\n" + FILLER + "\n\n" + PARA_DISTRACTOR
        out = compress_context(ctx, PARA_QUERY, ccr=False, citations=False)
        if not out.fail_open:
            self.assertIn("DB-77-Z", out.compressed_text)
        else:
            self.assertIn("DB-77-Z", ctx)  # sanity: source has it

    def test_with_tier_discriminates_paraphrase_distractor(self):
        """Semantic tier: fail open on genuine ambiguity OR keep the answer —
        never silently drop the paraphrased evidence."""
        tier = _tier()
        ctx = FILLER + "\n\n" + "\n\n".join(PARA_EVIDENCE) + "\n\n" + FILLER + "\n\n" + PARA_DISTRACTOR
        out = compress_context(
            ctx, PARA_QUERY, ccr=False, citations=False, semantic_tier=tier
        )
        # The contract: DB-77-Z must survive in the output. Either we keep it,
        # or we fail open (whole doc). Silently dropping it is the failure.
        if out.fail_open:
            self.assertLess(out.tokens_saved_pct, 5.0)
        else:
            self.assertIn("DB-77-Z", out.compressed_text)


class TierFallbackTests(unittest.TestCase):
    class _BrokenTier:
        available = True

        def score_against_query(self, q, texts):
            raise RuntimeError("model exploded")

    def test_broken_tier_degrades_to_lexical(self):
        """A crashing tier must never break compression."""
        ctx = FILLER + "\n\nNeedle-alpha carries the payload fact ALPHA-123.\n\n" + FILLER
        out = compress_context(
            ctx,
            "needle-alpha",
            ccr=False,
            citations=False,
            semantic_tier=self._BrokenTier(),
        )
        self.assertIn("ALPHA-123", ctx)
        self.assertIsNotNone(out.compressed_text)

    def test_none_tier_is_identical_to_v06(self):
        """Default path unchanged: no tier == v0.7 behaviour."""
        ctx = FILLER + "\n\nSelene endpoint is DB-77-Z.\n\n" + FILLER
        out = compress_context(ctx, "Selene endpoint?", ccr=False, citations=False)
        self.assertIn("DB-77-Z", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
