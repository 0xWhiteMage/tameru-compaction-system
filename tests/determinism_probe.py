"""Subprocess probe for ``test_determinism``: one label -> output-hash mapping per run.

Run as a script under a chosen ``PYTHONHASHSEED``; prints a JSON object. The workload is the
``fx_shape-jp-musubi`` fixture under every golden query and option, plus a handful of round-2
**dev** S5 cases under ``build_specific``/``build_vague`` for both host profiles — the paths the
E5/E6 protection machinery (fact restore, error-exemplar restore, selection floor) can reach.
The same input must give the same bytes on every seed.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT / "tests"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import golden_compress as g
from tameru.compress_context import compress_context


def _blob(res, ccr: Path) -> str:
    blob = json.dumps(dataclasses.asdict(res), sort_keys=True, default=str)
    for form in {str(ccr), str(ccr).replace("\\", "/"), json.dumps(str(ccr))[1:-1]}:
        blob = blob.replace(form, "<ccr>")
    return blob.replace("<ccr>\\\\", "<ccr>/")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _musubi(out: dict[str, str], ccr: Path) -> None:
    text = g.corpus()["fx_shape-jp-musubi"]
    for qi, query in enumerate(g.QUERIES):
        for oi, option in enumerate(g.OPTIONS):
            kwargs = dict(option)
            kwargs.setdefault("ccr_dir", ccr)
            try:
                out[f"musubi|q{qi}|o{oi}"] = _sha(_blob(compress_context(text, query, **kwargs), ccr))
            except Exception as exc:
                out[f"musubi|q{qi}|o{oi}"] = f"raised {type(exc).__name__}"


def _r2_s5(out: dict[str, str], take: int = 8) -> None:
    from benchmarks.engine_bench import corpus, run

    assign = corpus.r2_assignment()
    cases = [
        c for c in corpus._build_r2()
        if assign[c["id"]] == "dev" and c.get("item_kind") in ("s5_buried", "s5_superseded")
    ][:take]
    for case in cases:
        text = case["text"]
        for cond in ("build_specific", "build_vague"):
            query = case["queries"][cond]
            sel = run._selector_query_for(case, cond)
            for profile in run.PROFILES:
                try:
                    res = run._call(profile, text, query, sel)
                    out[f"{case['id']}|{cond}|{profile}"] = _sha(
                        json.dumps(dataclasses.asdict(res), sort_keys=True, default=str))
                except Exception as exc:
                    out[f"{case['id']}|{cond}|{profile}"] = f"raised {type(exc).__name__}"


def main() -> None:
    ccr = Path(tempfile.mkdtemp())
    out: dict[str, str] = {}
    _musubi(out, ccr)
    _r2_s5(out)
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
