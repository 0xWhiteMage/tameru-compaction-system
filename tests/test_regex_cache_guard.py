import os
import re
import re._compiler as re_compiler
import traceback

import tameru
from tameru.compress_context import compress_context
from tameru.regex_cache import cached_compile

PKG = os.path.dirname(os.path.abspath(tameru.__file__))

WORDS = [
    a + b
    for a in ("ka", "lo", "mi", "nu", "pe", "ro", "su", "ti", "vo", "ze")
    for b in ("da", "fe", "gi", "ho", "ju", "ky")
]

log = (
    "\n".join(
        f"2026-10-22 10:00:{i % 60:02d} INFO worker {WORDS[i]} processed batch {i}"
        for i in range(60)
    )
    + "\n2026-10-22 10:01:00 ERROR worker kada failed: connection refused\n"
)
prose = " ".join(
    f"The {w} team reviewed {i} change requests and updated the runbook."
    for i, w in enumerate(WORDS)
)
table = (
    "NAME   STATUS   RESTARTS\n"
    + "\n".join(f"{w}-pod   Running   0" for w in WORDS)
    + "\nkada-pod   CrashLoopBackOff   7\n"
)
pkg = (
    "\n".join(f"Collecting {w}==1.0" for w in WORDS)
    + "\nERROR: Could not find a version that satisfies the requirement kada==9.9\n"
)
TEXTS = (log, prose, table, pkg)
QUERIES = [f"why did {w} fail" for w in WORDS[:30]] + [
    f"{a} {b} status" for a, b in zip(WORDS[30:], WORDS[:30])
]


def run_all() -> None:
    for text in TEXTS:
        for query in QUERIES[::3]:
            compress_context(text, query, ccr=False, citations=False)


def test_query_dependent_patterns_bypass_re_cache(monkeypatch):
    run_all()
    re.purge()
    record = []
    orig = re_compiler.compile

    def counting(pattern, *args, **kwargs):
        if any(frame.filename.startswith(PKG) for frame in traceback.extract_stack()[:-1]):
            record.append(str(pattern))
        return orig(pattern, *args, **kwargs)

    monkeypatch.setattr(re_compiler, "compile", counting)
    run_all()

    dynamic = [p for p in record if any(w in p for w in WORDS)]
    assert dynamic == [], (
        f"query-dependent patterns compiled through re's cache: {sorted(set(dynamic))[:10]}"
    )
    assert len(set(record)) <= 128, (
        "too many distinct patterns go through re's module cache; use regex_cache.cached_compile"
    )


def test_cached_compile_memoises():
    cached_compile.cache_clear()
    p1 = cached_compile("ab+c", re.IGNORECASE)
    p2 = cached_compile("ab+c", re.IGNORECASE)
    assert p1 is p2
    assert p1.search("xABBC")
    assert cached_compile("ab+c") is not p1
