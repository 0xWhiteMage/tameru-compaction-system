"""YAML lists and test-runner dumps: drop unmatched records, keep gold."""
from __future__ import annotations

import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"

from tameru.compress_context import compress_context  # noqa: E402


class YamlListAndRunnerTests(unittest.TestCase):
    def test_travis_yaml_keeps_dist_language_drops_unrelated_packages(self):
        ctx = (FIX / "shape-yaml-travis.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx,
            "what apt distro and compiler language is this travis job on?",
            ccr=False,
            citations=False,
        )
        self.assertIn("dist: xenial", out.compressed_text)
        self.assertIn("language: c", out.compressed_text)
        self.assertNotIn("libenchant-dev", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.6)

    def test_vitest_keeps_summary_drops_warning_noise(self):
        ctx = (FIX / "shape-vitest-log.txt").read_text(encoding="utf-8")
        out = compress_context(
            ctx,
            "how many tests passed in the v14 focused node22 run?",
            ccr=False,
            citations=False,
        )
        self.assertIn("21 passed", out.compressed_text)
        self.assertIn("acmecorp-genesis-v14-focused-node22-raw", out.compressed_text)
        self.assertNotIn("ExperimentalWarning", out.compressed_text)
        self.assertLess(len(out.compressed_text), len(ctx) * 0.65)


if __name__ == "__main__":
    unittest.main()
