"""Settings-tried ledger enforcement for the round-2 engine bench (plan section 8).

A tuning run of this tree must name either ``--setting ID`` — an id listed in
``docs/SETTINGS-TRIED-LEDGER.json`` with ``target: engine`` — or ``--reference COMMIT``,
which is allowed only when the running checkout's HEAD equals COMMIT and its tree is
clean (a worktree reference run, e.g. the stored 1.10.0 baseline). Every row records the
setting or reference and the engine commit. Round-2 runs see dev only: ``--split
validation`` is refused; validation is queried solely through ``thresholdout.py``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_PATH = HERE.parents[1] / "docs" / "SETTINGS-TRIED-LEDGER.json"


def load_ledger(path: Path | None = None) -> dict:
    return json.loads((path or LEDGER_PATH).read_text(encoding="utf-8"))


def engine_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _worktree_clean() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    return not out.stdout.strip()


def engine_setting_ids(ledger: dict) -> set[str]:
    return {s["id"] for s in ledger.get("settings", []) if s.get("target") == "engine"}


def resolve_provenance(
    setting: str | None,
    reference: str | None,
    *,
    required: bool,
    ledger_path: Path | None = None,
) -> dict:
    """Validate ``--setting``/``--reference``. Returns the row provenance fields
    (``setting`` or ``reference``, plus ``engine_commit``) or raises ``SystemExit``-style
    ``ValueError`` with the refusal message — callers print it and exit 2."""
    if setting and reference:
        raise ValueError("pass --setting OR --reference, not both")
    if required and not setting and not reference:
        raise ValueError(
            "refusing: a round-2 run of this tree requires --setting ID (an engine setting "
            "in docs/SETTINGS-TRIED-LEDGER.json) or --reference COMMIT for a clean worktree run"
        )
    prov = {"engine_commit": engine_commit()}
    if setting:
        ids = engine_setting_ids(load_ledger(ledger_path))
        if setting not in ids:
            raise ValueError(
                f"refusing: setting {setting!r} is not an engine setting in "
                f"docs/SETTINGS-TRIED-LEDGER.json (engine ids: {sorted(ids) or 'none'})"
            )
        prov["setting"] = setting
    if reference:
        head = prov["engine_commit"]
        if not head.startswith(reference):
            raise ValueError(
                f"refusing: --reference {reference} requires HEAD == that commit "
                f"(HEAD is {head[:10]}) — run reference benches from a clean worktree"
            )
        if not _worktree_clean():
            raise ValueError(
                "refusing: --reference requires a clean tree (uncommitted changes would "
                "mislabel the rows) — run reference benches from a clean worktree"
            )
        prov["reference"] = reference
    return prov


def refuse_or_return(message: str | None) -> int:
    if message:
        print(f"refusing: {message}", file=sys.stderr)
        return 2
    return 0
