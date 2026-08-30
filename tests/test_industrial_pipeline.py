"""Industrial preflight, limits, and pipeline integration contracts."""
from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tameru.compress_context import compress_context, main
from tameru.industrial import IndustrialLimits, industrial_preprocess, profile_input


class IndustrialLimitTests(unittest.TestCase):
    def test_malformed_claimed_structure_fails_open_before_ccr(self):
        lines = [json.dumps({"id": i, "msg": f"noise-{i}"}) for i in range(30)]
        lines.insert(10, "not-json-but-shares-target-77")
        lines.insert(20, json.dumps({"id": 77, "msg": "target-77"}))
        source = "\n".join(lines)
        with tempfile.TemporaryDirectory() as directory:
            result = compress_context(
                source,
                "target-77",
                ccr=True,
                citations=True,
                ccr_dir=directory,
            )
            self.assertTrue(result.fail_open)
            self.assertEqual(result.compressed_text, source)
            self.assertIn("malformed JSON record", " ".join(result.reasons))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_character_limit_fails_open_exactly_and_writes_no_ccr(self):
        source = "line one\r\nline two\r\ncritical-value-77"
        limits = IndustrialLimits(max_input_chars=10)
        with tempfile.TemporaryDirectory() as directory:
            result = compress_context(
                source,
                "critical-value-77",
                limits=limits,
                ccr=True,
                ccr_dir=directory,
            )
            self.assertTrue(result.fail_open)
            self.assertEqual(result.compressed_text, source)
            self.assertIn("character limit", " ".join(result.reasons))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_excessive_bidi_overrides_fail_open_exactly(self):
        source = "safe\u202eabc\u202c\u202eabc\u202c\u202eabc\u202ctail"
        result = compress_context(
            source,
            "abc",
            ccr=False,
            citations=False,
            limits=IndustrialLimits(max_bidi_overrides=2),
        )
        self.assertTrue(result.fail_open)
        self.assertEqual(result.compressed_text, source)
        self.assertIn("bidi override limit", result.reasons[0])

    def test_line_limit_fails_open(self):
        source = "\n".join(f"record-{index}" for index in range(20))
        result = compress_context(
            source,
            "record-19",
            limits=IndustrialLimits(max_lines=10),
            ccr=False,
        )
        self.assertTrue(result.fail_open)
        self.assertEqual(result.compressed_text, source)
        self.assertIn("line limit", " ".join(result.reasons))

    def test_invalid_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_input_chars"):
            IndustrialLimits(max_input_chars=0)


class IndustrialProfileTests(unittest.TestCase):
    def test_profile_is_deterministic_and_bounded(self):
        source = ("abc אבג مرحبا\n" * 200) + "widget-77"
        limits = IndustrialLimits(max_profile_chars=128)
        first = profile_input(source, limits)
        second = profile_input(source, limits)
        self.assertEqual(first, second)
        self.assertTrue(first.profile_truncated)
        self.assertLessEqual(first.sampled_chars, 256)
        self.assertEqual(first.direction, "mixed")
        self.assertIn("hebrew", first.scripts)
        self.assertIn("arabic", first.scripts)

    def test_preprocess_declines_malformed_surrogate(self):
        source = "prefix\ud800suffix"
        result = industrial_preprocess(source, "suffix")
        self.assertTrue(result.hard_fail_open)
        self.assertIn("surrogate", result.reason)
        self.assertEqual(result.text, source)


class IndustrialPipelineTests(unittest.TestCase):
    def test_ndjson_adapter_runs_end_to_end_and_is_receipted(self):
        lines = [
            json.dumps({"id": index, "device": f"device-{index}", "status": "ok"})
            for index in range(100)
        ]
        source = "\n".join(lines)
        result = compress_context(source, "device-77", ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertIn("device-77", result.compressed_text)
        self.assertNotIn("device-120", result.compressed_text)
        self.assertLess(len(result.compressed_text), len(source) // 4)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        industrial = result.receipt["industrial"]
        self.assertEqual(industrial["profile"]["format"], "ndjson")
        self.assertTrue(industrial["format_result"]["applied"])
        self.assertEqual(industrial["format_result"]["kept_records"], 1)

    def test_compaction_log_records_industrial_profile(self):
        source = "\n".join(
            json.dumps({"id": index, "device": f"device-{index}"})
            for index in range(100)
        )
        with tempfile.TemporaryDirectory() as td:
            compress_context(
                source,
                "device-77",
                ccr=False,
                citations=False,
                log_dir=td,
            )
            record = json.loads(
                (Path(td) / "compactions.jsonl").read_text(encoding="utf-8")
            )
        self.assertEqual(record["industrial_format"], "ndjson")
        self.assertTrue(record["industrial_applied"])
        self.assertEqual(record["direction"], "ltr")
        self.assertIn("latin", record["scripts"])
        self.assertEqual(record["input_lines"], 100)

    def test_quoted_csv_adapter_runs_end_to_end(self):
        source = (
            'id,name,notes\r\n'
            '1,alpha,"ordinary, record"\r\n'
            '77,target,"first line\r\nsecond line device-77"\r\n'
            '120,other,"device-120"\r\n'
        )
        result = compress_context(source, "device-77", ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertIn("device-77", result.compressed_text)
        self.assertNotIn("device-120", result.compressed_text)
        self.assertEqual(result.content_type, "csv")

    def test_vertical_ocr_adapter_runs_end_to_end(self):
        source = "東\n京\n都\n庁\n舎\n\n大\n阪\n支\n店\n案\n内"
        result = compress_context(source, "東京都庁舎", ccr=False, citations=False)
        self.assertFalse(result.fail_open)
        self.assertIn("東\n京\n都\n庁\n舎", result.compressed_text)
        self.assertNotIn("大阪", result.compressed_text.replace("\n", ""))
        self.assertEqual(result.content_type, "vertical")

    def test_cli_exposes_precision_mode_and_hard_limits(self):
        source = "exact caller bytes"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "context.txt"
            path.write_text(source, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        str(path),
                        "caller",
                        "--mode",
                        "precision",
                        "--max-input-chars",
                        "4",
                        "--no-ccr",
                        "--no-citations",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue().rstrip("\n"), source)


if __name__ == "__main__":
    unittest.main()
