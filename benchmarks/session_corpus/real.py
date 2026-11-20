"""Real tool outputs (Squeez / SWE-bench) reused as ``kind: real`` steps, and their manifest.

The dataset file stays out of git.  ``manifest.json`` (committed) records, per output used, its origin, licence, id,
sha256, size, gold line spans (numbers only) and redaction, so a rebuild can prove it is byte-identical; it holds no
output text.  Pools are by REPOSITORY: an output's repository decides which splits may use it (see ``assign_repos``).

    python -m benchmarks.session_corpus.real --squeez PATH        # (re)write manifest.json from the dataset file
    python -m benchmarks.session_corpus.real --squeez PATH --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST_FILE = HERE / "manifest.json"
DEFAULT_SQUEEZ = ROOT / "build" / "session_corpus" / "squeez" / "canonical_test.jsonl"
SQUEEZ_SHA256 = "1ead3be111439266370fbcc8ffabeadd38fbd1526bbd981d23347da013b20540"
SQUEEZ_URL = "https://huggingface.co/datasets/KRLabsOrg/tool-output-extraction-swebench (file canonical_test.jsonl)"
MIN_CHARS, MAX_CHARS = 2000, 60000
SPLITS = ("dev", "validation", "holdout")


class SqueezMissing(FileNotFoundError):
    """The Squeez dataset file is not at the given path."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def repo_of(instance_id: str) -> str:
    owner, rest = instance_id.split("__", 1)
    return f"{owner}/{rest.rsplit('-', 1)[0]}"


def read_rows(path: Path | None = None) -> list[dict]:
    path = Path(path or DEFAULT_SQUEEZ)
    if not path.is_file():
        raise SqueezMissing(f"Squeez file not found at {path} (put canonical_test.jsonl there or pass --squeez)")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SQUEEZ_SHA256:
        raise ValueError(f"{path}: sha256 {digest} is not the pinned {SQUEEZ_SHA256}")
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def _eligible(rows: list[dict]) -> list[tuple[str, dict]]:
    out, seen = [], {}
    for row in rows:
        k = seen.get(row["instance_id"], 0)
        seen[row["instance_id"]] = k + 1
        if row["source"] == "swe" and MIN_CHARS <= len(row["tool_output"]) <= MAX_CHARS:
            out.append((f"squeez:{row['instance_id']}:{k}", row))
    return out


def gold_facts(text: str, spans: list[dict]) -> list[tuple[int, str]]:
    """One fact per gold span: the longest line of the span (stripped), with its 0-based line index."""
    lines = text.split("\n")
    out = []
    for sp in spans:
        best = None
        for i in range(max(0, sp["start_line"] - 1), min(len(lines), sp["end_line"])):
            s = lines[i].strip()
            if len(s) >= 6 and (best is None or len(s) > len(best[1])):
                best = (i, s)
        if best:
            out.append(best)
    return out


def assign_repos(repo_chars: dict[str, int]) -> dict[str, list[str]]:
    """Repository -> splits allowed to use it.  With >= 3 repositories each goes to exactly one split (largest first, to
    the split with the largest unmet share: holdout 0.55, dev 0.27, validation 0.18).  With fewer, the largest goes to
    the holdout alone and the rest are shared by dev and validation (recorded as a straddle; the holdout never shares)."""
    repos = sorted(repo_chars, key=lambda r: (-repo_chars[r], r))
    if len(repos) < 3:
        out = {repos[0]: ["holdout"]}
        for r in repos[1:]:
            out[r] = ["dev", "validation"]
        return out
    want = {"holdout": 0.55, "dev": 0.27, "validation": 0.18}
    total = sum(repo_chars.values())
    got = dict.fromkeys(want, 0)
    out = {}
    for r in repos:
        s = max(want, key=lambda k: (want[k] - got[k] / total, k))
        out[r] = [s]
        got[s] += repo_chars[r]
    return out


def build_manifest(rows: list[dict]) -> dict:
    elig = _eligible(rows)
    repo_chars: dict[str, int] = {}
    for _, row in elig:
        repo_chars[repo_of(row["instance_id"])] = repo_chars.get(repo_of(row["instance_id"]), 0) + len(row["tool_output"])
    pools = assign_repos(repo_chars)
    outputs = []
    for oid, row in elig:
        text = row["tool_output"]
        outputs.append({
            "id": oid, "origin": "Squeez canonical_test.jsonl (SWE-bench agent tool output)", "licence": "Apache-2.0",
            "repo": repo_of(row["instance_id"]), "instance_id": row["instance_id"], "tool_type": row["tool_type"],
            "sha256": sha256_text(text), "chars": len(text), "lines": text.count("\n") + 1,
            "gold_spans": [[s["start_line"], s["end_line"]] for s in row["gold_spans"]],
            "gold_facts": len(gold_facts(text, row["gold_spans"])), "redaction": "none",
            "splits": pools[repo_of(row["instance_id"])],
        })
    straddle = [f"{r}: {'+'.join(s)}" for r, s in sorted(pools.items()) if len(s) > 1]
    return {
        "dataset": {"name": "Squeez canonical_test.jsonl", "url": SQUEEZ_URL, "licence": "Apache-2.0", "sha256": SQUEEZ_SHA256,
                    "rows": len(rows)},
        "selection": f"source == 'swe' and {MIN_CHARS} <= chars <= {MAX_CHARS}; synthetic rows are not real and are not used",
        "repo_chars": dict(sorted(repo_chars.items())),
        "repo_splits": dict(sorted(pools.items())),
        "straddle": straddle,
        "straddle_note": ("only two repositories are in the file: the holdout's repository is used by no other split; dev and "
                          "validation share the other one until more repositories are fetched") if straddle else "",
        "outputs": outputs,
    }


def manifest_blob(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_manifest() -> dict:
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def pool_for(split: str, manifest: dict | None = None) -> list[dict]:
    m = manifest or load_manifest()
    return [o for o in m["outputs"] if split in o["splits"]]


class RealTexts:
    """Texts of the manifest's outputs, read from the Squeez file and checked against the manifest's sha256."""

    def __init__(self, path: Path | None = None, manifest: dict | None = None):
        m = manifest or load_manifest()
        want = {o["id"]: o for o in m["outputs"]}
        self.rows: dict[str, dict] = {}
        for oid, row in _eligible(read_rows(path)):
            if oid in want:
                if sha256_text(row["tool_output"]) != want[oid]["sha256"]:
                    raise ValueError(f"{oid}: text does not match the manifest sha256")
                self.rows[oid] = row
        missing = set(want) - set(self.rows)
        if missing:
            raise ValueError(f"{len(missing)} manifest outputs are not in the Squeez file")

    def text(self, oid: str) -> str:
        return self.rows[oid]["tool_output"]

    def query(self, oid: str) -> str:
        return self.rows[oid]["query"]

    def command(self, oid: str) -> str:
        return self.rows[oid]["command"]

    def facts(self, oid: str) -> list[tuple[int, str]]:
        row = self.rows[oid]
        return gold_facts(row["tool_output"], row["gold_spans"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--squeez", type=Path, default=DEFAULT_SQUEEZ)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        blob = manifest_blob(build_manifest(read_rows(args.squeez)))
    except SqueezMissing as e:
        print(f"skip: {e}", file=sys.stderr)
        return 3
    if args.check:
        ok = MANIFEST_FILE.read_text(encoding="utf-8") == blob
        print("manifest.json is byte-identical to a rebuild" if ok else "MISMATCH: manifest.json differs from a rebuild")
        return 0 if ok else 1
    MANIFEST_FILE.write_text(blob, encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
