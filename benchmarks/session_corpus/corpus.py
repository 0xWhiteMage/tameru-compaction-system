"""Splits, scenario export, canonical hashing and the holdout guard of the session corpus.

* Families are dealt to dev / validation / holdout by a logged seed (``deal``); the eight round-1 families (the burned
  round-1 DeepSeek holdout) are dev material and are pinned to dev.  A scenario never leaves its family's split.
* ``scenarios(split, ...)`` yields exported scenarios (SCHEMA.md).  The holdout is refused unless ``holdout=True`` and a
  candidate name are given; such a read first checks SEALED-HOLDOUT.sha256 and appends to holdout_looks.json.
* ``_plans`` is internal: it returns plans (no output text) of any split, for split.py (the sealed hash) and
  equivalence.py (descriptors only).  Nothing else may call it for the holdout.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

from . import generator as g
from . import real as realmod
from .families import FAMILIES, FAMILY_BY_ID

HERE = Path(__file__).resolve().parent
SPLITS_FILE = HERE / "splits.json"
SEALED_HASH_FILE = HERE / "SEALED-HOLDOUT.sha256"
LOOKS_FILE = HERE / "holdout_looks.json"
SPLITS = ("dev", "validation", "holdout")
DEV_RANDOM, VALIDATION_FAMILIES = 4, 8          # dev = the 8 pinned round-1 families + 4 dealt; the rest go to holdout
BURNED_ROUND1_HOLDOUT_SHA256 = "ac9e77dd723d3755b8238c4a1e60d6947e798ddcc0ee489e9d2c10f2b5ca1489"
BURNED_ROUND1_FAMILIES = {"pytest-zh": "pytest", "maven-en": "maven", "kubectl-zh": "kubectl", "sql-en": "sql",
                          "jest-en": "jest", "gotest-zh": "gotest", "cargo-en": "cargo", "metrics-zh": "metrics"}


class HoldoutAccessError(RuntimeError):
    """Raised when holdout scenarios are requested without --holdout --candidate NAME."""


# ------------------------------------------------------------------------------------------------ splits
def deal(seed: str) -> dict[str, str]:
    pinned = sorted(f.id for f in FAMILIES if f.burned_round1)
    rest = sorted(f.id for f in FAMILIES if not f.burned_round1)
    r = g.rng(f"deal:{seed}")
    r.shuffle(rest)
    out = {fid: "dev" for fid in pinned}
    for i, fid in enumerate(rest):
        out[fid] = "dev" if i < DEV_RANDOM else "validation" if i < DEV_RANDOM + VALIDATION_FAMILIES else "holdout"
    return dict(sorted(out.items()))


def splits_doc(seed: str, attempt: int) -> dict:
    fams = deal(seed)
    counts = {s: {"families": sum(v == s for v in fams.values()),
                  "scenarios": g.SCENARIOS_PER_FAMILY * sum(v == s for v in fams.values())} for s in SPLITS}
    manifest = realmod.load_manifest()
    return {
        "generator": g.GENERATOR_VERSION,
        "deal": {"seed": seed, "attempt": attempt,
                 "rule": (f"the {len(BURNED_ROUND1_FAMILIES)} round-1 families are pinned to dev; the others, sorted by id, are "
                          f"shuffled by random.Random(sha256('deal:'+seed)) and dealt {DEV_RANDOM} to dev, {VALIDATION_FAMILIES} "
                          "to validation, the rest to holdout")},
        "burned_round1": {"holdout_sha256": BURNED_ROUND1_HOLDOUT_SHA256, "families": BURNED_ROUND1_FAMILIES,
                          "note": "the burned round-1 DeepSeek holdout's families are dev material; reproduced here and pinned to dev"},
        "scenarios_per_family": g.SCENARIOS_PER_FAMILY,
        "families": fams,
        "counts": counts,
        "real_pools": manifest["repo_splits"],
    }


def splits_blob(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_splits() -> dict:
    return json.loads(SPLITS_FILE.read_text(encoding="utf-8"))


def family_split() -> dict[str, str]:
    return load_splits()["families"]


# ------------------------------------------------------------------------------------------------ plans and export
def _plans(split: str, assignment: dict[str, str] | None = None, manifest: dict | None = None) -> list[g.Plan]:
    """INTERNAL: plans (no output text) of a split, any split.  Only split.py and equivalence.py use it for the holdout."""
    assignment = assignment or family_split()
    manifest = manifest or realmod.load_manifest()
    pool = realmod.pool_for(split, manifest)
    return [g.plan(fid, i, pool, split) for fid in sorted(f for f, s in assignment.items() if s == split)
            for i in range(g.SCENARIOS_PER_FAMILY)]


def _windows_table(p: g.Plan) -> dict:
    out = {}
    for w in g.WINDOWS:
        n = p.windows[w]
        out[str(w)] = {"steps": n, "chars": sum(p.chars[:n]), "trigger_tokens": {"deepseek": g.ds_trigger(w), "hermes": g.hermes_trigger(w)}}
    return out


def _step_kind(p: g.Plan, facts: list[dict], i: int) -> str:
    if p.real_ids[i] is not None:
        return "real"
    if any(f["kind"] == "error" for f in facts):
        return "error"
    return "fact" if facts else "filler"


def export_step(p: g.Plan, i: int, real, *, text_hash_only: bool = False) -> dict:
    text, facts = g.step_text(p, i, real)
    tool, args = g.step_call(p, i, real)
    for f in facts:
        if f["kind"] == "stale":
            f["superseded"] = True
    step = {"index": i, "tool": tool, "args": args, "kind": _step_kind(p, facts, i), "chars": len(text), "planned_chars": p.chars[i],
            "facts": facts}
    if p.real_ids[i] is not None:
        step["source"] = p.real_ids[i]
    if text_hash_only:
        step["output_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    else:
        step["output_text"] = text
    return step


def export_head(p: g.Plan, real) -> dict:
    fam = p.family
    return {
        "schema": 1, "generator": g.GENERATOR_VERSION, "id": p.id, "family": fam.id, "index": p.index, "seed": p.seed,
        "language": p.language, "task_style": p.style, "task": g.task_text(p),
        "parameters": {"tool": fam.tool, "median_chars": fam.median_chars, "length_factor": p.factor, "real_pool": p.pool,
                       "real_share_target": g.REAL_SHARE_TARGET, "scenarios_per_family": g.SCENARIOS_PER_FAMILY,
                       "chars_per_token": g.CHARS_PER_TOKEN},
        "windows": _windows_table(p),
        "questions": g.questions(p, real),
    }


def export(p: g.Plan, real, window: int | None = None) -> dict:
    head = export_head(p, real)
    n = p.windows[window] if window else len(p.chars)
    if window:
        head["questions"] = [q for q in head["questions"] if q["first_window"] <= window]
        head["sliced_to_window"] = window
    head["steps"] = [export_step(p, i, real) for i in range(n)]
    return head


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scenario_digest(p: g.Plan, real) -> str:
    """sha256 of the canonical full scenario with each output text replaced by its sha256 (same content, streamable)."""
    head = export_head(p, real)
    h = hashlib.sha256(canonical(head).encode("utf-8"))
    for i in range(len(p.chars)):
        h.update(b"\n")
        h.update(canonical(export_step(p, i, real, text_hash_only=True)).encode("utf-8"))
    return h.hexdigest()


def split_digest(plans: list[g.Plan], real) -> str:
    rows = sorted([p.id, scenario_digest(p, real)] for p in plans)
    return hashlib.sha256(canonical(rows).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ loader
def _log_look(candidate: str, command: str) -> None:
    looks = json.loads(LOOKS_FILE.read_text(encoding="utf-8")) if LOOKS_FILE.exists() else []
    looks.append({"date": datetime.date.today().isoformat(), "generator": g.GENERATOR_VERSION, "candidate": candidate,
                  "sealed_sha256": SEALED_HASH_FILE.read_text().split()[0], "command": command})
    LOOKS_FILE.write_text(json.dumps(looks, indent=1) + "\n", encoding="utf-8", newline="\n")


def scenarios(split: str, *, holdout: bool = False, candidate: str | None = None, squeez: Path | None = None,
              window: int | None = None, command: str = ""):
    """Yield exported scenarios of one split.  The holdout needs holdout=True and a candidate (one look, logged)."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    if split == "holdout":
        if not holdout or not candidate:
            raise HoldoutAccessError("the holdout may only be read with --holdout --candidate NAME (one look, logged)")
    plans = _plans(split)
    real = realmod.RealTexts(squeez)
    if split == "holdout":
        if split_digest(plans, real) != SEALED_HASH_FILE.read_text().split()[0]:
            raise HoldoutAccessError("holdout scenarios no longer match SEALED-HOLDOUT.sha256")
        _log_look(candidate, command or f"scenarios('holdout', candidate={candidate!r})")
    for p in plans:
        yield export(p, real, window)


def all_family_ids() -> list[str]:
    return sorted(FAMILY_BY_ID)
