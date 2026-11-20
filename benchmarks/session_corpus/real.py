"""Real tool outputs (Squeez / SWE-bench) reused as ``kind: real`` steps, and their manifest.

The dataset files stay out of git.  ``manifest.json`` (committed) records both files' sha256 and, per output used, its
origin, licence, id, repository, sha256, size, gold line spans (numbers only) and redaction, so a rebuild can prove it
is byte-identical; it holds no output text.  Pools are by REPOSITORY: each repository is dealt to exactly one split by
a logged seed (``assign_repos``), so no repository straddles splits.

    python -m benchmarks.session_corpus.real [--squeez DIR]          # (re)write manifest.json from the dataset files
    python -m benchmarks.session_corpus.real [--squeez DIR] --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST_FILE = HERE / "manifest.json"
DEFAULT_SQUEEZ = ROOT / "build" / "session_corpus" / "squeez"      # a directory holding both files below
DATASETS = {  # tag -> (file name, pinned sha256)
    "test": ("canonical_test.jsonl", "1ead3be111439266370fbcc8ffabeadd38fbd1526bbd981d23347da013b20540"),
    "train": ("canonical_train.jsonl", "8e64421bfbb0fda2f2edfb1cee8f593297229ecd2c2c1e7692ff784bbaca22a3"),
}
SQUEEZ_URL = "https://huggingface.co/datasets/KRLabsOrg/tool-output-extraction-swebench"
MIN_CHARS, MAX_CHARS = 2000, 40000         # 40K: the size cap of real steps (generator.REAL_MAX_CHARS)
PER_REPO = 120                             # outputs kept per repository (lowest sha256 of their id), so no repo dominates a pool
REPO_DEAL_SEED = "session-corpus-round2-repos-1"
REPO_SPLIT_COUNTS = {"holdout": 5, "dev": 3, "validation": 3}
SPLITS = ("dev", "validation", "holdout")


class SqueezMissing(FileNotFoundError):
    """A Squeez dataset file is not in the given directory."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def repo_of(instance_id: str) -> str:
    owner, rest = instance_id.split("__", 1)
    return f"{owner}/{rest.rsplit('-', 1)[0]}"


def files_present(directory: Path | None = None) -> bool:
    d = Path(directory or DEFAULT_SQUEEZ)
    return all((d / name).is_file() for name, _ in DATASETS.values())


def read_rows(directory: Path | None = None) -> dict[str, list[dict]]:
    """tag -> rows of each pinned dataset file (sha256 checked)."""
    d = Path(directory or DEFAULT_SQUEEZ)
    out = {}
    for tag, (name, want) in DATASETS.items():
        path = d / name
        if not path.is_file():
            raise SqueezMissing(f"Squeez file not found at {path} (put {', '.join(n for n, _ in DATASETS.values())} in {d} or pass --squeez DIR)")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != want:
            raise ValueError(f"{path}: sha256 {digest} is not the pinned {want}")
        out[tag] = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    return out


def _eligible(rows_by_tag: dict[str, list[dict]]) -> list[tuple[str, str, dict]]:
    """(id, dataset tag, row) of every swe output of 2K-40K characters, then at most PER_REPO per repository."""
    cand: dict[str, list[tuple[str, str, dict]]] = {}
    for tag in sorted(rows_by_tag):
        seen: dict[str, int] = {}
        for row in rows_by_tag[tag]:
            k = seen.get(row["instance_id"], 0)
            seen[row["instance_id"]] = k + 1
            if row["source"] == "swe" and MIN_CHARS <= len(row["tool_output"]) <= MAX_CHARS:
                oid = f"squeez-{tag}:{row['instance_id']}:{k}"
                cand.setdefault(repo_of(row["instance_id"]), []).append((oid, tag, row))
    out = []
    for repo in sorted(cand):
        picks = sorted(cand[repo], key=lambda t: hashlib.sha256(t[0].encode()).hexdigest())[:PER_REPO]
        out.extend(sorted(picks, key=lambda t: t[0]))
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


def assign_repos(repos: list[str], seed: str = REPO_DEAL_SEED) -> dict[str, list[str]]:
    """Repository -> [the one split that may use it]: repositories sorted by name, shuffled by
    random.Random(sha256('repos:'+seed)), dealt REPO_SPLIT_COUNTS (holdout 5, dev 3, validation 3)."""
    need = sum(REPO_SPLIT_COUNTS.values())
    if len(repos) < need:
        raise ValueError(f"{len(repos)} repositories; the deal needs {need}")
    order = sorted(repos)
    random.Random(int(hashlib.sha256(f"repos:{seed}".encode()).hexdigest()[:16], 16)).shuffle(order)
    out, i = {}, 0
    for split in ("holdout", "dev", "validation"):
        for _ in range(REPO_SPLIT_COUNTS[split]):
            out[order[i]] = [split]
            i += 1
    for r in order[i:]:          # any further repository goes to the holdout
        out[r] = ["holdout"]
    return dict(sorted(out.items()))


def build_manifest(rows_by_tag: dict[str, list[dict]]) -> dict:
    elig = _eligible(rows_by_tag)
    repo_chars: dict[str, int] = {}
    for _, _, row in elig:
        repo_chars[repo_of(row["instance_id"])] = repo_chars.get(repo_of(row["instance_id"]), 0) + len(row["tool_output"])
    pools = assign_repos(list(repo_chars))
    outputs = []
    for oid, tag, row in elig:
        text = row["tool_output"]
        outputs.append({
            "id": oid, "origin": f"Squeez {DATASETS[tag][0]} (SWE-bench agent tool output)", "licence": "Apache-2.0",
            "repo": repo_of(row["instance_id"]), "instance_id": row["instance_id"], "tool_type": row["tool_type"],
            "sha256": sha256_text(text), "chars": len(text), "lines": text.count("\n") + 1,
            "gold_spans": [[s["start_line"], s["end_line"]] for s in row["gold_spans"]],
            "gold_facts": len(gold_facts(text, row["gold_spans"])), "redaction": "none",
            "splits": pools[repo_of(row["instance_id"])],
        })
    return {
        "datasets": {tag: {"file": name, "sha256": sha, "rows": len(rows_by_tag[tag]), "url": SQUEEZ_URL, "licence": "Apache-2.0"}
                     for tag, (name, sha) in DATASETS.items()},
        "selection": (f"source == 'swe' and {MIN_CHARS} <= chars <= {MAX_CHARS}; at most {PER_REPO} outputs per repository "
                      "(lowest sha256 of the id); synthetic rows are not real and are not used"),
        "repo_deal": {"seed": REPO_DEAL_SEED, "counts": REPO_SPLIT_COUNTS,
                      "rule": "repositories sorted, shuffled by random.Random(sha256('repos:'+seed)), dealt holdout, dev, validation"},
        "repo_chars": dict(sorted(repo_chars.items())),
        "repo_splits": pools,
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
    """Texts of the manifest's outputs, read from the Squeez files and checked against the manifest's sha256."""

    def __init__(self, directory: Path | None = None, manifest: dict | None = None):
        m = manifest or load_manifest()
        want = {o["id"]: o for o in m["outputs"]}
        self.rows: dict[str, dict] = {}
        for oid, _, row in _eligible(read_rows(directory)):
            if oid in want:
                if sha256_text(row["tool_output"]) != want[oid]["sha256"]:
                    raise ValueError(f"{oid}: text does not match the manifest sha256")
                self.rows[oid] = row
        missing = set(want) - set(self.rows)
        if missing:
            raise ValueError(f"{len(missing)} manifest outputs are not in the Squeez files")

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
    ap.add_argument("--squeez", type=Path, default=DEFAULT_SQUEEZ, help="directory holding both Squeez files")
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
