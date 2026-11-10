"""Tameru red-team harness.

Usage:
    python benchmarks/redteam/run_redteam.py             # full run
    python benchmarks/redteam/run_redteam.py --worker CASE_ID OUT.json
    python benchmarks/redteam/run_redteam.py --hashdump CASE_ID OUT.txt
    python benchmarks/redteam/run_redteam.py --only CASE_SUBSTR

The worker runs one case in a fresh process (Windows has no SIGALRM, so the
5 s per-case wall-clock cap is enforced by the parent killing the subprocess).
Writes findings-1.6.0.json and FINDINGS-1.6.0.md next to this file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_SRC = HERE.parent.parent / "src"
sys.path.insert(0, str(ENGINE_SRC))
sys.path.insert(0, str(HERE))

from markers import MARKER_RES, PREFIX_MARKERS, JSON_CRUSH_FRAGMENTS, marker_name  # noqa: E402

def _engine_version() -> str:
    """The version of the engine under test, so a run writes findings-<version>.* and never overwrites an earlier record."""
    text = (ENGINE_SRC / "tameru" / "compress_context.py").read_text(encoding="utf-8")
    match = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "unknown"


VERSION = _engine_version()
CASE_TIMEOUT_S = 30          # whole worker lifetime
COMPRESS_CAP_MS = 5000       # invariant 10: per-case wall-clock cap
HASH_SAMPLE = 60
WORKERS = 4

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def norm_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _materialise(text):
    """Case ``text`` field -> the real input value."""
    if isinstance(text, dict):
        kind = text["kind"]
        if kind == "const":
            return text["value"]
        if kind == "repeat":
            lines = [text["line"]] * text["n"]
            extra = text.get("extra") or []
            if extra:
                lines = lines[: text["n"] // 2] + extra + lines[text["n"] // 2:]
            return "\n".join(lines)
        if kind == "scale":
            base = text["base"]
            return base * text["mult"]
        raise ValueError(kind)
    return text


def _input_lines(text) -> list[str]:
    if not isinstance(text, str):
        return []
    return norm_newlines(text).split("\n")


def _check_extractive(output: str, text, input_lines: list[str]):
    """Every output line is an input line (post engine normalisation) or an
    allow-listed marker. Returns (fabrications, rewritten, markers_used)."""
    in_set = set(input_lines)
    stripped_in = {ln.rstrip() for ln in input_lines}
    lstripped_in = {ln.lstrip() for ln in input_lines}
    ansi_free_in = {_ANSI_RE.sub("", ln).rstrip() for ln in input_lines}
    # whitespace-free input text: catches JSON re-serialisation that re-indents
    # or splits an input scalar/array element onto its own line
    wsfree_in = re.sub(r"\s", "", "\n".join(input_lines))
    fab, rewritten, markers = [], [], []
    for line in output.split("\n"):
        if line in in_set or line.rstrip() in stripped_in or line.rstrip() in ansi_free_in:
            continue
        if line.lstrip() in lstripped_in:
            rewritten.append("indent-drift")
            continue
        m = marker_name(line)
        if m:
            markers.append(m)
            continue
        pre = None
        for _name, rx, _src in PREFIX_MARKERS:
            mm = rx.match(line)
            if mm:
                pre = mm.group(1)
                break
        if pre is not None:
            if pre in in_set or pre.rstrip() in stripped_in or pre.strip() in stripped_in:
                markers.append("prefixed-input")
                continue
            # periodic fold keeps only u[:p].strip() — a prefix of a line
            if any(il.startswith(pre.rstrip()[:80]) for il in input_lines[: len(input_lines)]):
                markers.append("prefixed-input")
                continue
        # truncated long line: input prefix + marker tail (compress_context
        # _emit_brief cuts lines at budget//3 and appends a marker)
        hit = next((il for il in input_lines if line and il.startswith(line[:60]) and len(line) < len(il)), None)
        if hit is not None:
            rewritten.append("truncated-line")
            continue
        if any(f in line for f in JSON_CRUSH_FRAGMENTS):
            rewritten.append("json-crush")
            continue
        # JSON re-serialisation: the line's content (minus whitespace) is a
        # substring of the input's — a reshaped JSON span, not invented text
        ws_line = re.sub(r"\s", "", line)
        if len(ws_line) >= 4 and ws_line in wsfree_in:
            rewritten.append("ws-rewritten")
            continue
        # tool-envelope meta line: first line parses as a JSON dict whose
        # keys/values are scalar metadata of the input envelope
        if line.startswith("{") and isinstance(text, str) and text.strip().startswith("{"):
            try:
                meta = json.loads(line)
                whole = json.loads(text.strip())
                if isinstance(meta, dict) and isinstance(whole, dict) and all(
                    k in whole and whole[k] == v for k, v in meta.items()
                ):
                    rewritten.append("tool-meta")
                    continue
            except Exception:
                pass
        fab.append(line)
    return fab, rewritten, markers


def _has_surrogate(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def run_case(case: dict) -> dict:
    from tameru.compress_context import compress_context, error_fingerprints

    text = _materialise(case["text"])
    query = case["query"]
    out_rec = {
        "id": case["id"], "family": case["family"], "format": case["format"],
        "lang": case["lang"], "attack": case["attack"],
        "violations": [], "metrics": {},
    }
    v = out_rec["violations"].append
    ccr_dir = tempfile.mkdtemp(prefix="tameru-redteam-ccr-") if case.get("ccr") else None
    try:
        t0 = time.perf_counter()
        r = compress_context(text, query, ccr=bool(case.get("ccr")), citations=False,
                             ccr_dir=ccr_dir or tempfile.gettempdir())
        ms = (time.perf_counter() - t0) * 1000
    except Exception as exc:  # invariant 1 — no crash
        v({"invariant": "no-crash", "detail": f"{type(exc).__name__}: {exc}"[:400]})
        out_rec["metrics"]["ms"] = None
        return out_rec

    output = r.compressed_text or ""
    in_len = len(text) if isinstance(text, str) else len(str(text))
    out_rec["metrics"].update(
        ms=round(ms, 1), in_len=in_len, out_len=len(output),
        saved_pct=round(r.tokens_saved_pct, 2), fail_open=r.fail_open,
        risk=r.compression_risk, content_type=r.content_type,
        adapter=(r.receipt or {}).get("adapter"),
        bytes_wasted=in_len - len(output),
    )

    # invariant 3 — fail-open identity
    if r.fail_open and isinstance(text, str) and output != text:
        v({"invariant": "fail-open-identity",
           "detail": f"fail_open but output {len(output)} chars != input {in_len}"})
    # invariant 4 — never longer
    if isinstance(text, str) and len(output) > in_len:
        v({"invariant": "never-longer",
           "detail": f"output {len(output)} > input {in_len}",
           "excerpt": output[:120]})
    # invariant 5 — extractive
    if isinstance(text, str):
        input_lines = _input_lines(text)
        fab, rewritten, markers = _check_extractive(output, text, input_lines)
        out_rec["metrics"]["rewritten_lines"] = len(rewritten)
        out_rec["metrics"]["marker_lines"] = len(markers)
        for line in fab[:5]:
            v({"invariant": "fabrication", "excerpt": line[:300],
               "detail": f"output line matches no input line or marker: {line[:160]!r}"})
    # invariant 6 — gold retained
    for g in case.get("gold") or []:
        if g and g not in output:
            v({"invariant": "gold-loss", "detail": f"missing gold: {g[:160]!r}"})
    # invariant 7 — forbidden
    present_forbidden = [f for f in (case.get("forbidden") or []) if f and f in output]
    out_rec["metrics"]["forbidden_present"] = present_forbidden
    for f in present_forbidden:
        v({"invariant": "forbidden-leak", "detail": f"superseded/contradicted value kept: {f[:160]!r}"})
    # invariant 8 — error fingerprint coverage (metric; violation iff a gold error line dropped)
    if isinstance(text, str) and text:
        try:
            want = set(error_fingerprints(text))
            got = set(error_fingerprints(output))
            cov = (len(want & got) / len(want)) if want else 1.0
            out_rec["metrics"]["error_coverage"] = round(cov, 3)
            gold_lines = {gl for g in (case.get("gold") or []) for gl in g.split("\n")}
            err_fps = error_fingerprints(text)
            gold_error_fps = {fp for fp, ln in err_fps.items() if any(gl and gl in ln for gl in gold_lines)}
            missing_gold_fps = gold_error_fps - got
            if missing_gold_fps:
                v({"invariant": "error-coverage",
                   "detail": f"gold error fingerprint dropped: {sorted(missing_gold_fps)[:2]}"})
        except Exception as exc:
            out_rec["metrics"]["error_coverage"] = f"error: {exc}"
    # invariant 9 — savings metric (flagged in parent, not a violation here)
    # invariant 10 — wall-clock
    if ms > COMPRESS_CAP_MS:
        v({"invariant": "perf-cap", "detail": f"{ms:.0f} ms > {COMPRESS_CAP_MS} ms"})
    # invariant 11 — idempotence
    if isinstance(text, str) and output:
        try:
            r2 = compress_context(output, query, ccr=False, citations=False)
            if len(r2.compressed_text or "") > len(output):
                v({"invariant": "idempotence",
                   "detail": f"re-compress grew {len(output)} -> {len(r2.compressed_text)}"})
            out_rec["metrics"]["second_pass_fail_open"] = r2.fail_open
        except Exception as exc:
            v({"invariant": "idempotence", "detail": f"second pass raised {type(exc).__name__}: {exc}"[:300]})
    # invariant 12 — unicode
    if isinstance(text, str):
        out_rec["metrics"]["output_surrogates"] = _has_surrogate(output)
        if _has_surrogate(output) and not _has_surrogate(text):
            v({"invariant": "unicode", "detail": "output contains lone surrogates absent from input"})
        bidi_in = sum(1 for ln in _input_lines(text) if any(c in _BIDI for c in ln))
        bidi_out = sum(1 for ln in output.split("\n") if any(c in _BIDI for c in ln))
        out_rec["metrics"]["bidi_lines_in"] = bidi_in
        out_rec["metrics"]["bidi_lines_out"] = bidi_out
    # invariant 2 — determinism (in-process double call, same flags)
    try:
        r3 = compress_context(text, query, ccr=bool(case.get("ccr")), citations=False,
                              ccr_dir=ccr_dir or tempfile.gettempdir())
        det = (r3.compressed_text or "") == output
        out_rec["metrics"]["deterministic_inproc"] = det
        if not det:
            v({"invariant": "determinism", "detail": "second in-process call differs"})
    except Exception as exc:
        v({"invariant": "determinism", "detail": f"second call raised {type(exc).__name__}: {exc}"[:300]})
    # invariant 13 — CCR store must not hold a planted secret
    if case.get("ccr") and ccr_dir:
        planted = case.get("secret") or ""
        stored = []
        for fp in Path(ccr_dir).glob("*.json"):
            try:
                blob = fp.read_text(encoding="utf-8", errors="surrogatepass")
            except OSError:
                continue
            if planted and planted in blob:
                stored.append(fp.name)
        if stored:
            v({"invariant": "ccr-secret", "detail": f"planted secret stored in {stored}"})
        out_rec["metrics"]["ccr_records"] = len(list(Path(ccr_dir).glob("*.json")))
        out_rec["metrics"]["ccr_marker_in_output"] = "[CC-Retrieve:" in output
    # forged-marker survivability metric (attacks)
    if case.get("forged_markers"):
        surv = [m for m in case["forged_markers"] if m in output]
        out_rec["metrics"]["forged_survived"] = surv
        out_rec["metrics"]["recursion_guard_failopen"] = r.fail_open
        if surv:
            v({"invariant": "forged-marker", "detail": f"forged engine markers survive as kept lines: {surv}"})
    return out_rec


def run_worker(case_id: str, out_path: str) -> None:
    from corpus import build_corpus

    case = next(c for c in build_corpus() if c["id"] == case_id)
    rec = run_case(case)
    Path(out_path).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def run_hashdump(case_id: str, out_path: str) -> None:
    import hashlib

    from corpus import build_corpus
    from tameru.compress_context import compress_context

    case = next(c for c in build_corpus() if c["id"] == case_id)
    text = _materialise(case["text"])
    r = compress_context(text, case["query"], ccr=False, citations=False)
    h = hashlib.sha256((r.compressed_text or "").encode("utf-8", errors="surrogatepass")).hexdigest()
    Path(out_path).write_text(h, encoding="ascii")


def _severity(violation: str) -> str:
    order = ["fabrication", "no-crash", "ccr-secret", "forbidden-leak",
             "gold-loss", "error-coverage", "determinism", "forged-marker",
             "unicode", "fail-open-identity", "never-longer", "idempotence", "perf-cap"]
    for s in order:
        if violation == s or violation.startswith(s):
            return {
                "fabrication": "fabrication", "no-crash": "crash",
                "ccr-secret": "safety-leak", "forbidden-leak": "safety-leak",
                "gold-loss": "gold-loss", "error-coverage": "gold-loss",
                "determinism": "nondeterminism", "forged-marker": "fabrication",
                "unicode": "unicode", "fail-open-identity": "safety-leak",
                "never-longer": "safety-leak", "idempotence": "nondeterminism",
                "perf-cap": "perf",
            }[s]
    return "low"


def _layer(case: dict) -> str:
    fam = case["family"]
    if fam.startswith("perf"):
        return "perf"
    if fam in ("languages", "unicode"):
        return "unicode"
    if fam == "ccr":
        return "engine-core"
    if case["format"] in ("diff", "grep", "test", "xml", "yaml", "csv", "tsv",
                          "markdown", "json", "ndjson", "kubectl", "numbered_code"):
        return "adapter"
    return "engine-core"


def main() -> int:
    from corpus import build_corpus

    only = None
    argv = sys.argv[1:]
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]
    cases = build_corpus()
    if only:
        cases = [c for c in cases if only in c["id"]]
    print(f"{len(cases)} cases, {WORKERS} workers", flush=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="tameru-redteam-"))
    script = str(HERE / "run_redteam.py")

    def run_one(case):
        cid = case["id"]
        out = tmpdir / f"{cid}.json"
        cmd = [sys.executable, script, "--worker", cid, str(out)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=CASE_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            rec = json.loads(json.dumps({"id": cid, "family": case["family"],
                                         "format": case["format"], "lang": case["lang"],
                                         "attack": case["attack"], "violations": [], "metrics": {}}))
            rec["violations"].append({"invariant": "perf-cap",
                                      "detail": f"worker exceeded {CASE_TIMEOUT_S}s (killed)"})
            rec["metrics"]["ms"] = None
            return rec
        if not out.exists():
            rec = {"id": cid, "family": case["family"], "format": case["format"],
                   "lang": case["lang"], "attack": case["attack"],
                   "violations": [{"invariant": "no-crash",
                                   "detail": f"worker died rc={proc.returncode}: "
                                             f"{(proc.stderr or '')[-400:]}"}],
                   "metrics": {"ms": None}}
            return rec
        rec = json.loads(out.read_text(encoding="utf-8"))
        rec["metrics"]["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec

    results: list[dict] = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, rec in enumerate(pool.map(run_one, cases)):
            results.append(rec)
            nv = len(rec["violations"])
            print(f"[{i + 1:3d}/{len(cases)}] {rec['id']:34s} "
                  f"ms={str(rec['metrics'].get('ms')):>8s} viol={nv}", flush=True)

    # hash-seed determinism on a sample
    sample = cases[:HASH_SAMPLE]
    print(f"hash-seed determinism over {len(sample)} cases", flush=True)
    def hash_for(cid, seed):
        out = tmpdir / f"h-{seed}-{cid}.txt"
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, script, "--hashdump", cid, str(out)],
                       capture_output=True, timeout=CASE_TIMEOUT_S, env=env)
        return out.read_text().strip() if out.exists() else "MISSING"

    for case in sample:
        cid = case["id"]
        h0, h1 = hash_for(cid, 0), hash_for(cid, 12345)
        if h0 != h1:
            rec = next(r for r in results if r["id"] == cid)
            rec["violations"].append(
                {"invariant": "determinism",
                 "detail": f"PYTHONHASHSEED 0 vs 12345 differ ({h0[:12]} vs {h1[:12]})"})
        next(r for r in results if r["id"] == cid)["metrics"]["hash0"] = h0[:16]

    # scaling ratio check
    by_id = {r["id"]: r for r in results}
    for case in cases:
        cid = case["id"]
        if case["family"] == "perf-scaling" and cid.endswith("-16x"):
            base = cid[: -len("-16x")]
            t1 = by_id.get(base + "-1x", {}).get("metrics", {}).get("ms")
            t16 = by_id[cid]["metrics"].get("ms")
            if t1 and t16 and t16 / max(t1, 1) > 24:
                by_id[cid]["violations"].append(
                    {"invariant": "superlinear",
                     "detail": f"16x size took {t16:.0f}ms vs {t1:.0f}ms at 1x (ratio {t16 / t1:.1f}x)"})
            by_id[cid]["metrics"]["scale_ratio_16_1"] = (
                round(t16 / max(t1 or 1, 1), 1) if t16 else None)

    # low-savings flags (metric + soft violation)
    for rec in results:
        m = rec["metrics"]
        if (m.get("in_len") or 0) > 4096 and not m.get("fail_open") \
                and (m.get("saved_pct") or 0) < 30:
            rec["violations"].append(
                {"invariant": "low-savings",
                 "detail": f"{m.get('saved_pct')}% saved on {m.get('in_len')} chars"})

    findings = []
    sev_rank = {"fabrication": 0, "crash": 1, "safety-leak": 2, "gold-loss": 3,
                "nondeterminism": 4, "perf": 5, "unicode": 6, "low-savings": 7}
    case_map = {c["id"]: c for c in cases}
    for rec in results:
        for viol in rec["violations"]:
            inv = viol["invariant"]
            sev = "low-savings" if inv == "low-savings" else (
                "perf" if inv in ("perf-cap", "superlinear") else _severity(inv))
            findings.append({
                "case_id": rec["id"], "invariant": inv,
                "severity": sev, "layer": _layer(case_map[rec["id"]]),
                "detail": viol.get("detail", "")[:500],
                "excerpt": viol.get("excerpt", "")[:300],
                "family": rec["family"], "format": rec["format"],
            })
    findings.sort(key=lambda f: (sev_rank.get(f["severity"], 9), f["case_id"]))

    payload = {
        "version": VERSION,
        "cases": len(cases),
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "findings": findings,
    }
    suffix = f"-{VERSION}" if not only else f"-{VERSION}-partial"
    (HERE / f"findings{suffix}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_md(payload, suffix)
    print(f"findings: {len(findings)} -> {HERE}/findings{suffix}.json, FINDINGS{suffix}.md")
    return 0


def _write_md(payload: dict, suffix: str | None = None) -> None:
    suffix = suffix or f"-{payload['version']}"
    lines = [f"# Tameru {payload['version']} red-team findings",
             f"",
             f"Run: {payload['run_at']} — {payload['cases']} cases",
             f"",
             "| severity | count |",
             "|---|---|"]
    from collections import Counter
    sev_c = Counter(f["severity"] for f in payload["findings"])
    for sev in ("fabrication", "crash", "safety-leak", "gold-loss",
                "nondeterminism", "perf", "unicode", "low-savings", "low"):
        if sev_c.get(sev):
            lines.append(f"| {sev} | {sev_c[sev]} |")
    lines += ["", "## Findings", "",
              "| case | layer | severity | invariant | detail |", "|---|---|---|---|---|"]
    for f in payload["findings"]:
        det = f["detail"].replace("|", "\\|").replace("\n", " ")[:220]
        lines.append(f"| {f['case_id']} | {f['layer']} | {f['severity']} | "
                     f"{f['invariant']} | {det} |")
    lines += ["", "## Per-case metrics", "",
              "| case | family | in_len | out_len | saved% | ms | fail_open | risk | adapter |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in payload["results"]:
        m = r["metrics"]
        ad = m.get("adapter")
        adn = ad.get("name") if isinstance(ad, dict) else (ad or "")
        lines.append(f"| {r['id']} | {r['family']} | {m.get('in_len')} | {m.get('out_len')} "
                     f"| {m.get('saved_pct')} | {m.get('ms')} | {m.get('fail_open')} "
                     f"| {m.get('risk')} | {adn} |")
    (HERE / f"FINDINGS{suffix}.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--worker" in sys.argv:
        i = sys.argv.index("--worker")
        run_worker(sys.argv[i + 1], sys.argv[i + 2])
        sys.exit(0)
    if "--hashdump" in sys.argv:
        i = sys.argv.index("--hashdump")
        run_hashdump(sys.argv[i + 1], sys.argv[i + 2])
        sys.exit(0)
    sys.exit(main())
