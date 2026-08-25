"""Production QA v3: savings, temporal supersession, performance and determinism."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"

from tameru.compress_context import compress_context  # noqa: E402


def _archive(n: int = 30) -> str:
    return "\n\n".join(
        f"Routine archive section {i}: ordinary status record with no relevant operational facts."
        for i in range(n)
    )


class SavingsCollapseTests(unittest.TestCase):
    """v0.5.19 finding: trust-risk presence nuked a correct small selection."""

    def test_lexical_distractor_keeps_evidence_and_savings(self):
        ctx = (
            _archive()
            + "\n\nThe Moonlight operation is codenamed Selene.\n\nSelene failover endpoint is DB-77-Z.\n\n"
            + _archive()
            + "\n\nThe lunar warehouse backup host phrase appears here, but this obsolete glossary entry is unrelated."
        )
        out = compress_context(ctx, "What is the backup host for the lunar warehouse?", ccr=False, citations=False)
        self.assertIn("DB-77-Z", out.compressed_text)
        self.assertNotIn("glossary", out.compressed_text)
        self.assertGreater(out.tokens_saved_pct, 60.0, f"savings collapsed to {out.tokens_saved_pct}%")
        self.assertFalse(out.fail_open)


class SupersessionTests(unittest.TestCase):
    """Stale standalone fact lines must yield to explicit newer overrides."""

    def test_current_value_drops_stale_config_line(self):
        ctx = (
            _archive(10)
            + "\n\n2026-08-01 config: payment timeout is 30 seconds.\n\n"
            + _archive(10)
            + "\n\n2026-08-19 change: payment timeout is now 5 seconds; 30 seconds is obsolete."
        )
        out = compress_context(ctx, "What is the current payment timeout?", ccr=False, citations=False)
        self.assertIn("5 seconds", out.compressed_text)
        self.assertNotIn("config: payment timeout is 30 seconds", out.compressed_text)

    def test_negation_override_drops_stale_runbook_line(self):
        ctx = (
            _archive(10)
            + "\n\nEarlier runbook: feature Falcon is enabled.\n\n"
            + _archive(10)
            + "\n\nCurrent override: feature Falcon is not enabled."
        )
        out = compress_context(ctx, "Is feature Falcon enabled now?", ccr=False, citations=False)
        self.assertIn("not enabled", out.compressed_text)
        self.assertNotIn("runbook: feature Falcon is enabled", out.compressed_text)

    def test_no_supersession_marker_keeps_both_lines(self):
        """Without an explicit override marker, both lines survive (conservative)."""
        ctx = (
            _archive(10)
            + "\n\n2026-08-01 config: payment timeout is 30 seconds.\n\n"
            + _archive(10)
            + "\n\n2026-08-19 note: payment timeout was audited today."
        )
        out = compress_context(ctx, "What is the payment timeout?", ccr=False, citations=False)
        self.assertIn("30 seconds", out.compressed_text)


class PerformanceTests(unittest.TestCase):
    """Fast and light: large-document latency budget."""

    def test_large_doc_under_budget(self):
        import statistics
        import time

        rows = [
            f"Log entry {i}: service module_{i % 97} emitted status code {1000 + i} after {i}ms. "
            f"The deploy pipeline for region-{i % 13} completed stage {i % 9}."
            for i in range(4000)
        ]
        small = "\n\n".join(rows[:2000])
        big = "\n\n".join(rows)

        def measure(text: str) -> tuple[float, object]:
            samples = []
            result = None
            for _ in range(3):
                t0 = time.process_time()
                result = compress_context(
                    text,
                    "which region completed stage 3?",
                    ccr=False,
                    citations=False,
                )
                samples.append((time.process_time() - t0) * 1000)
            return statistics.median(samples), result

        small_ms, _small_out = measure(small)
        big_ms, out = measure(big)
        self.assertLess(
            big_ms,
            1200.0,
            f"{len(big) / 1024:.0f}KiB document median CPU time was {big_ms:.0f}ms",
        )
        self.assertLess(
            big_ms / max(small_ms, 1.0),
            3.2,
            f"doubling input scaled CPU time from {small_ms:.0f}ms to {big_ms:.0f}ms",
        )
        self.assertGreater(out.tokens_saved_pct, 90.0)


class DeterminismTests(unittest.TestCase):
    """Same input + different hash seed => byte-identical output."""

    def test_byte_identical_across_hash_seeds(self):
        import os
        import subprocess

        script = (
            "import tameru.compress_context as m;"
            "from pathlib import Path;"
            "ctx=Path(%r).read_text(encoding='utf-8');"
            "out=m.compress_context(ctx,'which commit stopped deleted profiles coming back?',ccr=False,citations=False);"
            "print(out.compressed_text)"
            % (str(FIX / "shape-git-log.txt"),)
        )
        outs = []
        for seed in ("0", "1"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH="src")
            r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            outs.append(r.stdout)
        self.assertEqual(outs[0], outs[1], "output differs across hash seeds")


class EscapedJsonDumpTests(unittest.TestCase):
    """Real-world gauntlet finding (2026-08-25): tool dumps arrive as JSON
    strings whose values contain LITERAL \n escapes. preprocess_json keeps
    them on one line, segment_blocks yields a single mega-block, and the
    saturation guard fails open at 0% savings. Unwrap literal escapes before
    segmentation."""

    def test_escaped_newline_json_dump_compresses(self):
        import json as _json
        inner = "\n".join(
            f"2026-08-2{i} Etiqa policy {i}: recycling balance {1000+i} units" for i in range(30)
        )
        ctx = _json.dumps({"output": "====\nUTMOST VISION breakdown\n====\n" + inner})
        out = compress_context(
            ctx,
            "What is the recycling balance for Etiqa policy 17?",
            citations=True,
            ccr=False,
        )
        self.assertFalse(out.fail_open)
        self.assertIn("recycling balance 1017 units", out.compressed_text)
        self.assertGreater(getattr(out, "tokens_saved_pct", 0) or 0, 30)

    def test_unrelated_query_still_fail_open_on_escaped_dump(self):
        import json as _json
        inner = "\n".join(f"log line {i}: ok status 200" for i in range(40))
        ctx = _json.dumps({"output": inner})
        out = compress_context(ctx, "unrelated query about quantum flux", citations=True)
        # weak signal must still fail open - no behaviour change for safety
        self.assertTrue(out.fail_open)


if __name__ == "__main__":
    unittest.main()
