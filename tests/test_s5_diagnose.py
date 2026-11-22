"""s5_diagnose.py: the tracing wrappers are output-neutral and the sealed split is refused."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.engine_bench import corpus, s5_diagnose  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def eng():
    return s5_diagnose.load_engine(REPO / "src", "1.10.0")


def test_wrappers_output_neutral_on_dev_cases(eng):
    """diagnose_cell verifies byte-identical results wrapped vs unwrapped per call and aborts
    otherwise; completing traced calls here proves neutrality on these dev cases."""
    assignment = corpus.r2_assignment()
    cases = [c for c in corpus._build_r2()
             if assignment[c["id"]] == "dev" and c["item_kind"] in ("csv_args", "s5_buried")][:3]
    for case in cases:
        row = s5_diagnose.diagnose_cell(eng, dict(case, _split="dev"), "deepseek", "tool_call", trace=True)
        assert row["accepted"] in (True, False) and row["gold_total"] >= 1


def test_refuses_sealed():
    rc = s5_diagnose.main(["--engine-src", "src", "--label", "1.10.0", "--split", "sealed",
                           "--out", "build/should-not-exist.json"])
    assert rc == 2
    assert not (REPO / "build" / "should-not-exist.json").exists()
