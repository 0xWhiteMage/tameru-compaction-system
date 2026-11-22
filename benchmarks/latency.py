#!/usr/bin/env python
"""Latency benchmark for ``tameru.compress_context.compress_context`` (stdlib only, no network).

Every cell = (profile, size class, content kind, query condition).  Inputs are synthetic and seeded.
Each cell gets one untimed warmup call, then ``n`` timed calls.  Engine memos are cleared
(``compress_context._clear_memos``) before every timed call, so each call is a memo-cold analysis of the
text in a warm process (imports done, regexes compiled).  That is the cost a plugin pays for a text it has
not seen; the repeat-call cost with warm memos is far lower and is not what the budgets describe.

Profiles
  deepseek         {min_savings_ratio=0.25, mode adaptive, ccr=False, citations=False, strategy=extract}
  deepseek+anchor  the same plus anchor_errors=True (texts <= 20K only: the plan's interim rule)
  hermes           the option set of hermes_tameru_plugin/engine.py::_compress (defaults of config.py)

Usage
  python benchmarks/latency.py                       # full run, prints table
  python benchmarks/latency.py --quick               # fewer reps, no 2M cells (CI-like)
  python benchmarks/latency.py --out benchmarks/latency-1.9.0.json
  python benchmarks/latency.py --compare PREV.json   # exit 1 if any p50 is >10% slower than PREV
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import tameru  # noqa: E402
from tameru import compress_context as cc  # noqa: E402

SIZES = {"6-20K": 16_000, "50K": 50_000, "200K": 200_000, "2M": 2_000_000, "4M": 4_000_000}
# (p50 ms, p95 ms) budgets for the next release.
BUDGETS = {"6-20K": (60, 150), "50K": (200, 400), "200K": (800, 1500), "2M": (6000, 10000), "4M": (2000, 2000)}
REPS = {"6-20K": 15, "50K": 15, "200K": 15, "2M": 5, "4M": 3}
QUICK_REPS = {"6-20K": 5, "50K": 5, "200K": 3, "2M": 0, "4M": 0}
REGRESSION = 1.10
CELL_TIMEOUT_S = 90  # guard for the 2M class (child process, killed on expiry)
SEED = 20260101


# ---------------------------------------------------------------- synthetic inputs
def _gen_build_log(rng: random.Random, size: int) -> str:
    out, n = [], 0
    mods = ["core", "net", "auth", "store", "render", "cli", "sync"]
    while n < size:
        i = len(out)
        m = rng.choice(mods)
        r = rng.random()
        if r < 0.02:
            line = f"ERROR: test_{m}_{rng.randint(1, 99)} failed: AssertionError: expected {rng.randint(1, 9)} got {rng.randint(10, 99)}"
        elif r < 0.04:
            line = f"WARNING: deprecated call in {m}/mod_{rng.randint(1, 50)}.py:{rng.randint(1, 900)}"
        elif r < 0.5:
            line = f"[{i:06d}] compiling {m}/unit_{rng.randint(1, 400)}.c -> build/{m}/unit_{rng.randint(1, 400)}.o ({rng.randint(5, 900)} ms)"
        else:
            line = f"[{i:06d}] PASSED tests/{m}/test_case_{rng.randint(1, 800)}.py::test_{rng.choice(['ok', 'edge', 'roundtrip', 'cache'])} in {rng.random():.3f}s"
        out.append(line)
        n += len(line) + 1
    # a few fixed errors at deterministic spots
    for pos in (len(out) // 5, len(out) // 2, (4 * len(out)) // 5):
        out[pos] = f"ERROR: build step {pos} failed: undefined reference to `render_frame_{pos % 7}' (exit status 1)"
    out.append("FAILED tests/render/test_case_17.py::test_edge - AssertionError")
    out.append("=== 3 failed, %d passed in %.1fs ===" % (len(out), len(out) / 90))
    return "\n".join(out)


def _gen_java_trace(rng: random.Random, size: int) -> str:
    out, n = [], 0
    pk = ["com.acme.order", "com.acme.billing", "org.spring.web", "org.hibernate.engine", "java.base/java.lang"]
    while n < size:
        ts = f"2026-03-{rng.randint(1, 28):02d} 12:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d},{rng.randint(0, 999):03d}"
        if rng.random() < 0.12:
            head = [
                f"{ts} ERROR [http-nio-8080-exec-{rng.randint(1, 20)}] c.a.o.OrderService - request {rng.randint(1000, 9999)} failed",
                f"java.lang.IllegalStateException: order {rng.randint(1000, 9999)} has no payment",
            ]
            frames = [f"\tat {rng.choice(pk)}.Class{rng.randint(1, 60)}.method{rng.randint(1, 30)}(Class{rng.randint(1, 60)}.java:{rng.randint(10, 800)})"
                      for _ in range(rng.randint(8, 25))]
            cause = [
                f"Caused by: java.sql.SQLException: connection {rng.randint(1, 50)} reset",
                *[f"\tat {rng.choice(pk)}.Dao{rng.randint(1, 20)}.query{rng.randint(1, 9)}(Dao.java:{rng.randint(10, 400)})" for _ in range(rng.randint(5, 12))],
                f"\t... {rng.randint(10, 40)} more",
            ]
            block = head + frames + cause
        else:
            block = [f"{ts} INFO  [scheduler-{rng.randint(1, 8)}] c.a.b.Job{rng.randint(1, 30)} - processed {rng.randint(1, 500)} items in {rng.randint(1, 900)} ms"]
        out.extend(block)
        n += sum(len(x) + 1 for x in block)
    return "\n".join(out)


def _gen_json_array(rng: random.Random, size: int) -> str:
    rows, n = [], 2
    i = 0
    while n < size:
        row = {
            "id": i, "name": f"user_{rng.randint(1, 5000)}", "email": f"u{rng.randint(1, 99999)}@example.org",
            "status": rng.choice(["active", "inactive", "pending"]), "score": round(rng.random() * 100, 2),
            "tags": [rng.choice(["a", "b", "c", "d", "e"]) for _ in range(rng.randint(0, 4))],
            "address": {"city": rng.choice(["Oslo", "Lima", "Pune", "Graz"]), "zip": str(rng.randint(10000, 99999))},
        }
        if rng.random() < 0.01:
            row["error"] = f"validation failed: field {rng.choice(['email', 'zip'])} rejected"
        s = json.dumps(row)
        rows.append(s)
        n += len(s) + 2
        i += 1
    return "[\n" + ",\n".join(rows) + "\n]"


def _gen_source(rng: random.Random, size: int) -> str:
    out, n, ln = [], 0, 1
    fn = 0
    while n < size:
        fn += 1
        body = [
            f"def handle_{fn}(request, ctx):",
            f'    """Handle step {fn} of the pipeline."""',
            f"    limit = ctx.get('limit_{fn % 9}', {rng.randint(1, 100)})",
            "    items = [i for i in request.items if i.valid]",
            f"    if len(items) > limit:",
            f"        raise ValueError('too many items for step {fn}')",
            f"    total = sum(i.price * i.qty for i in items)",
            f"    ctx.log('step {fn}', total=total)",
            "    return {'total': total, 'count': len(items)}",
            "",
        ]
        for b in body:
            line = f"{ln:5d}  {b}"
            out.append(line)
            n += len(line) + 1
            ln += 1
    return "\n".join(out)


CONTENT = {
    "build_log": (_gen_build_log, "which build step failed and why undefined reference render_frame"),
    "java_trace": (_gen_java_trace, "why did the order request fail with IllegalStateException no payment"),
    "json_array": (_gen_json_array, "which records have a validation error and what field was rejected"),
    "source": (_gen_source, "where is the ValueError raised for too many items in step 7"),
}
TOOL_CALL = {
    "build_log": 'terminal {"command": "make -j8 && pytest -x"} the build is red, tell me what broke',
    "java_trace": 'read_file {"path": "logs/app.log", "tail": 2000} find what is wrong with the checkout service',
    "json_array": 'http_get {"url": "https://api.example.org/users?limit=5000"} list the users that look broken',
    "source": 'read_file {"path": "src/pipeline.py"} explain how step 7 validates its items',
}


def make_query(kind: str, cond: str) -> str:
    if cond == "task":
        return CONTENT[kind][1]
    if cond == "toolcall":
        return TOOL_CALL[kind]
    return "continue"


# ---------------------------------------------------------------- profiles
def _elision_marker(omitted: int, total: int) -> str:
    return f"[... {omitted} of {total} lines omitted ...]"


def profile_kwargs(profile: str) -> dict:
    if profile == "deepseek":
        return dict(min_savings_ratio=0.25, mode="adaptive", ccr=False, citations=False, strategy="extract")
    if profile == "deepseek+anchor":
        return dict(min_savings_ratio=0.25, mode="adaptive", ccr=False, citations=False, strategy="extract",
                    anchor_errors=True)
    if profile == "hermes":  # hermes_tameru_plugin.engine.TameruEngine._compress, config.py defaults
        return dict(ccr=False, citations=False, content_hint=None, pin_patterns=None, gap_marker=_elision_marker,
                    inline_short_gaps=True, anchor_errors=True, prose_brief=True,
                    recursion_markers=("[tameru:",), min_savings_ratio=0.10)
    raise ValueError(profile)


def profiles_for(size_class: str) -> list[str]:
    ps = ["deepseek"]
    if SIZES[size_class] <= 20_000:
        ps.append("deepseek+anchor")
    ps.append("hermes")
    return ps


# ---------------------------------------------------------------- measuring
def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def measure(text: str, query: str, kwargs: dict, n: int) -> list[float]:
    cc.compress_context(text, query, **kwargs)  # untimed warmup
    times = []
    for _ in range(n):
        cc._clear_memos()
        t0 = time.perf_counter()
        cc.compress_context(text, query, **kwargs)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def _child(conn, kind, size, query, kwargs, n):
    text = CONTENT[kind][0](random.Random(f"{SEED}:{kind}:{size}"), size)
    cc.compress_context(text, query, **kwargs)  # untimed warmup
    conn.send(("warm", 0.0))
    for _ in range(n):
        cc._clear_memos()
        t0 = time.perf_counter()
        cc.compress_context(text, query, **kwargs)
        conn.send(("t", (time.perf_counter() - t0) * 1000))
    conn.send(("done", 0.0))


def measure_guarded(kind: str, size: int, query: str, kwargs: dict, n: int, timeout_s: float) -> tuple[list[float], bool]:
    """Run a cell in a child process; stop it after ``timeout_s`` seconds. Returns (times, timed_out)."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(child, kind, size, query, kwargs, n), daemon=True)
    proc.start()
    deadline = time.monotonic() + timeout_s
    times, done = [], False
    while not done:
        left = deadline - time.monotonic()
        if left <= 0 or not parent.poll(left):
            break
        tag, val = parent.recv()
        if tag == "t":
            times.append(val)
        done = tag == "done"
    proc.terminate()
    proc.join()
    return times, not done


def run(quick: bool, only_size: set[str] | None) -> list[dict]:
    reps = QUICK_REPS if quick else REPS
    machine = f"{platform.system()} {platform.machine()} cpus={os.cpu_count()}"
    rows = []
    for size_class, size in SIZES.items():
        n = reps[size_class]
        if n == 0 or (only_size and size_class not in only_size):
            continue
        for kind, (gen, _) in CONTENT.items():
            guarded = size >= 1_000_000
            text = None if guarded else gen(random.Random(f"{SEED}:{kind}:{size}"), size)
            for cond in ("task", "toolcall", "generic"):
                query = make_query(kind, cond)
                for profile in profiles_for(size_class):
                    timed_out = False
                    if guarded:
                        t, timed_out = measure_guarded(kind, size, query, profile_kwargs(profile), n, CELL_TIMEOUT_S)
                    else:
                        t = measure(text, query, profile_kwargs(profile), n)
                    row = {
                        "bench": "latency", "engine": tameru.__version__, "profile": profile,
                        "size_class": size_class, "content": kind, "query_condition": cond, "n": n,
                        "p50_ms": round(pct(t, 0.5), 2) if t else None,
                        "p95_ms": round(pct(t, 0.95), 2) if t else None,
                        "python": platform.python_version(), "machine": machine,
                        "memo": "cleared", "chars": size if guarded else len(text),
                    }
                    if guarded:
                        row["n"] = len(t)
                        if timed_out:
                            row["timeout_s"] = CELL_TIMEOUT_S
                            row["note"] = f"cell exceeded {CELL_TIMEOUT_S}s guard after {len(t)} timed reps"
                    rows.append(row)
                    print(f"  {size_class:6} {profile:16} {kind:10} {cond:9} p50={row['p50_ms'] or float('nan'):>9.1f} "
                          f"p95={row['p95_ms'] or float('nan'):>9.1f} ms{'  TIMEOUT' if timed_out else ''}", flush=True)
    return rows


def verdict(row: dict) -> str:
    b50, b95 = BUDGETS[row["size_class"]]
    if row["p50_ms"] is None:
        return "OVER(timeout)"
    return "PASS" if row["p50_ms"] <= b50 and row["p95_ms"] <= b95 else "OVER"


def table(rows: list[dict]) -> None:
    print(f"\nengine {tameru.__version__}  python {platform.python_version()}  cpus {os.cpu_count()}")
    print(f"{'size':6} {'profile':16} {'content':10} {'query':9} {'n':>3} {'p50 ms':>10} {'p95 ms':>10}  budget(p50/p95)  verdict")
    for r in rows:
        b = BUDGETS[r["size_class"]]
        print(f"{r['size_class']:6} {r['profile']:16} {r['content']:10} {r['query_condition']:9} {r['n']:>3} "
              f"{r['p50_ms'] if r['p50_ms'] is not None else float('nan'):>10.1f} {r['p95_ms'] if r['p95_ms'] is not None else float('nan'):>10.1f}  {b[0]:>6}/{b[1]:<8} {verdict(r)}")
    over = [r for r in rows if verdict(r) == "OVER"]
    print(f"\n{len(rows) - len(over)} PASS, {len(over)} OVER (budgets are for the next release; OVER does not fail the run)")


def key(r: dict) -> tuple:
    return (r["profile"], r["size_class"], r["content"], r["query_condition"])


def compare(rows: list[dict], prev_path: str) -> int:
    prev = {key(r): r for r in json.loads(Path(prev_path).read_text(encoding="utf-8"))}
    bad = []
    for r in rows:
        p = prev.get(key(r))
        if p and r["p50_ms"] is None and p["p50_ms"] is not None:
            bad.append((r, p))
        elif p and None not in (r["p50_ms"], p["p50_ms"]) and r["p50_ms"] > p["p50_ms"] * REGRESSION:
            bad.append((r, p))
    print(f"\ncompare vs {prev_path}: {len(bad)} cell(s) with p50 >10% slower")
    for r, p in bad:
        if r["p50_ms"] is None:
            print(f"  {key(r)}: {p['p50_ms']:.1f} ms -> TIMEOUT")
        else:
            print(f"  {key(r)}: {p['p50_ms']:.1f} -> {r['p50_ms']:.1f} ms ({r['p50_ms'] / p['p50_ms'] - 1:+.0%})")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="few reps, skip the 2M class")
    ap.add_argument("--sizes", help="comma list of size classes to run, e.g. 6-20K,50K")
    ap.add_argument("--out", help="write rows as JSON here (inside benchmarks/)")
    ap.add_argument("--compare", metavar="PREV.json", help="fail if any p50 is >10%% slower than PREV")
    a = ap.parse_args()
    rows = run(a.quick, set(a.sizes.split(",")) if a.sizes else None)
    table(rows)
    if a.out:
        out = Path(a.out).resolve()
        if out.parent != Path(__file__).resolve().parent:
            ap.error("--out must be inside the benchmarks directory")
        out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return compare(rows, a.compare) if a.compare else 0


if __name__ == "__main__":
    sys.exit(main())
