"""Line-oriented dumps (git log, npm verbose) must drop non-matching records."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"

from tameru.compress_context import compress_context  # noqa: E402


class LineRecordDumpTests(unittest.TestCase):
    def test_git_log_keeps_named_commit_and_saves(self):
        ctx = (FIX / "shape-git-log.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx,
            "which commit stopped deleted profiles coming back?",
            ccr=False,
            citations=False,
        )
        self.assertIn("2038d4034d", out.compressed_text)
        self.assertIn("prevent deleted profile respawn", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.7)
        self.assertNotIn("Inspired by Copilot CLI", out.compressed_text)

    def test_npm_log_keeps_playwright_version_and_saves(self):
        ctx = (FIX / "shape-npm-log.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx,
            "which playwright version did npm exec request?",
            ccr=False,
            citations=False,
        )
        self.assertIn("playwright@1.55.0", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.85)


if __name__ == "__main__":
    unittest.main()
