"""v0.7.0 hardening-pass features: old-error purge, lost-in-the-middle reorder,
structural verbatim invariant, pre-compression inspect gate.

Each test maps to a studied mechanism (see docs/STUDY-NOTES.md).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import (  # noqa: E402
    compress_context,
    estimate_tokens,
)


class OldErrorPurgeTests(unittest.TestCase):
    """Old errored tool dumps are dead weight: keep the fact, drop the bulk."""

    def test_old_error_dump_purged_to_stub(self):
        filler = "\n\n".join(
            f"Archive {i}: routine operational status record." for i in range(12)
        )
        error_dump = (
            "Traceback (most recent call last):\n"
            '  File "/app/service.py", line 88, in handler\n'
            "ConnectionError: upstream timeout after 30s\n"
            + "\n".join(f"  frame {j}: stack detail line {j}" for j in range(20))
        )
        ctx = (
            error_dump
            + "\n\n"
            + filler
            + "\n\nThe fix landed in commit abc123def."
        )
        out = compress_context(ctx, "what fixed the issue?", ccr=False, citations=False)
        # The fact of the error may survive as a citation stub, but the bulk
        # frames must be gone.
        self.assertNotIn("stack detail line 5", out.compressed_text)
        self.assertIn("abc123def", out.compressed_text)

    def test_recent_error_kept_verbatim(self):
        recent_error = (
            "Traceback (most recent call last):\n"
            '  File "/app/live.py", line 7, in run\n'
            "ValueError: bad config value for port\n"
        )
        ctx = recent_error + "\n\n" + "Status: all good otherwise.\n\n" * 8
        out = compress_context(ctx, "why did it crash?", ccr=False, citations=False)
        self.assertIn("ValueError: bad config value for port", out.compressed_text)


class LostInTheMiddleReorderTests(unittest.TestCase):
    """Best kept block anchors the front; second-best anchors the end."""

    def test_reorder_flag_places_best_first_second_best_last(self):
        blocks = []
        for i in range(6):
            blocks.append(
                f"Section {i}: {'needle-alpha' if i == 2 else ''} "
                f"{'needle-beta' if i == 4 else ''} routine padding text {i}."
            )
        ctx = "\n\n".join(blocks)
        out = compress_context(
            ctx, "needle-alpha needle-beta", ccr=False, citations=False,
            reorder_best=True,
        )
        text = out.compressed_text
        pos_a = text.find("needle-alpha")
        pos_b = text.find("needle-beta")
        self.assertGreaterEqual(pos_a, 0)
        self.assertGreaterEqual(pos_b, 0)
        # Mechanism contract: best-scoring block first, second-best last.
        # Scores here: beta 15.7 > alpha 15.63 → beta opens, alpha closes.
        self.assertLess(pos_b, pos_a)

    def test_default_order_unchanged_without_flag(self):
        blocks = [
            f"Entry {i}: marker-{i} plus standard operational content." for i in range(5)
        ]
        ctx = "\n\n".join(blocks)
        out = compress_context(ctx, "marker-1", ccr=False, citations=False)
        self.assertIn("marker-1", out.compressed_text)
        # without the flag, original document order preserved
        i1 = out.compressed_text.find("marker-0")
        i3 = out.compressed_text.find("marker-3")
        if i1 >= 0 and i3 >= 0:
            self.assertLess(i1, i3)


class StructuralVerbatimTests(unittest.TestCase):
    """Fenced code and tracebacks must survive byte-for-byte when kept."""

    def test_fenced_code_block_survives_untouched(self):
        code = (
            "```python\n"
            "def deploy(region: str) -> bool:\n"
            "    return push(f'edge-{region}', timeout=42)\n"
            "```"
        )
        filler = "\n\n".join(f"Log {i}: routine event stream record." for i in range(15))
        ctx = code + "\n\n" + filler
        out = compress_context(ctx, "deploy function edge timeout", ccr=False, citations=False)
        self.assertIn(code, out.compressed_text)

    def test_traceback_block_survives_untouched_when_kept(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/srv/app.py", line 12, in main\n'
            "    start(port=8080)\n"
            "OSError: address already in use"
        )
        filler = "\n\n".join(f"Note {i}: ordinary background chatter." for i in range(15))
        ctx = tb + "\n\n" + filler
        out = compress_context(ctx, "address already in use error", ccr=False, citations=False)
        self.assertIn(tb, out.compressed_text)


class InspectGateTests(unittest.TestCase):
    """Pre-compression check: report whether compression is worth running."""

    def test_inspect_reports_small_payload_not_worth_it(self):
        from tameru.compress_context import inspect_compressibility

        verdict = inspect_compressibility("tiny context", "query")
        self.assertFalse(verdict["worth_it"])

    def test_inspect_reports_highly_repetitive_worth_it(self):
        from tameru.compress_context import inspect_compressibility

        big = "\n\n".join(
            f"Record {i}: user=john action=login status=ok session=abc duration=42ms extra=repeated-field-value"
            for i in range(200)
        )
        verdict = inspect_compressibility(big, "who logged in?")
        self.assertTrue(verdict["worth_it"])
        self.assertGreater(verdict["repetition_ratio"], 0.5)


if __name__ == "__main__":
    unittest.main()
