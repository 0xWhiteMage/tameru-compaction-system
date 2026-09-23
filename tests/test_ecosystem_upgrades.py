"""Coverage for the ecosystem-research upgrades: secrets screen before CCR
archival, the self-output recursion guard, compressible-subset budgeting
in fixed mode, CCR listing/pagination recall, selection-path receipts,
and the ``strategy="auto"`` escalation ladder.
"""
from __future__ import annotations

import tempfile
import unittest

from tameru.compress_context import (
    _contains_secret,
    compress_context,
    list_ccr,
    retrieve,
    select_fixed,
)


def _needle_context(n: int = 30) -> str:
    parts = [f"Filler paragraph {i} about routine topic {i} with detail." for i in range(n)]
    parts[15] = (
        "The quixotic configuration lives at /etc/quixotic.conf "
        "with timeout 42 and retries 7."
    )
    return "\n\n".join(parts)


def _block(
    i: int,
    tokens: int,
    *,
    score: float = 1.0,
    pinned: bool = False,
    text: str | None = None,
) -> dict:
    word_count = max(1, tokens)
    return {
        "id": i,
        "text": text if text is not None else f"block {i} " + "w " * word_count,
        "tokens": tokens,
        "score": score,
        "start": i * 4,
        "end": i * 4 + 3,
        "type": "para",
        "entity_hits": 0,
        "term_hits": 0,
        "rare_term_hits": 0,
        "reason": "coverage",
        "trust_risk": False,
        "pinned": pinned,
    }


class SecretsScreenTests(unittest.TestCase):
    def test_contains_secret_patterns(self):
        self.assertTrue(_contains_secret("key = AKIAIOSFODNN7EXAMPLE"))
        self.assertTrue(
            _contains_secret("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        )
        self.assertTrue(_contains_secret("token: ghp_0123456789abcdefghijKL"))
        self.assertTrue(_contains_secret("use sk-0123456789abcdefghijklmnop here"))
        self.assertTrue(_contains_secret('api_key = "abcdefghijklmnopqrstuv"'))
        self.assertFalse(_contains_secret("an ordinary paragraph about logs"))
        self.assertFalse(_contains_secret('api_key = "short"'))
        self.assertFalse(_contains_secret(""))

    def test_secret_input_skips_ccr(self):
        ctx = _needle_context() + "\n\naws key AKIAIOSFODNN7EXAMPLE in notes"
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "quixotic configuration", ccr_dir=td)
            self.assertFalse(out.fail_open)
            self.assertIsNone(out.ccr)
            self.assertNotIn("[CC-Retrieve:", out.compressed_text)
            self.assertIn("ccr skipped: secret material detected", out.reasons)
            self.assertEqual(list_ccr(td), [])

    def test_clean_input_stores_normally(self):
        ctx = _needle_context()
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "quixotic configuration", ccr_dir=td)
            self.assertFalse(out.fail_open)
            self.assertIsNotNone(out.ccr)
            self.assertIn("[CC-Retrieve:", out.compressed_text)
            self.assertNotIn(
                "ccr skipped: secret material detected", out.reasons
            )


class RecursionGuardTests(unittest.TestCase):
    def test_ccr_marked_output_not_recompressed(self):
        ctx = _needle_context()
        with tempfile.TemporaryDirectory() as td:
            first = compress_context(ctx, "quixotic configuration", ccr_dir=td)
            self.assertFalse(first.fail_open)
            self.assertIn("[CC-Retrieve:", first.compressed_text)
            second = compress_context(
                first.compressed_text, "quixotic configuration", ccr_dir=td
            )
            self.assertTrue(second.fail_open)
            self.assertEqual(second.policy_name, "local-noop-recursion")
            self.assertEqual(second.compressed_text, first.compressed_text)
            self.assertIn(
                "input already compressed (recursion guard)", second.reasons
            )

    def test_wrapped_output_not_recompressed(self):
        wrapped = '<compressed_context version="1">\nbody\n</compressed_context>'
        out = compress_context(wrapped, "body")
        self.assertTrue(out.fail_open)
        self.assertEqual(out.policy_name, "local-noop-recursion")
        self.assertEqual(out.compressed_text, wrapped)

    def test_plain_text_unaffected(self):
        ctx = _needle_context()
        out = compress_context(ctx, "quixotic configuration")
        self.assertNotEqual(out.policy_name, "local-noop-recursion")


class CompressibleBudgetTests(unittest.TestCase):
    def test_pins_do_not_consume_budget(self):
        # 10 blocks x 100 tokens, one pinned. ratio=0.1 over the
        # compressible 900 tokens gives budget 100 + 90 = 190 — enough
        # for the pin plus roughly one more block.
        blocks = [_block(i, 100) for i in range(10)]
        blocks[0]["pinned"] = True
        blocks[0]["text"] = "PINNED-MARKER " + "w " * 80
        kept, fail_open, _ = select_fixed(blocks, 0.1)
        self.assertFalse(fail_open)
        self.assertIn(0, kept)

    def test_no_pins_budget_unchanged(self):
        # No pins: budget is exactly total * ratio — legacy semantics.
        blocks = [_block(i, 100) for i in range(10)]
        kept, fail_open, _ = select_fixed(blocks, 0.3)
        self.assertFalse(fail_open)
        kept_tokens = sum(b["tokens"] for b in blocks if b["id"] in kept)
        self.assertLessEqual(kept_tokens, 450)

    def test_all_pinned_keeps_all(self):
        blocks = [_block(i, 100, pinned=True) for i in range(5)]
        kept, fail_open, _ = select_fixed(blocks, 0.1)
        self.assertFalse(fail_open)
        self.assertEqual(kept, {0, 1, 2, 3, 4})

    def test_fixed_mode_integration_keeps_pin(self):
        ctx = _needle_context() + "\n\n" + "-- filler\n" * 5
        out = compress_context(
            ctx,
            "quixotic configuration",
            mode="fixed",
            budget_ratio=0.15,
            pin_recent=1,
        )
        self.assertFalse(out.fail_open)
        self.assertIn("-- filler", out.compressed_text)


class CcrRecallTests(unittest.TestCase):
    def test_list_ccr_returns_metadata(self):
        ctx = _needle_context()
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "quixotic configuration", ccr_dir=td)
            self.assertIsNotNone(out.ccr)
            records = list_ccr(td)
            self.assertEqual(len(records), 1)
            rec = records[0]
            self.assertEqual(rec["hash"], out.ccr["hash"])
            self.assertEqual(rec["chars"], len(ctx))
            self.assertIn("stored_at", rec)
            self.assertIn("ttl", rec)
            self.assertEqual(rec["preview"], ctx[:80])

    def test_list_ccr_empty_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(list_ccr(td), [])
            self.assertEqual(list_ccr(td + "/nonexistent"), [])

    def test_retrieve_pagination(self):
        ctx = _needle_context()
        with tempfile.TemporaryDirectory() as td:
            out = compress_context(ctx, "quixotic configuration", ccr_dir=td)
            h = out.ccr["hash"]
            self.assertEqual(retrieve(h, td), ctx)
            self.assertEqual(retrieve(h, td, offset=5), ctx[5:])
            self.assertEqual(retrieve(h, td, limit=10), ctx[:10])
            self.assertEqual(retrieve(h, td, offset=5, limit=10), ctx[5:15])

    def test_list_ccr_limit_offset(self):
        ctx_a = _needle_context()
        ctx_b = _needle_context() + "\n\nextra tail paragraph distinct"
        with tempfile.TemporaryDirectory() as td:
            compress_context(ctx_a, "quixotic configuration", ccr_dir=td)
            compress_context(ctx_b, "quixotic configuration", ccr_dir=td)
            records = list_ccr(td)
            self.assertEqual(len(records), 2)
            self.assertEqual(len(list_ccr(td, limit=1)), 1)
            self.assertEqual(len(list_ccr(td, offset=1)), 1)


class SelectionReceiptTests(unittest.TestCase):
    def test_needle_path_reported(self):
        # Distinctive-selector query (path-like) routes to the needle path.
        out = compress_context(_needle_context(), "/etc/quixotic.conf timeout 42")
        self.assertEqual(out.receipt["selection"], "needle")

    def test_fixed_path_reported(self):
        out = compress_context(
            _needle_context(), "quixotic configuration", mode="fixed"
        )
        self.assertEqual(out.receipt["selection"], "fixed")

    def test_fail_open_records_path(self):
        # A generic query forces the post-selection fail-open gate, but
        # the receipt still reports which selector ran.
        out = compress_context(_needle_context(), "tell me about this")
        self.assertIsNotNone(out.receipt)
        self.assertIn("selection", out.receipt)


class AutoLadderTests(unittest.TestCase):
    def test_auto_returns_extract_when_it_succeeds(self):
        ctx = _needle_context()
        auto = compress_context(
            ctx,
            "quixotic configuration",
            strategy="auto",
            summary_endpoint="http://127.0.0.1:1/",
            summary_timeout=0.2,
        )
        extract = compress_context(ctx, "quixotic configuration")
        self.assertFalse(auto.fail_open)
        self.assertEqual(auto.compressed_text, extract.compressed_text)

    def test_auto_escalates_and_falls_back(self):
        # Generic query: extraction fails open at the post-selection gate,
        # so auto escalates to summarise. The endpoint is unreachable, so
        # summarise falls back to extract — which fails open the same way.
        ctx = _needle_context()
        out = compress_context(
            ctx,
            "tell me about this",
            strategy="auto",
            summary_endpoint="http://127.0.0.1:1/",
            summary_timeout=0.2,
        )
        self.assertTrue(out.fail_open)
        self.assertEqual(out.compressed_text, ctx)

    def test_auto_deterministic(self):
        ctx = _needle_context()
        a = compress_context(
            ctx, "quixotic configuration", strategy="auto",
            summary_endpoint="http://127.0.0.1:1/", summary_timeout=0.2,
        )
        b = compress_context(
            ctx, "quixotic configuration", strategy="auto",
            summary_endpoint="http://127.0.0.1:1/", summary_timeout=0.2,
        )
        self.assertEqual(a.compressed_text, b.compressed_text)

    def test_unknown_strategy_still_raises(self):
        with self.assertRaises(ValueError):
            compress_context(_needle_context(), "q", strategy="bogus")


if __name__ == "__main__":
    unittest.main()
