"""v0.9.0 hardening-pass 2 tests — mechanisms from NTK layer1_filter.rs and
caveman SPEC, applied to Tameru's log preprocessing (TDD: RED first).

Each test cites the source mechanism:
  N1+N2  count-preserving template dedup with idempotent markers
  N4     progress-bar / build-spam line removal
  N6     error-signal post-hoc invariant on log transforms
  N3     Go/Java-style indented frame runs collapse like Python traces
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import compress_context, preprocess_logs


class CountPreservingDedupTests(unittest.TestCase):
    """N1/N2: repeats become one exemplar + count, not silent drops."""

    def test_repeated_log_line_collapses_with_count(self):
        lines = [f"2026-08-24 healthcheck: service ok status=200 req={i}" for i in range(50)]
        out = preprocess_logs(lines)
        joined = "\n".join(out)
        self.assertLess(len(out), 10)
        self.assertIn("×50", joined)  # 49 collapsed copies must be counted

    def test_marker_lines_are_idempotent(self):
        """Re-running preprocess on already-collapsed output must not
        re-collapse the marker's digits into a new group (NTK invariant #5)."""
        lines = [f"2026-08-24 tick seq={i} worker=a" for i in range(6)]
        once = preprocess_logs(lines)
        twice = preprocess_logs(once)
        self.assertEqual("\n".join(once), "\n".join(twice))

    def test_distinct_lines_not_merged(self):
        lines = [
            "2026-08-24 deploy started env=prod",
            "2026-08-24 deploy finished env=staging",
            "2026-08-24 backup completed size=10GB",
        ]
        out = preprocess_logs(lines)
        self.assertEqual(len(out), 3)


class ProgressBarStripTests(unittest.TestCase):
    """N4: progress bars and build spam are noise for an agent."""

    def test_progress_bars_removed(self):
        lines = [
            "Compiling serde v1.0.210",
            "Compiling tokio v1.40.0",
            "Downloading crates...",
            "[====================] 45% (12/27)",
            "error[E0308]: mismatched types",
        ]
        out = preprocess_logs(lines)
        joined = "\n".join(out)
        self.assertNotIn("45%", joined)
        self.assertIn("error[E0308]", joined)  # invariant N6: errors survive

    def test_error_signal_invariant(self):
        """N6: if stripping would remove ALL error lines, keep them."""
        lines = ["ERROR: disk full", "[####----] 20%", "ERROR: retry needed"]
        out = preprocess_logs(lines)
        joined = "\n".join(out)
        self.assertIn("disk full", joined)
        self.assertIn("retry needed", joined)


class FrameRunTests(unittest.TestCase):
    """N3-lite: Go/Java-style frames collapse like our Python trace flush."""

    def test_go_style_frame_run_collapses(self):
        lines = [
            "panic: connection refused",
            "\tgoroutine 1 [running]:",
            "\tmain.handle(/srv/app/handler.go:88)",
            "\tnet/http.(*Server).serve(/usr/local/go/src/net/http/server.go:3210)",
            "\tnet/http.(*conn).serve(/usr/local/go/src/net/http/server.go:1945)",
            "\truntime.goexit(/usr/local/go/src/runtime/asm_amd64.s:1698)",
            "\truntime.main(/usr/local/go/src/runtime/proc.go:267)",
            "\tmain.main(/srv/app/main.go:12)",
            "exit status 2",
        ]
        out = preprocess_logs(lines)
        joined = "\n".join(out)
        self.assertIn("panic: connection refused", joined)
        self.assertIn("frames omitted", joined)
        # preserve_first_frame: where user code entered framework land...
        self.assertIn("goroutine 1 [running]:", joined)
        # ...and the deepest user frame survives (preserve_last_frame).
        self.assertIn("main.main(/srv/app/main.go:12)", joined)


class EndToEndNoRegressionTests(unittest.TestCase):
    def test_query_hit_lines_never_deduped_away(self):
        ctx = (
            "\n\n".join(
                f"2026-08-24 healthcheck: service alpha ok status=200 req={i}"
                for i in range(20)
            )
            + "\n\nThe payment endpoint for Selene is DB-77-Z."
        )
        out = compress_context(ctx, "Selene endpoint?", ccr=False, citations=False)
        self.assertIn("DB-77-Z", out.compressed_text)


if __name__ == "__main__":
    unittest.main()
