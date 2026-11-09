"""``compress_context`` produces byte-identical results for a fixed corpus (a safety net for refactors; see golden_compress)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from golden_compress import capture

GOLDEN = Path(__file__).resolve().parent / "golden" / "compress_context.json"


def test_compress_context_output_is_unchanged(tmp_path):
    got = capture(tmp_path / "ccr")
    if os.environ.get("TAMERU_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    changed = sorted(key for key in set(got) | set(want) if got.get(key) != want.get(key))
    assert not changed, (
        f"compress_context output changed for {len(changed)} of {len(want)} corpus entries (first: {changed[:5]}). If the change is "
        "intended, regenerate with TAMERU_WRITE_GOLDEN=1 and review the diff of tests/golden/compress_context.json."
    )
