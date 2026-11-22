"""The round-2 analysis plan is hash-pinned and the settings-tried ledger starts at 26."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
BURNED = "ac9e77dd723d3755b8238c4a1e60d6947e798ddcc0ee489e9d2c10f2b5ca1489"


def test_plan_matches_its_registered_hash():
    text = (DOCS / "ANALYSIS-PLAN-ROUND2.md").read_bytes().replace(b"\r\n", b"\n")
    registered = [line.split()[0] for line in (DOCS / "ANALYSIS-PLAN-ROUND2.sha256").read_text(encoding="utf-8").splitlines() if line.strip()]
    # amendments append a new hash; the current file matches the last one
    assert hashlib.sha256(text).hexdigest() == registered[-1]
    assert BURNED.encode() in text
    assert b"No gate is added or widened after this file's hash is committed" in text


def test_ledger_starts_at_26_and_counts_its_entries():
    ledger = json.loads((DOCS / "SETTINGS-TRIED-LEDGER.json").read_text(encoding="utf-8"))
    settings = ledger["settings"]
    assert ledger["settings_tried"] == len(settings) >= 26
    assert [s["n"] for s in settings] == list(range(1, len(settings) + 1))
    assert len({s["id"] for s in settings}) == len(settings)
    assert ledger["validation_query_budget"] == 20
    assert all(0 <= v <= 20 for v in ledger["validation_queries"].values())
