"""Keep timing, repeat-output and unavailable-provider claims honest."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "tameru_comparison", Path(__file__).resolve().parents[1] / "benchmarks/compare.py"
)
compare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)


def test_measure_times_the_complete_call(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(compare.time, "perf_counter", lambda: clock[0])

    def runner(case):
        clock[0] += 0.005  # Scoring work, before the output has been produced.
        return "answer", {}

    row = compare.measure(runner, {"ctx": "context", "q": "query", "gold": ["answer"]}, 3)
    assert row["latency_samples_ms"] == [5.0, 5.0, 5.0]


def test_retention_checks_every_repeat_instead_of_the_best_sample():
    samples = iter(["answer", "answer", "missing", "answer forbidden"])
    row = compare.measure(
        lambda case: (next(samples), {}),
        {"ctx": "context", "gold": ["answer"], "forbid": ["forbidden"]}, 3,
    )
    assert row["gold_kept"] == 0
    assert row["missing_gold"] == ["answer"]
    assert row["leaked_forbid"] == ["forbidden"]
    assert not row["deterministic"]


def test_missing_jev_access_is_unavailable_and_has_no_scores(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    case = {"name": "tiny", "ctx": "answer", "q": "answer", "gold": ["answer"]}
    monkeypatch.setattr(compare, "current_cases", lambda: [case])
    out = tmp_path / "results.json"
    assert compare.main(["--arms", "tameru", "lcc-jev", "--output", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["arms"]["lcc-jev"]["status"] == "unavailable"
    assert report["arms"]["lcc-jev"]["results"] == {}
    assert "common_summary" not in report["arms"]["lcc-jev"]


def test_fallback_is_not_published_as_a_model_measurement(monkeypatch):
    fake = ModuleType("lcc.relevance.compactor")
    fake.RelevanceCompactionRequest = SimpleNamespace
    fake.compact_context = lambda request: SimpleNamespace(
            compacted_text="answer",
            report=SimpleNamespace(degraded=True, provider_used="laya+mechanical_fallback"),
        )
    for name in ("lcc", "lcc.relevance"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, "lcc.relevance.compactor", fake)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    runner = compare.make_runner("lcc-jev", SimpleNamespace(include_jev=True))
    with pytest.raises(RuntimeError, match="Requested jev"):
        runner({"ctx": "answer", "q": "answer"})


def test_incomplete_provider_is_not_rendered_with_a_partial_summary():
    table = compare.comparison_table({"arms": {"lcc-jev": {
        "status": "incomplete", "common_summary": {"gold_kept": 999},
    }}})
    assert "LCC → JEV — unmeasured | — | —" in table
    assert "999" not in table


def test_fully_protected_noop_is_not_mistaken_for_model_fallback(monkeypatch):
    fake = ModuleType("lcc.relevance.compactor")
    fake.RelevanceCompactionRequest = SimpleNamespace
    fake.compact_context = lambda request: SimpleNamespace(
        compacted_text=request.text,
        report=SimpleNamespace(
            degraded=False, provider_used="mechanical", calls=0, blocks_scored=0,
            blocks_total=2, blocks_protected=2, jev_model_resolved=None,
        ),
    )
    for name in ("lcc", "lcc.relevance"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, "lcc.relevance.compactor", fake)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    runner = compare.make_runner("lcc-jev", SimpleNamespace(include_jev=True))
    text, receipt = runner({"ctx": "answer", "q": "answer"})
    assert text == "answer"
    assert receipt["protected_noop"] is True
    assert receipt["scoring_calls"] == 0


def test_resume_refuses_a_different_corpus(monkeypatch, tmp_path):
    case = {"name": "tiny", "ctx": "answer", "q": "answer", "gold": ["answer"]}
    monkeypatch.setattr(compare, "current_cases", lambda: [case])
    out = tmp_path / "results.json"
    assert compare.main(["--arms", "tameru", "--output", str(out)]) == 0
    monkeypatch.setattr(compare, "current_cases", lambda: [{**case, "q": "changed task"}])
    with pytest.raises(ValueError, match="corpus_sha256 changed"):
        compare.main(["--arms", "tameru", "--output", str(out), "--resume"])
