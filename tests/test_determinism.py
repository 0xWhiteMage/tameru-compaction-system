"""``compress_context`` is deterministic: the same input gives the same bytes under any
``PYTHONHASHSEED``. The probe runs in a real subprocess per seed so hash-order differences
cannot hide inside this process's ordering."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "determinism_probe.py"
SEEDS = ("0", "1", "2", "3", "42", "1234")


def _run_probe(seed: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT)] + env.get("PYTHONPATH", "").split(os.pathsep)
    )
    proc = subprocess.run(
        [sys.executable, str(PROBE)], capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.mark.perf
def test_compress_context_is_seed_independent():
    runs = {seed: _run_probe(seed) for seed in SEEDS}
    base = runs[SEEDS[0]]
    assert len(base) > 200  # musubi q0-q8 x options + r2 dev S5 cases, both profiles
    for seed in SEEDS[1:]:
        diff = [k for k in set(base) | set(runs[seed]) if base.get(k) != runs[seed].get(k)]
        assert not diff, f"output differs under PYTHONHASHSEED={seed} for {len(diff)} cells: {diff[:10]}"
