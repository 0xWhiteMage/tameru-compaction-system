"""P3-3 (E4): the settings-tried ledger gates round-2 runs; r2 validation is refused in
run.py and s5_diagnose.py and reachable only through thresholdout's noisy pass/fail."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.engine_bench import ledger, run, s5_diagnose, thresholdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _ledger(tmp_path, **over):
    d = {
        "schema": 1, "rules": "test", "settings_tried": 2,
        "validation_queries": {"engine": over.pop("used", 0)},
        "validation_query_budget": 20, "noise_seed": 4242,
        "settings": [{"n": 1, "date": "2026-11-21", "target": "engine", "id": "E4",
                      "setting": "x", "split": "r2 dev"},
                     {"n": 2, "date": "2026-11-21", "target": "deepseek-plugin", "id": "G1",
                      "setting": "y", "split": "dev"}],
    }
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- ledger gate


def test_round2_requires_a_setting_or_reference():
    assert run.main(["--round", "2", "--split", "dev", "--quiet"]) == 2
    assert run.main(["--round", "2", "--split", "dev", "--setting", "NOPE", "--quiet"]) == 2


def test_round2_validation_is_refused():
    assert run.main(["--round", "2", "--split", "validation", "--setting", "E4", "--quiet"]) == 2


def test_reference_requires_matching_commit_and_clean_tree(monkeypatch):
    with pytest.raises(ValueError, match="HEAD == that commit"):
        ledger.resolve_provenance(None, "0" * 40, required=True)
    # matching HEAD but dirty tree refuses
    monkeypatch.setattr(ledger, "_worktree_clean", lambda: False)
    head = ledger.engine_commit()
    with pytest.raises(ValueError, match="clean tree"):
        ledger.resolve_provenance(None, head, required=True)
    # a clean worktree at HEAD passes
    monkeypatch.setattr(ledger, "_worktree_clean", lambda: True)
    prov = ledger.resolve_provenance(None, head, required=True)
    assert prov["reference"] == head and prov["engine_commit"] == head


def test_setting_must_target_engine(tmp_path):
    lp = _ledger(tmp_path)
    with pytest.raises(ValueError, match="not an engine setting"):
        ledger.resolve_provenance("G1", None, required=True, ledger_path=lp)
    prov = ledger.resolve_provenance("E4", None, required=True, ledger_path=lp)
    assert prov["setting"] == "E4"


def test_s5_diagnose_requires_setting_and_refuses_validation(tmp_path):
    base = ["--engine-src", "src", "--label", "1.10.0", "--out", str(tmp_path / "x.json")]
    assert s5_diagnose.main(base) == 2                                  # no --setting
    assert s5_diagnose.main(base + ["--setting", "E4", "--split", "validation"]) == 2
    assert s5_diagnose.main(base + ["--setting", "E4", "--split", "sealed"]) == 2


# ----------------------------------------------------------------------------- thresholdout


def _s5_rows(kept: bool) -> list[dict]:
    rows = []
    for i in range(10):
        for profile in ("deepseek", "hermes"):
            rows.append({
                "case": f"r2-x-{i:02d}", "source_case": f"cl-{i}", "split": "validation",
                "item_kind": "s5_buried", "query_condition": "build_vague", "language": "en",
                "profile": profile, "gold_total": 1, "gold_kept": 1.0 if kept else 0.0,
                "saved_pct": 50.0,
            })
    return rows


def test_thresholdout_prints_only_pass_or_fail_and_spends_budget(tmp_path):
    lp = _ledger(tmp_path)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("".join(json.dumps(r) + "\n" for r in _s5_rows(True)), encoding="utf-8")
    argv = ["--setting", "E4", "--gate", "s5_vague_en",
            "--ledger", str(lp), "--r2-rows", str(rows)]
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert thresholdout.main(argv) == 0
    assert buf.getvalue() in ("PASS\n", "FAIL\n")
    led = json.loads(lp.read_text(encoding="utf-8"))
    assert led["validation_queries"]["engine"] == 1
    q = led["validation_query_log"][-1]
    assert q["gate"] == "s5_vague_en" and q["noise_seed"] == 4242


def test_thresholdout_refuses_at_budget(tmp_path):
    lp = _ledger(tmp_path, used=20)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("".join(json.dumps(r) + "\n" for r in _s5_rows(True)), encoding="utf-8")
    assert thresholdout.main(["--setting", "E4", "--gate", "s5_vague_en",
                              "--ledger", str(lp), "--r2-rows", str(rows)]) == 2
    led = json.loads(lp.read_text(encoding="utf-8"))
    assert led["validation_queries"]["engine"] == 20  # unchanged


def test_thresholdout_refuses_unknown_setting(tmp_path):
    lp = _ledger(tmp_path)
    assert thresholdout.main(["--setting", "G1", "--gate", "s5_vague_en",
                              "--ledger", str(lp)]) == 2


def test_thresholdout_fails_when_gold_is_dropped(tmp_path):
    lp = _ledger(tmp_path)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("".join(json.dumps(r) + "\n" for r in _s5_rows(False)), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        thresholdout.main(["--setting", "E4", "--gate", "s5_vague_en",
                           "--ledger", str(lp), "--r2-rows", str(rows)])
    assert buf.getvalue() == "FAIL\n"
