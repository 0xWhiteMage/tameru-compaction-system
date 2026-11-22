#!/usr/bin/env python
"""Peak memory of one ``compress_context`` call (stdlib only): the round-2 S7 memory gate.

Every cell = (engine, size, content kind, profile).  Inputs are latency.py's seeded generators at 1M, 2M, 4M and 8M
characters with the kind's task query; the profiles are latency.py's 2M-class profiles (deepseek, hermes).  Every
measurement runs in a fresh child process that

  1. imports the engine under test and runs one small call on other text (imports, regex compilation),
  2. reads the input by decoding a memory-mapped file, so no freed heap copy of the input is left for the call to reuse,
  3. clears the engine's memos, collects garbage and reads the working set (RSS),
  4. makes the call and reads the process's peak working set.

Growth = peak after the call - RSS before it.  Where the peak did not move during the call (Windows cannot reset it, so
an earlier peak can mask the call's), the row is marked ``masked`` and its growth is the highest working set a 0.5 ms
sampler thread saw during the call instead, a lower bound.  A cell is the median of ``--reps`` children.

Gate (ANALYSIS-PLAN-ROUND2.md, 2026-11-22 maintainer exception): every cell's growth <= 64 MiB, and <= 1.10x the
same cell on the 1.10.0 engine (``--baseline``, default e638509, whose src/tameru is unchanged since 7a7bb83).

Usage
  python benchmarks/memory.py --out benchmarks/memory-<label>.json
  python benchmarks/memory.py --sizes 2M --reps 1          # one size, quick look
  python benchmarks/memory.py --baseline ''                # no baseline cells
  python benchmarks/memory.py --candidate 6a40d6f          # a committed engine instead of the working tree
"""
from __future__ import annotations

import argparse
import codecs
import functools
import gc
import io
import json
import mmap
import random
import statistics
import subprocess
import sys
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZES = {"1M": 1_000_000, "2M": 2_000_000, "4M": 4_000_000, "8M": 8_000_000}
PROFILES = ("deepseek", "hermes")
CAP_BYTES = 64 << 20          # the S7 content cache's own budget (content_cache._DEFAULT_MAX_BYTES)
NO_REGRESSION = 1.10
MIB = 1 << 20


@functools.cache
def _reader():
    """A function returning (current RSS, peak RSS) of this process, in bytes."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        c = Counters()
        c.cb = ctypes.sizeof(Counters)
        handle, ref = kernel32.GetCurrentProcess(), ctypes.byref(c)

        def read() -> tuple[int, int]:
            if not psapi.GetProcessMemoryInfo(handle, ref, c.cb):
                raise OSError("GetProcessMemoryInfo failed")
            return c.WorkingSetSize, c.PeakWorkingSetSize
        return read

    def read() -> tuple[int, int]:
        fields = dict(ln.split(":", 1) for ln in Path("/proc/self/status").read_text().splitlines() if ":" in ln)
        return int(fields["VmRSS"].split()[0]) * 1024, int(fields["VmHWM"].split()[0]) * 1024
    return read


def _mem() -> tuple[int, int]:
    """(current RSS, peak RSS) of this process, in bytes."""
    return _reader()()


def _reset_peak() -> None:
    """Linux: start the peak (VmHWM) from the current RSS.  Windows has no reset; ``masked`` covers it."""
    if sys.platform != "win32":
        try:
            Path("/proc/self/clear_refs").write_text("5")
        except OSError:
            pass


def child(args: argparse.Namespace) -> None:
    src = Path(args.engine_src).resolve()
    sys.path.insert(0, str(src))
    import tameru
    from tameru import compress_context as cc
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import latency  # its own ``import tameru`` finds the engine under test already loaded
    assert Path(tameru.__file__).resolve().is_relative_to(src), (tameru.__file__, str(src))
    kwargs = latency.profile_kwargs(args.profile)
    query = latency.make_query(args.kind, "task")
    cc.compress_context(latency.CONTENT[args.kind][0](random.Random("memory-warmup"), 20_000), query, **kwargs)
    with open(args.input, "rb") as fh:
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        view = memoryview(mm)
        text = codecs.utf_8_decode(view, "strict", True)[0]
        view.release()
        mm.close()
    cc._clear_memos()
    gc.collect()
    row = {"engine": tameru.__version__, "chars": len(text), "in_memory": sys.getsizeof(text)}
    if args.tracemalloc:
        import tracemalloc
        tracemalloc.start()
        cc.compress_context(text, query, **kwargs)
        row["tracemalloc_peak"] = tracemalloc.get_traced_memory()[1]
    else:
        # Windows cannot reset the peak: a sampler of the current working set measures a call the earlier peak masks
        stop, top = threading.Event(), [0]

        def sample() -> None:
            while not stop.is_set():
                top[0] = max(top[0], _mem()[0])
                time.sleep(0.0005)
        sys.setswitchinterval(0.0005)
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        _reset_peak()
        rss0, peak0 = _mem()
        cc.compress_context(text, query, **kwargs)
        rss1, peak1 = _mem()
        stop.set()
        sampler.join()
        masked = peak1 <= peak0
        sampled = max(top[0], rss1)
        row.update(rss_before=rss0, peak_before=peak0, peak_after=peak1, sampled_top=sampled,
                   growth=(sampled if masked else peak1) - rss0, masked=masked)
    print(json.dumps(row))


def _engine_src(rev: str, work: Path) -> Path:
    """``src`` of the engine at ``rev`` (git archive of src/tameru), or this checkout's ``src`` for ''."""
    if not rev:
        return ROOT / "src"
    dest = work / f"engine-{rev}"
    if not (dest / "src" / "tameru" / "__init__.py").exists():
        blob = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", rev, "src/tameru"],
                              check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
            tf.extractall(dest, filter="data")
    return dest / "src"


def _inputs(sizes: list[str], work: Path) -> dict[tuple[str, str], Path]:
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import latency
    paths = {}
    for size in sizes:
        for kind, (gen, _query) in latency.CONTENT.items():
            path = work / "inputs" / f"{kind}-{size}.txt"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(gen(random.Random(f"{latency.SEED}:{kind}:{SIZES[size]}"), SIZES[size]),
                                encoding="utf-8", newline="")
            paths[(kind, size)] = path
    return paths


def _run_child(src: Path, inp: Path, kind: str, profile: str, tracemalloc: bool, timeout: float) -> dict:
    cmd = [sys.executable, __file__, "--child", "--engine-src", str(src), "--input", str(inp),
           "--kind", kind, "--profile", profile] + (["--tracemalloc"] if tracemalloc else [])
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout:.0f}s"}
    if done.returncode != 0:
        return {"error": (done.stderr.strip().splitlines() or ["exit %d" % done.returncode])[-1]}
    return json.loads(done.stdout.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--engine-src", help=argparse.SUPPRESS)
    ap.add_argument("--input", help=argparse.SUPPRESS)
    ap.add_argument("--kind", help=argparse.SUPPRESS)
    ap.add_argument("--profile", help=argparse.SUPPRESS)
    ap.add_argument("--tracemalloc", action="store_true", help="child: report tracemalloc's peak instead of RSS")
    ap.add_argument("--sizes", default=",".join(SIZES), help="comma list of " + ",".join(SIZES))
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per child")
    ap.add_argument("--baseline", default="e638509", help="git rev of the 1.10.0 engine ('' = none)")
    ap.add_argument("--candidate", default="", help="git rev of the engine under test ('' = this working tree)")
    ap.add_argument("--work", default=str(ROOT / "build" / "memory"))
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.child:
        child(args)
        return 0

    work = Path(args.work)
    sizes = [s for s in args.sizes.split(",") if s]
    inputs = _inputs(sizes, work)
    engines = {"candidate": _engine_src(args.candidate, work)}
    if args.baseline:
        engines["1.10.0"] = _engine_src(args.baseline, work)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", args.candidate or "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = not args.candidate and bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src/tameru"],
                                                       capture_output=True, text=True).stdout.strip())
    jobs = [(label, size, kind, profile, rep, tm)
            for label in engines for size in sizes for (kind, s) in inputs if s == size
            for profile in PROFILES for rep in range(args.reps + 1) for tm in (False, True)
            if tm == (rep == args.reps)]  # reps RSS children, then one tracemalloc child
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda j: (j, _run_child(engines[j[0]], inputs[(j[2], j[1])], j[2], j[3], j[5],
                                                          args.timeout)), jobs))

    cells: dict[tuple[str, str, str, str], dict] = {}
    for (label, size, kind, profile, _rep, tm), res in results:
        cell = cells.setdefault((label, size, kind, profile), {"growths": [], "masked": False, "errors": []})
        if "error" in res:
            cell["errors"].append(res["error"])
        elif tm:
            cell["tracemalloc_peak"] = res["tracemalloc_peak"]
        else:
            cell["growths"].append(res["growth"])
            cell["masked"] |= res["masked"]
            cell.update(chars=res["chars"], in_memory=res["in_memory"], engine=res["engine"])
    rows = []
    for (label, size, kind, profile), cell in sorted(cells.items(), key=lambda kv: (kv[0][0], SIZES[kv[0][1]], kv[0][2], kv[0][3])):
        growth = statistics.median(cell["growths"]) if cell["growths"] else None
        row = {"engine": label, "version": cell.get("engine"), "size_class": size, "content": kind, "profile": profile,
               "chars": cell.get("chars"), "in_memory": cell.get("in_memory"), "reps": len(cell["growths"]),
               "growth_bytes": growth, "growth_mib": round(growth / MIB, 2) if growth is not None else None,
               "growth_x_chars": round(growth / cell["chars"], 2) if growth is not None else None,
               "masked": cell["masked"], "tracemalloc_peak": cell.get("tracemalloc_peak"), "errors": cell["errors"]}
        if label == "candidate":
            base = cells.get(("1.10.0", size, kind, profile))
            base_growth = statistics.median(base["growths"]) if base and base["growths"] else None
            row["cap_ok"] = growth is not None and growth <= CAP_BYTES
            row["vs_1_10_0"] = round(growth / base_growth, 3) if growth is not None and base_growth else None
            row["no_regression_ok"] = None if row["vs_1_10_0"] is None else row["vs_1_10_0"] <= NO_REGRESSION
        rows.append(row)

    print(f"engine src at {head}{' (src/tameru modified)' if dirty else ''}; python {sys.version.split()[0]}; {sys.platform}")
    print(f"{'engine':9} {'size':4} {'content':10} {'profile':8} {'MiB':>7} {'x chars':>7} {'tm x':>6} {'vs 1.10.0':>9}  verdict")
    for r in rows:
        tm = r["tracemalloc_peak"] / r["chars"] if r["tracemalloc_peak"] and r["chars"] else float("nan")
        verdict = ""
        if r["engine"] == "candidate":
            verdict = "PASS" if r["cap_ok"] and r["no_regression_ok"] is not False else "FAIL"
            verdict += "" if r["no_regression_ok"] is not None else " (no baseline)"
        verdict += " masked" if r["masked"] else ""
        verdict += f" errors={r['errors']}" if r["errors"] else ""
        print(f"{r['engine']:9} {r['size_class']:4} {r['content']:10} {r['profile']:8} "
              f"{r['growth_mib'] if r['growth_mib'] is not None else float('nan'):>7.1f} "
              f"{r['growth_x_chars'] if r['growth_x_chars'] is not None else float('nan'):>7.2f} {tm:>6.2f} "
              f"{r['vs_1_10_0'] if r.get('vs_1_10_0') is not None else float('nan'):>9.3f}  {verdict}")
    gated = [r for r in rows if r["engine"] == "candidate"]
    failed = [r for r in gated if not (r["cap_ok"] and r["no_regression_ok"] is not False)]
    print(f"\n{len(gated) - len(failed)} PASS, {len(failed)} FAIL (cap {CAP_BYTES // MIB} MiB; <= {NO_REGRESSION}x the 1.10.0 cell)")
    if args.out:
        Path(args.out).write_text(json.dumps({"bench": "memory", "head": head, "src_modified": dirty,
                                              "baseline": args.baseline, "python": sys.version.split()[0],
                                              "platform": sys.platform, "rows": rows}, indent=1) + "\n",
                                  encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
