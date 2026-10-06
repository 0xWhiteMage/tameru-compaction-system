"""Regression tests from the WS-FORMATS adversarial review."""
from __future__ import annotations

import time
import unittest

from tameru.agent_formats import (
    adapt_grep_lines,
    adapt_unified_diff,
    apply_agent_adapters,
    detect_test_runner,
    is_numbered_code,
    preprocess_test_output,
)
from tameru.compress_context import compress_context
from tameru.format_adapters import detect_format


def _diff(nfiles: int = 3, nhunks: int = 12) -> str:
    out: list[str] = []
    for f in range(nfiles):
        out += [f"diff --git a/m{f}.py b/m{f}.py", f"--- a/m{f}.py", f"+++ b/m{f}.py"]
        for h in range(nhunks):
            s = h * 20 + 1
            out += [f"@@ -{s},3 +{s},3 @@", " a", f"-old_{f}_{h}", f"+new_{f}_{h}", " b"]
    return "\n".join(out) + "\n"


def _grep(files: int = 10, per: int = 30) -> str:
    return "\n".join(
        f"src/mod{f}.py:{m * 3 + 1}:    value_{f}_{m} = compute(x)  # TODO"
        for f in range(files)
        for m in range(per)
    )


class TestRunnerDetectionIsLinear(unittest.TestCase):
    def test_long_line_of_passed_fragments_is_not_cubic(self):
        # `=== ` + many "N passed in Ns" made the old whole-text regex cubic
        # (16 KB took 11 s).
        text = "=== " + "1 passed in 1s " * 4000
        started = time.perf_counter()
        self.assertIsNone(detect_test_runner(text))
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_wide_pytest_banner_still_detected(self):
        head = "=" * 40 + " test session starts " + "=" * 40
        self.assertEqual(detect_test_runner(head + "\ncollected 1 item\n"), "pytest")


class PytestProgressFailures(unittest.TestCase):
    def test_progress_lines_with_f_or_e_are_kept(self):
        text = (
            "=" * 30 + " test session starts " + "=" * 30 + "\n"
            "collected 40 items\n\n"
            "tests/test_a.py ....F.....   [ 25%]\n"
            "tests/test_b.py ..........E.   [ 50%]\n"
            "tests/test_c.py ..........   [ 75%]\n"
            "tests/test_d.py ..........   [100%]\n\n"
            "=" * 20 + " 1 failed, 1 error, 38 passed in 0.50s " + "=" * 20 + "\n"
        )
        out = preprocess_test_output(text, "")
        self.assertIsNotNone(out)
        self.assertIn("tests/test_a.py ....F", out)
        self.assertIn("tests/test_b.py ..........E", out)
        self.assertIn("20 passing tests omitted", out)


class NoSelectorHitLicensesNoCut(unittest.TestCase):
    def test_diff_with_absent_query_term_fails_open(self):
        text = _diff()
        res = compress_context(text, "frobnicate_widget zzz_missing", ccr=False)
        self.assertEqual(res.compressed_text, text)
        self.assertIsNone((res.receipt or {}).get("adapter"))

    def test_grep_with_absent_query_term_fails_open(self):
        text = _grep()
        res = compress_context(text, "frobnicate_widget zzz_missing", ccr=False)
        self.assertEqual(res.compressed_text, text)

    def test_adapters_still_orient_direct_callers(self):
        out = adapt_unified_diff(_diff(), "frobnicate_widget")
        self.assertIsNotNone(out)
        self.assertFalse(out.hit)
        self.assertLess(out.kept_records, out.total_records)
        text, info = apply_agent_adapters(_diff(), "frobnicate_widget")
        self.assertIsNone(info)
        g = adapt_grep_lines(_grep(), "frobnicate_widget")
        self.assertIsNotNone(g)
        self.assertFalse(g.hit)

    def test_hit_still_cuts(self):
        res = compress_context(_diff(), "new_1_5", ccr=False)
        self.assertLess(len(res.compressed_text), len(_diff()))
        self.assertIn("+new_1_5", res.compressed_text)
        self.assertEqual((res.receipt or {})["adapter"]["name"], "diff")


class NumberedReadEdges(unittest.TestCase):
    def test_tab_indented_code_is_not_a_tsv(self):
        flat = "\n".join(f"{i + 1:6d}\t\tx{i} := call(a)" for i in range(300))
        self.assertTrue(is_numbered_code(flat))
        self.assertEqual(detect_format(flat), "numbered_code")

    def test_real_numbered_tsv_is_still_a_table(self):
        tsv = "\n".join(f"{i}\tuser{i}\t{20 + i % 50}" for i in range(50))
        self.assertFalse(is_numbered_code(tsv))

    def test_colon_gutter_read_is_not_high_risk(self):
        code = "\n".join(
            f"def handler_{i}(req):\n    return req.get('k{i}', {i})\n" for i in range(150)
        )
        read = "\n".join(f"{i + 1}: {ln}" for i, ln in enumerate(code.split("\n")))
        res = compress_context(read, "what does handler_100 do?", ccr=False)
        self.assertIn("handler_100", res.compressed_text)
        self.assertNotEqual(res.compression_risk, "high")
        self.assertLess(res.verifier["critical_lines_total"], 50)


class CsvKeywordColumn(unittest.TestCase):
    def test_csv_whose_first_column_is_a_keyword_is_still_csv(self):
        rows = "\n".join(f"public,{i},{i * 2}" for i in range(40))
        text = "scope,a,b\n" + rows
        self.assertEqual(detect_format(text), "csv")


if __name__ == "__main__":
    unittest.main()
