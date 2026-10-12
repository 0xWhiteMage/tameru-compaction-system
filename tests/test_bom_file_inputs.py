"""BOM-prefixed UTF-8 files remain usable for CLI input and recovery storage."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tameru.compress_context import compress_context, list_ccr, retrieve, sweep_ccr_cache


@pytest.mark.parametrize("operation", ["retrieve", "list", "sweep"])
def test_bom_recovery_record_keeps_public_recovery_and_expiry_working(tmp_path, operation):
    source = "\n\n".join(["Routine archive status with no operational facts."] * 50)
    source += "\n\nThe active host is DB-PROD-42."
    result = compress_context(source, "What is the active host?", ccr_dir=tmp_path)
    assert result.ccr is not None
    key = result.ccr["hash"]
    record = tmp_path / f"{key}.json"
    metadata = json.loads(record.read_text())
    record.write_bytes(b"\xef\xbb\xbf" + record.read_bytes())

    if operation == "retrieve":
        assert retrieve(key, tmp_path) == source
    elif operation == "list":
        assert key in {row["hash"] for row in list_ccr(tmp_path)}
    else:
        assert sweep_ccr_cache(tmp_path, now=metadata["stored_at"] + metadata["ttl"] + 1) == 1
        assert not record.exists()


def test_cli_accepts_bom_utf8_input_without_leaking_the_file_marker(tmp_path):
    source = "The active host is DB-PROD-42."
    context = tmp_path / "context.txt"
    context.write_text(source, encoding="utf-8-sig")
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "-m", "tameru.compress_context", str(context), "", "--no-ccr", "--no-citations"],
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        capture_output=True, text=True, check=True,
    )
    assert done.stdout == source + "\n"
