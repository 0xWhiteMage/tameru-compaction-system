"""E2: quadratic hot spots are gone — asserted as SCALING, not milliseconds.

Every timing test compares the cost of an input with the cost of the same
input shape at 4x the size and requires ``time(4x) < 6 x time(1x)`` (a linear
algorithm gives ~4, a quadratic one ~16). Absolute times depend on the machine
and are never asserted. These are marked ``perf``; run only them with
``pytest -m perf`` or skip them with ``-m "not perf"``.

What was quadratic in 1.3.0 (a 650 KB INFO/ERROR log took 28-35 s):

* ``_critical_line_recall`` lowercased the whole compressed text once per
  critical line, and then searched it once per line;
* ``_summary_preserves_required_facts`` tested ``token not in required`` on a
  list;
* ``_PATH_RE``, ``_SUMMARY_STRUCTURED_TOKEN_RE`` and the ``[\\w]+[=:]`` pattern
  of ``_extract_critical_lines`` backtracked over long separator-free runs;
* the bridge-entity pass scanned every block for every dotted/quoted candidate.
"""
from __future__ import annotations

import random
import re
import time

import pytest

from tameru import compress_context as cc
from tameru.compress_context import compress_context

RATIO_LIMIT = 6.0  # time(4x) must stay below this multiple of time(1x)
NOISE_FLOOR = 0.004  # seconds: below this a timing is dominated by the timer


def best_of(fn, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def assert_scales_linearly(run_small, run_large, what: str, attempts: int = 3) -> None:
    """Pass if ANY of up to ``attempts`` measurements of the 4x/1x cost ratio is
    under the limit. A quadratic algorithm is ~16x on every attempt; a linear
    one only exceeds 6x when the machine is busy for a whole measurement."""
    seen = []
    for _ in range(attempts):
        small = best_of(run_small)
        large = best_of(run_large)
        ratio = large / max(small, NOISE_FLOOR)
        seen.append((ratio, small, large))
        if ratio < RATIO_LIMIT:
            return
    ratio, small, large = min(seen)
    raise AssertionError(
        f"{what}: 4x input cost {large:.3f}s vs {small:.3f}s (x{ratio:.1f}); "
        f"limit x{RATIO_LIMIT:g} (best of {attempts} attempts)"
    )


ERRORS = [
    "ERROR w{w} upstream timeout calling payments-svc after {n}ms req={h}",
    "ERROR w{w} db pool exhausted: 0 of {n} connections (pool=orders)",
    "ERROR w{w} failed to decode /api/v2/inventory/{h}: unexpected EOF",
    "ERROR w{w} circuit breaker OPEN for auth-svc after {n} failures",
    "ERROR w{w} TLS handshake with 10.0.{m}.7:443 failed: certificate expired",
]
INFOS = [
    "INFO  w{w} GET /api/v1/users/{h}/profile 200 {n}ms",
    "INFO  w{w} POST /api/v1/orders/{h} 201 {n}ms",
    "INFO  w{w} cache hit key=session:{h} ttl={n}s",
    "INFO  w{w} job sync-{n} done path=/var/jobs/{h}.json",
    "INFO  w{w} heartbeat ok node-{m} up={n}s",
    "INFO  w{w} loaded /etc/app/conf.d/{h}.yaml",
]


def make_log(n_lines: int, seed: int = 11, error_rate: float = 0.01) -> str:
    rng = random.Random(seed)
    out = []
    for i in range(n_lines):
        ts = f"2026-03-14 {12 + i // 3600 % 12:02d}:{i // 60 % 60:02d}:{i % 60:02d}"
        fields = dict(
            w=rng.randint(1, 16),
            h="%08x" % rng.getrandbits(32),
            n=rng.randint(1, 50000),
            m=rng.randint(1, 250),
        )
        pool = ERRORS if rng.random() < error_rate else INFOS
        out.append(ts + " " + rng.choice(pool).format(**fields))
    return "\n".join(out)


# ------------------------------------------------------------ the whole pipeline


@pytest.mark.perf
@pytest.mark.parametrize("query", ["why are requests failing?", "continue"])
def test_compress_context_scales_linearly_on_a_log(query):
    small_log, large_log = make_log(2000), make_log(8000)
    assert_scales_linearly(
        lambda: compress_context(small_log, query, ccr=False, citations=False),
        lambda: compress_context(large_log, query, ccr=False, citations=False),
        f"compress_context({query!r})",
    )


@pytest.mark.perf
def test_compress_context_scales_linearly_with_a_distinctive_query():
    small_log, large_log = make_log(2000), make_log(8000)
    query = "which request hit upstream timeout payments-svc?"
    assert_scales_linearly(
        lambda: compress_context(small_log, query, ccr=False, citations=False),
        lambda: compress_context(large_log, query, ccr=False, citations=False),
        "compress_context(needle query)",
    )


@pytest.mark.perf
def test_650kb_log_completes_in_seconds_not_half_a_minute():
    """Sanity ceiling an order of magnitude above the measured time. The 1.3.0
    engine needed 22-35 s for this input."""
    log = make_log(9000)
    assert 600_000 < len(log) < 700_000
    start = time.perf_counter()
    result = compress_context(log, "why are requests failing?", ccr=False, citations=False)
    elapsed = time.perf_counter() - start
    assert not result.fail_open
    assert elapsed < 15.0, f"650 KB log took {elapsed:.1f}s"


# ------------------------------------------------------------------ verifier loop


@pytest.mark.perf
def test_critical_line_recall_scales_linearly():
    def case(n_lines: int):
        original = make_log(n_lines)
        lines = original.split("\n")
        compressed = "\n".join(
            ln if i % 5 else "[…]" for i, ln in enumerate(lines)
        )  # ~80% kept, non-ASCII marker present
        return original, compressed

    small_case, large_case = case(3000), case(12000)
    assert_scales_linearly(
        lambda: cc._critical_line_recall(*small_case),
        lambda: cc._critical_line_recall(*large_case),
        "_critical_line_recall",
    )


def test_critical_line_recall_result_is_exact():
    original = "\n".join(
        [
            "2026-03-14 12:00:01 ERROR upstream timeout after 5ms",
            "2026-03-14 12:00:02 INFO  heartbeat ok",
            "host=db1 port=5432 user=app",
            "    indented key=value line that is long enough",
            "[×3] 2026-03-14 12:00:03 ERROR retrying connection",
            "deployed version 1.4.0 to prod",
        ]
    )
    compressed = "\n".join(
        [
            "2026-03-14 12:00:01 ERROR upstream timeout after 5ms",  # whole line
            "[×3] host=db1 port=5432 user=app",  # collapse prefix
            "  indented key=value line that is long enough  ",  # re-indented
            "  [×3] 2026-03-14 12:00:03 ERROR retrying connection and more",  # core inside a longer line
        ]
    )
    kept, total = cc._critical_line_recall(original, compressed)
    critical = cc._extract_critical_lines(original)
    assert total == len(critical) == 5  # the INFO heartbeat is not critical
    # A longer, changed line is not evidence that its original facts survived.
    assert kept == 3


@pytest.mark.perf
def test_summary_fact_gate_scales_linearly():
    def case(n: int):
        source = "\n".join(f"host db-{i} port {5000 + i} status ok" for i in range(n))
        return source, source, "host port"

    small_case, large_case = case(1500), case(6000)
    assert_scales_linearly(
        lambda: cc._summary_preserves_required_facts(*small_case),
        lambda: cc._summary_preserves_required_facts(*large_case),
        "_summary_preserves_required_facts",
    )


def test_summary_fact_gate_answers_are_unchanged():
    source = "host db-prod-01 port 5432 role primary\nthe paint color is ultraviolet\n"
    good = "host db-prod-01 port 5432"
    assert cc._summary_preserves_required_facts(source, good, "host db-prod-01") == (True, 1.0)
    ok, recall = cc._summary_preserves_required_facts(source, "host db-prod-01", "host db-prod-01")
    assert not ok and recall < 1.0  # port 5432 is required and missing
    ok, _ = cc._summary_preserves_required_facts(source, good + " db-prod-99", "host db-prod-01")
    assert not ok  # a novel structured id


# --------------------------------------------------------- backtracking regexes

SHAPES = {
    "word-run": lambda n: "a" * n,
    "dotted": lambda n: "a." * (n // 2),
    "hyphenated": lambda n: "ab-" * (n // 3),
    "colon-run": lambda n: "a:" * (n // 2),
    "slash-run": lambda n: "ab/" * (n // 3),
    "hex-and-dots": lambda n: "deadbeef.0123456789abcdef." * (n // 26),
    "scheme-ish": lambda n: "a-" * (n // 2) + "x",
}

PATTERNS = {
    "_PATH_RE": lambda s: cc._PATH_RE.findall(s),
    "_SUMMARY_STRUCTURED_TOKEN_RE": lambda s: cc._SUMMARY_STRUCTURED_TOKEN_RE.findall(s),
    "_URI_RE": lambda s: cc._URI_RE.findall(s),
    "_extract_critical_lines": lambda s: cc._extract_critical_lines(s),
    "_extract_entities": lambda s: cc._extract_entities(s),
}


@pytest.mark.perf
@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("pattern", sorted(PATTERNS))
def test_long_runs_do_not_backtrack_quadratically(pattern, shape):
    run = PATTERNS[pattern]
    small_text, large_text = SHAPES[shape](10_000), SHAPES[shape](40_000)
    assert_scales_linearly(
        lambda: run(small_text), lambda: run(large_text), f"{pattern} on a {shape} run"
    )


@pytest.mark.perf
def test_a_20k_char_run_inside_a_document_is_cheap_end_to_end():
    def doc(n: int) -> str:
        blob = "k" * n
        filler = "\n".join(f"line {i}: routine output" for i in range(60))
        return f"{filler}\n{blob}\nERROR boom key={blob[:8]}\n{filler}"

    small_doc, large_doc = doc(10_000), doc(40_000)
    query = "where is boom?"
    assert_scales_linearly(
        lambda: compress_context(small_doc, query, ccr=False, citations=False),
        lambda: compress_context(large_doc, query, ccr=False, citations=False),
        "compress_context on a long separator-free run",
    )


# --------------------------------------- bounded regexes keep their old meaning

OLD_PATH = re.compile(r"(?:[\w.-]+/){2,}[\w.-]+")
OLD_STRUCT = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9_.:/-]*\d[A-Za-z0-9_.:/-]*|\d+(?:[.:/-]\d+)*)\b"
)
OLD_KV = re.compile(r"[\w]+[=:]\s*[\w][\w.-]*")
OLD_URI = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+")

WORDS = [
    "src/tameru/x.py", "a/b/c", "http://x.y/z", "v1.2.3", "db-prod-01", "key=value",
    "12:03:45", "foo.bar.baz", "/usr/local/bin", "../a/b/../c", "C:/Users/x",
    "user@host:~/dir", "2026-03-14", "sha256:abcdef0123456789", "ftp://h/p", "x://",
    "a//b///c", "...", "--flag=1", "a-b-c-1", "naïve/日本語/path",
]
ALPHABET = list("abcXYZ019_.-/:= \t\n[]()\"'é中")


def test_bounded_regexes_match_the_unbounded_ones_on_normal_text():
    rng = random.Random(1)
    for _ in range(4000):
        parts = []
        for _ in range(rng.randint(1, 12)):
            if rng.random() < 0.5:
                parts.append(rng.choice(WORDS))
            else:
                parts.append("".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 20))))
        text = " ".join(parts)
        assert cc._PATH_RE.findall(text) == OLD_PATH.findall(text), text
        assert cc._SUMMARY_STRUCTURED_TOKEN_RE.findall(text) == OLD_STRUCT.findall(text), text
        assert cc._URI_RE.findall(text) == OLD_URI.findall(text), text
        assert bool(cc._CRITICAL_KV_RE.search(text)) == bool(OLD_KV.search(text)), text


def test_realistic_paths_and_tokens_still_match():
    assert cc._PATH_RE.findall("see /var/log/app/error.log and src/tameru/x.py now") == [
        "var/log/app/error.log",
        "src/tameru/x.py",
    ]
    assert cc._SUMMARY_STRUCTURED_TOKEN_RE.findall("host db-prod-01 port 5432 v1.2.3") == [
        "db-prod-01",
        "5432",
        "v1.2.3",
    ]
    assert cc._URI_RE.findall("fetch https://example.com/a?b=1 now") == ["https://example.com/a?b=1"]
    assert cc._extract_entities("open src/app/core/x.py via https://h.io/p")[:2] == [
        "https://h.io/p",
        "src/app/core/x.py",
    ]


# ------------------------------------------------ 1.10.0: structural pass, chain folding, early exit, probes


def make_java_chain_log(chains: int, seed: int = 5) -> str:
    """INFO noise plus ``chains`` Java exception chains (head, frames, a cause, ``... N more``)."""
    rng = random.Random(seed)
    out = []
    for c in range(chains):
        out.append(f"2026-03-14 12:{c % 60:02d}:00 INFO  w{rng.randint(1, 9)} job {c} ok id={rng.getrandbits(32):08x}")
        out.append(f"2026-03-14 12:{c % 60:02d}:01 INFO  w{rng.randint(1, 9)} heartbeat {rng.randint(1, 999)}ms")
        out += [f"2026-03-14 12:{c % 60:02d}:02 ERROR [exec-{c}] c.a.Svc - request {c} failed",
                f"java.lang.IllegalStateException: order {c} has no payment"]
        out += [f"\tat org.springframework.web.Layer{i}.step(Layer{i}.java:{10 + i})" for i in range(12)]
        out += [f"Caused by: java.sql.SQLException: connection {c} reset"]
        out += [f"\tat com.acme.Dao{i}.query(Dao{i}.java:{20 + i})" for i in range(9)] + ["\t... 31 more"]
    return "\n".join(out)


@pytest.mark.perf
def test_structural_log_pass_scales_linearly():
    small, large = make_log(2000).split("\n"), make_log(8000).split("\n")
    assert_scales_linearly(
        lambda: cc.structural_log_pass(small), lambda: cc.structural_log_pass(large), "structural_log_pass"
    )


@pytest.mark.perf
def test_chain_folding_scales_linearly():
    small, large = make_java_chain_log(150).split("\n"), make_java_chain_log(600).split("\n")
    assert_scales_linearly(
        lambda: cc.structural_log_pass(small), lambda: cc.structural_log_pass(large), "per-cause chain folding"
    )


@pytest.mark.perf
def test_one_long_stack_scales_linearly():
    def stack(n):
        return ["java.lang.IllegalStateException: deep"] + [f"\tat com.acme.F{i}.run(F{i}.java:{i})" for i in range(n)]

    small, large = stack(4000), stack(16000)
    assert_scales_linearly(lambda: cc.structural_log_pass(small), lambda: cc.structural_log_pass(large), "one long stack")


@pytest.mark.perf
@pytest.mark.parametrize("query", ["continue", "", "what happened to req-9999zz?"])
def test_early_exit_scales_linearly(query):
    small_log, large_log = make_log(2000), make_log(8000)
    kw = dict(ccr=False, citations=False, min_savings_ratio=0.1)
    assert not compress_context(small_log, query, **kw).fail_open
    assert_scales_linearly(
        lambda: compress_context(small_log, query, **kw),
        lambda: compress_context(large_log, query, **kw),
        f"early exit ({query!r})",
    )


@pytest.mark.perf
def test_uninformative_query_probe_on_a_650kb_log_scales_linearly():
    """A generic objective with ``anchor_errors``: above ``_ANCHOR_RETRY_MAX_CHARS`` the two comparison probes are
    skipped, so 4x the text costs about 4x (it used to pay two extra full runs at any size)."""
    small_log, large_log = make_log(2250, seed=3), make_log(9000, seed=3)
    assert 600_000 < len(large_log) < 700_000
    kw = dict(ccr=False, citations=False, anchor_errors=True, min_savings_ratio=0.1)
    q = "tell me about the ratio"
    assert_scales_linearly(
        lambda: compress_context(small_log, q, **kw),
        lambda: compress_context(large_log, q, **kw),
        "uninformative-query probe",
    )


def make_numbered_source(n_funcs: int) -> str:
    out, ln = [], 1
    for fn in range(n_funcs):
        for body in (f"def handle_{fn}(request, ctx):", f"    limit = ctx.get('limit_{fn % 9}', {fn})",
                     "    items = [i for i in request.items if i.valid]",
                     f"    raise ValueError('too many items for step {fn}')", ""):
            out.append(f"{ln:5d}  {body}")
            ln += 1
    return "\n".join(out)


@pytest.mark.perf
def test_large_numbered_source_with_a_task_query_scales_linearly():
    """1.9.0: a 600 KB numbered source with a task query took over two minutes (the sampled format profile read it
    as YAML and the YAML subtree adapter scanned every earlier line for every match)."""
    small, large = make_numbered_source(600), make_numbered_source(2400)
    q = "where is the ValueError raised for too many items in step 7"
    kw = dict(ccr=False, citations=False, min_savings_ratio=0.25)
    assert_scales_linearly(
        lambda: compress_context(small, q, **kw), lambda: compress_context(large, q, **kw),
        "numbered source + task query",
    )


@pytest.mark.perf
def test_yaml_subtree_adapter_scales_linearly():
    from tameru import format_adapters as fa

    def doc(n):
        lines = []
        for i in range(n):
            lines += [f"svc{i}:", f"  name: worker-{i}", "  ports:", f"    - {8000 + i}", f"  note: needle {i}"]
        return "\n".join(lines)

    small, large = doc(1500), doc(6000)
    assert_scales_linearly(
        lambda: fa._adapt_yaml(small, ("needle",), None),
        lambda: fa._adapt_yaml(large, ("needle",), None),
        "_adapt_yaml",
    )
