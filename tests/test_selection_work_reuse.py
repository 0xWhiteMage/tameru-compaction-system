import hashlib
import json

from tameru import folding


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
