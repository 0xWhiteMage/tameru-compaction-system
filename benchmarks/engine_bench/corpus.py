"""Case corpus for the engine benchmark.

Case = {id, source_case, content_type, shape, text, gold, forbidden, language, queries}.

* ``source_case`` is the cluster id: variants of one source never straddle a split.
* ``content_type`` is a coarse stratum (trace, build, test, log, prose, structured, code, diff);
  ``shape`` is the finer label used for call-outs (trace-java, uni-fullwidth, jp_musubi, ...).
* ``language``: en, zh, mixed (a Chinese message against English text or the reverse) or other.
* ``queries`` = {task, tool_call, generic}; ``zh_user`` is added where the language is zh or mixed
  (a conversational Chinese user message in place of a task query).

Sources: benchmarks/compare.py + run_battery.py cases, the red-team corpus (traces, compilers, test
runners, languages, formats, unicode), tests/golden_compress.py inputs, and seeded generators in
gen_cases.py.  Sealed texts are only returned by ``load_cases(..., sealed_ok=True)``, which only
``run.py --sealed`` passes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from .gen_cases import generated_cases, make_case

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPLITS_FILE = HERE / "splits.json"
SEALED_HASH_FILE = HERE / "SEALED.sha256"


class SealedAccessError(RuntimeError):
    """Raised when sealed texts are requested without the explicit --sealed opt-in."""


def _load_module(name: str, path: Path, extra_paths=()):
    saved = list(sys.path)
    sys.path.extend(str(p) for p in extra_paths)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved


def _lang_code(lang: str) -> str:
    return "en" if lang == "en" else "zh" if lang.startswith("zh") else "other"


_BAT = {"git_log": ("structured", "git-log"), "npm_log": ("log", "npm-log"), "jp_musubi": ("prose", "jp_musubi"),
        "zh_needle": ("prose", "zh_needle"), "ar_needle": ("prose", "ar_needle"), "travis_yaml": ("structured", "yaml-travis"),
        "grep_saturated_command": ("structured", "grep"), "pytest_captured_blank_lines": ("test", "test-pytest"),
        "numbered_source": ("code", "numbered-source")}


def _existing_cases() -> list[dict]:
    out = []
    sys.path.insert(0, str(ROOT / "src"))
    bench = ROOT / "benchmarks"
    compare = _load_module("_eb_compare", bench / "compare.py", extra_paths=[bench])
    for c in compare.current_cases():
        if c["name"] == "large_doc_perf" or not c["gold"]:
            continue
        ctype, shape = _BAT.get(c["name"], ("prose", c["name"]))
        lang = "zh" if c["name"] == "zh_needle" else "other" if c["name"] in ("ar_needle", "jp_musubi") else "en"
        out.append(make_case(f"bat-{c['name']}", f"bat-{c['name']}", ctype, shape, c["ctx"], c["gold"], lang, c["q"],
                             forbidden=c.get("forbid", [])))
    rt = _load_module("_eb_redteam_corpus", bench / "redteam" / "corpus.py")
    keep = {"ecosystem-traces": "trace", "compiler-output": "build", "test-runners": "test", "languages": "log",
            "formats": "structured", "unicode": "log"}
    for c in rt.build_corpus():
        if c["family"] not in keep or not isinstance(c["text"], str) or not c["gold"]:
            continue
        cid = c["id"]
        paired = cid.startswith("lang-") and cid.rsplit("-", 1)[1] in ("native", "enq")
        source = "rt-" + (cid.rsplit("-", 1)[0] if paired else cid)
        shape = cid if cid.startswith(("trace-", "comp-", "run-", "uni-")) else "format" if c["family"] == "formats" else cid
        out.append(make_case("rt-" + cid, source, keep[c["family"]], shape, c["text"], c["gold"], _lang_code(c["lang"]), c["query"],
                             forbidden=c["forbidden"], zh="hant" if c["lang"] == "zh-Hant" else None))
    golden = _load_module("_eb_golden", ROOT / "tests" / "golden_compress.py")
    texts = golden.corpus()
    specials = {"log_errors": ("why did the payments job fail?", "PaymentGatewayTimeout"),
                "log_rare": ("handshake refused", "handshake refused by upstream"),
                "log_rare_many": ("retry scheduled", "retry scheduled"),
                "log_noisy_errors": ("cache miss storm", "ERROR cache miss storm key=")}
    for name, (q, token) in specials.items():
        lines = [ln for ln in texts[name].splitlines() if token in ln]
        picks = sorted({lines[0], lines[len(lines) // 2], lines[-1]})
        out.append(make_case(f"gold-{name}", f"gold-{name}", "log", "log-" + name, texts[name], picks, "en", q))
    return out


def _build_all() -> list[dict]:
    cases = _existing_cases() + generated_cases()
    seen = set()
    for c in cases:
        assert c["id"] not in seen, c["id"]
        seen.add(c["id"])
        missing = [g for g in c["gold"] if g not in c["text"]]
        assert not missing, (c["id"], missing)
    return sorted(cases, key=lambda c: c["id"])


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sealed_digest(cases: list[dict]) -> str:
    """sha256 of the canonical JSON of the sealed cases' (id, text hash, gold)."""
    rows = sorted([c["id"], text_sha(c["text"]), c["gold"]] for c in cases)
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_splits() -> dict[str, str]:
    return json.loads(SPLITS_FILE.read_text(encoding="utf-8"))


def load_cases(splits=("dev", "validation"), *, sealed_ok: bool = False) -> list[dict]:
    """Cases of the requested splits.  Sealed texts need ``sealed_ok=True`` (the runner's --sealed)."""
    splits = set(splits)
    if "sealed" in splits and not sealed_ok:
        raise SealedAccessError("the sealed split may only be read through run.py --sealed (one look per host)")
    assignment = load_splits()
    return [c for c in _build_all() if assignment[c["id"]] in splits]


# ---------------------------------------------------------------- round 2
SPLITS_R2_FILE = HERE / "splits_r2.json"
SEALED_R2_HASH_FILE = HERE / "SEALED-R2.sha256"
SEALED_LOOKS_R2_FILE = HERE / "sealed_looks_r2.json"


def _build_r2() -> list[dict]:
    """All round-2 generated cases (gen_cases_r2); the r2 split file maps family -> split."""
    from .gen_cases_r2 import generated_cases_r2

    cases = generated_cases_r2()
    seen = set()
    for c in cases:
        assert c["id"] not in seen, c["id"]
        seen.add(c["id"])
        missing = [g for g in c["gold"] if g not in c["text"]]
        assert not missing, (c["id"], missing)
    return sorted(cases, key=lambda c: c["id"])


def load_splits_r2() -> dict:
    """The round-2 split document: {deal: {seed, attempt, rule}, families: {fid: split}, counts}."""
    return json.loads(SPLITS_R2_FILE.read_text(encoding="utf-8"))


def r2_assignment() -> dict[str, str]:
    fams = load_splits_r2()["families"]
    return {c["id"]: fams[c["family"]] for c in _build_r2()}


def load_cases_r2(splits=("dev", "validation"), *, sealed_ok: bool = False) -> list[dict]:
    """Round-2 cases of the requested splits.  Sealed r2 texts need ``sealed_ok=True``."""
    splits = set(splits)
    if "sealed" in splits and not sealed_ok:
        raise SealedAccessError("the sealed r2 split may only be read through run.py --round 2 --sealed --candidate NAME")
    assignment = r2_assignment()
    return [c for c in _build_r2() if assignment[c["id"]] in splits]


# ---------------------------------------------------------------- round 3
SPLITS_R3_FILE = HERE / "splits_r3.json"
SEALED_R3_HASH_FILE = HERE / "SEALED-R3.sha256"
SEALED_LOOKS_R3_FILE = HERE / "sealed_looks_r3.json"


def _build_r3() -> list[dict]:
    """All round-3 generated cases (gen_cases_r3); the r3 split file maps family -> split.

    The r3 holdout exists because the failed r2 sealed look burned its families into dev —
    every r3 family is disjoint from r1, session-corpus and all r2 families.
    """
    from .gen_cases_r3 import generated_cases_r3

    cases = generated_cases_r3()
    seen = set()
    for c in cases:
        assert c["id"] not in seen, c["id"]
        seen.add(c["id"])
        missing = [g for g in c["gold"] if g not in c["text"]]
        assert not missing, (c["id"], missing)
    return sorted(cases, key=lambda c: c["id"])


def load_splits_r3() -> dict:
    """The round-3 split document: {deal: {seed, attempt, rule}, families: {fid: split}, counts}."""
    return json.loads(SPLITS_R3_FILE.read_text(encoding="utf-8"))


def r3_assignment() -> dict[str, str]:
    fams = load_splits_r3()["families"]
    return {c["id"]: fams[c["family"]] for c in _build_r3()}


def load_cases_r3(splits=("dev", "validation"), *, sealed_ok: bool = False) -> list[dict]:
    """Round-3 cases of the requested splits.  Sealed r3 texts need ``sealed_ok=True``."""
    splits = set(splits)
    if "sealed" in splits and not sealed_ok:
        raise SealedAccessError("the sealed r3 split may only be read through run.py --round 3 --sealed --candidate NAME")
    assignment = r3_assignment()
    return [c for c in _build_r3() if assignment[c["id"]] in splits]


def main(argv=None) -> int:
    import argparse
    from collections import Counter

    p = argparse.ArgumentParser(description="engine_bench corpus counts")
    p.add_argument("--round", dest="round_", type=int, choices=(1, 2, 3), default=1)
    a = p.parse_args(argv)
    cases = {1: _build_all, 2: _build_r2, 3: _build_r3}[a.round_]()
    print(f"round {a.round_}: {len(cases)} cases, {len({c['source_case'] for c in cases})} clusters, "
          f"{dict(Counter(c['language'] for c in cases))}")
    if a.round_ >= 2:
        print(f"families: {len({c['family'] for c in cases})}, "
              f"kinds: {dict(Counter(c['item_kind'] for c in cases))}")
        splits_file = SPLITS_R2_FILE if a.round_ == 2 else SPLITS_R3_FILE
        if splits_file.exists():
            fams = load_splits_r2()["families"] if a.round_ == 2 else load_splits_r3()["families"]
            per = Counter(fams[c["family"]] for c in cases)
            print(f"splits: {dict(per)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
