import csv
import hashlib
import io
import json
import random

from tameru import folding
from tameru.format_adapters import FormatLimits, _adapt_delimited_outliers


def test_json_brief_matches_baseline_across_shapes_and_budgets():
    outputs = []
    for shape in range(8):
        rows = [
            {
                "row": i,
                "state": "failed" if i == 17 else "ok",
                "padding": chr(97 + i % 20) * (shape * 5 + 7),
                **{f"field{j}": i + j for j in range(shape * 4)},
            }
            for i in range(35)
        ]
        for wrapped in (False, True):
            text = json.dumps({"items": rows, "meta": "kept"} if wrapped else rows, ensure_ascii=False)
            for budget in (0, 80, 250, 500, 900, 1500, 3500):
                for query in ("", "failed row 17"):
                    outputs.append(folding._json_brief(text, budget_chars=budget, query=query))
    digest = hashlib.sha256(json.dumps(outputs, ensure_ascii=False).encode()).hexdigest()
    assert digest == "1ba368e76e41ee2dc22830667396df6c1665cc6f2858a8a9999a0709fc81916d"


def test_json_brief_serializes_its_key_manifest_once(monkeypatch):
    real_dumps = folding._dumps
    manifests = []

    def spy(value):
        if isinstance(value, list) and all(isinstance(key, str) for key in value):
            manifests.append(value)
        return real_dumps(value)

    monkeypatch.setattr(folding, "_dumps", spy)
    text = json.dumps([{"name": f"worker-{i}", "state": "ok"} for i in range(40)])
    assert folding._json_brief(text, budget_chars=800) is not None
    assert manifests == [["name", "state"]]


def test_table_outliers_match_baseline_with_both_line_endings():
    rng = random.Random(241)
    outputs = []
    for kind in range(30):
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\r\n" if kind % 2 else "\n")
        writer.writerow(["name", "state", "latency", "util"])
        for i in range(30):
            writer.writerow([
                f"worker-{i}", "bad" if i == kind % 30 else "ok",
                str(rng.choice([1, 2, 3]) if i != kind % 30 else 50),
                "95%" if i == (kind + 1) % 30 else "5%",
            ])
        for query in ("", "latency", "unrelated needle"):
            outputs.append(_adapt_delimited_outliers(stream.getvalue(), query, FormatLimits(), ",", "csv").to_dict())
    digest = hashlib.sha256(json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert digest == "0b316c91b705c17eb91a4fc490df4a04fbbbb060fbe03850657326f9d6a1a63a"
