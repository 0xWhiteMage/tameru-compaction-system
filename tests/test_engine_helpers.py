"""Public helpers added in 1.4.0: ENGINE_VERSION, error_fingerprints,
brief_context, extract_evidence_lines, contains_secret, and the content_hint
routing argument."""
from __future__ import annotations

import random
import re

import pytest

from tameru import compress_context as cc
from tameru.compress_context import (
    ENGINE_VERSION,
    brief_context,
    compress_context,
    contains_secret,
    error_fingerprints,
    estimate_tokens,
    extract_evidence_lines,
)


def _log(n: int = 3000, seed: int = 5) -> str:
    rng = random.Random(seed)
    errors = [
        "ERROR w{w} upstream timeout calling payments-svc after {n}ms req={h}",
        "ERROR w{w} db pool exhausted: 0 of {n} connections (pool=orders)",
        "FATAL w{w} cannot bind 0.0.0.0:{n}: address in use",
    ]
    warns = ["WARN  w{w} slow response {n}ms from inventory", "WARNING w{w} retry {m}/3"]
    infos = [
        "INFO  w{w} GET /api/v1/users/{h}/profile 200 {n}ms",
        "INFO  w{w} cache hit key=session:{h} ttl={n}s",
        "INFO  w{w} heartbeat ok node-{m} up={n}s",
    ]
    out = []
    for i in range(n):
        f = dict(w=rng.randint(1, 9), h="%08x" % rng.getrandbits(32), n=rng.randint(1, 9999), m=rng.randint(1, 3))
        r = rng.random()
        pool = errors if r < 0.01 else warns if r < 0.03 else infos
        out.append(f"2026-03-14 12:{i // 60 % 60:02d}:{i % 60:02d} " + rng.choice(pool).format(**f))
    return "\n".join(out)


# ----------------------------------------------------------------- ENGINE_VERSION


def test_engine_version_is_a_semver_string():
    assert ENGINE_VERSION == "1.4.0"
    assert re.fullmatch(r"\d+\.\d+\.\d+", ENGINE_VERSION)


# ------------------------------------------------------------- error_fingerprints


def test_fingerprints_cover_levels_exceptions_tracebacks_and_panics():
    text = "\n".join(
        [
            "2026-03-14 12:00:00 INFO  all good",
            "2026-03-14 12:00:01 ERROR db down",
            "2026-03-14 12:00:02 FATAL out of memory",
            "2026-03-14 12:00:03 CRITICAL disk full",
            "2026-03-14 12:00:04 PANIC kernel",
            "FAILED tests/test_x.py::test_a - assert 1 == 2",
            "FAIL github.com/app/pkg 0.12s",
            "build FAILURE in module core",
            "Traceback (most recent call last):",
            '  File "x.py", line 3, in run',
            "ValueError: bad value 7",
            "requests.exceptions.ConnectionError: refused",
            "panic: runtime error: index out of range",
        ]
    )
    exemplars = list(error_fingerprints(text).values())
    for line in text.split("\n"):
        wanted = not line.startswith("2026-03-14 12:00:00") and not line.startswith("  File")
        assert (line in exemplars) == wanted, line


def test_level_tokens_are_case_sensitive():
    assert error_fingerprints("INFO the error rate is low, failed over fine") == {}
    assert error_fingerprints("an Error occurred") == {}
    assert error_fingerprints("ERROR occurred")


@pytest.mark.parametrize(
    "line",
    [
        "Summary: 0 errors, 12 warnings",
        "0 errors found",
        "errors: 0",
        "ERRORS: 0",
        "failed=0 passed=412",
        "no errors detected",
        "Found 0 FAILED jobs",
        "failures: 0",
    ],
)
def test_zero_error_summaries_are_not_errors(line):
    assert error_fingerprints(line) == {}


@pytest.mark.parametrize(
    "line",
    [
        "ERROR: no error handler registered for event foo",
        "2025-01-01 ERROR upstream returned 500 with no error body",
        "FATAL: zero failures tolerated but the job failed",
        "ERROR: 0.5 exceeds threshold",
    ],
)
def test_real_error_lines_that_mention_no_errors_are_still_errors(line):
    """Only a literal zero count ("0 errors", "errors: 0") negates a line; the
    words "no error ..." inside a real ERROR line's text do not."""
    assert error_fingerprints(line)


@pytest.mark.parametrize(
    "plain, counted",
    [
        ("ValueError: bad value 7", "[×500] ValueError: bad value 9"),
        (
            "requests.exceptions.ConnectionError: refused",
            "  [×3] requests.exceptions.ConnectionError: refused",
        ),
    ],
)
def test_exception_heads_keep_their_key_under_a_collapse_prefix(plain, counted):
    """The exception head is anchored at the line start; a "[×N] " fold prefix
    must not hide it (stability under the prefix, for every kind of line)."""
    assert error_fingerprints(plain)
    assert list(error_fingerprints(plain)) == list(error_fingerprints(counted))


def test_fingerprint_masks_digits_hex_and_uuids():
    a = "2026-03-14 12:00:01.123 ERROR [worker-3] timeout after 123ms req=3fa9c2d7e1b4"
    b = "2027-01-02 08:09:10.999 ERROR [worker-12] timeout after 9ms req=0a1b2c3d4e5f"
    u1 = "ERROR job 550e8400-e29b-41d4-a716-446655440000 failed"
    u2 = "ERROR job 123e4567-e89b-12d3-a456-426614174000 failed"
    assert list(error_fingerprints(a)) == list(error_fingerprints(b))
    assert list(error_fingerprints(u1)) == list(error_fingerprints(u2))
    (fp,) = error_fingerprints(a)
    assert "<hex>" in fp and "worker-#" in fp and "#ms" in fp
    (fp,) = error_fingerprints(u1)
    assert "<uuid>" in fp
    assert error_fingerprints("ERROR disk full on sda")  # different text: different key
    assert list(error_fingerprints("ERROR disk full on sda")) != list(
        error_fingerprints("ERROR disk full on sdb")
    )


def test_fingerprint_strips_collapse_prefix_and_is_capped():
    plain = "ERROR upstream timeout after 5ms"
    counted = "[×500] ERROR upstream timeout after 9ms"
    assert list(error_fingerprints(plain)) == list(error_fingerprints(counted))
    (fp,) = error_fingerprints("ERROR " + "word " * 100)
    assert len(fp) <= 160


def test_exemplar_is_the_first_occurrence_in_original_order():
    text = "\n".join(
        [
            "ERROR disk 11 full on sdb",
            "INFO noise",
            "ERROR net 12 unreachable from host-1",
            "ERROR disk 13 full on sdb",
            "ERROR net 14 unreachable from host-9",
        ]
    )
    result = error_fingerprints(text)
    assert list(result.values()) == [
        "ERROR disk 11 full on sdb",
        "ERROR net 12 unreachable from host-1",
    ]


def test_fingerprints_empty_and_non_string_input():
    assert error_fingerprints("") == {}
    assert error_fingerprints("INFO fine\nINFO still fine") == {}


def test_fingerprints_survive_compression_of_a_log():
    log = _log()
    before = error_fingerprints(log)
    assert len(before) >= 3
    result = compress_context(log, "why are requests failing?", ccr=False, citations=False)
    assert not result.fail_open
    assert before.keys() <= error_fingerprints(result.compressed_text).keys()


def test_fingerprints_survive_collapse_markers():
    log = _log()
    result = compress_context(
        log, "what happened with req=zz99?", ccr=False, citations=False
    )
    out = result.compressed_text
    assert error_fingerprints(log).keys() <= error_fingerprints(out).keys()


# ------------------------------------------------------------------ brief_context


def test_brief_returns_text_unchanged_when_it_fits():
    assert brief_context("short", budget_chars=1200) == "short"
    text = "a\n" * 600
    assert brief_context(text, budget_chars=len(text)) == text
    assert brief_context("", budget_chars=10) == ""


@pytest.mark.parametrize("budget", [300, 600, 1200, 3000])
def test_brief_never_exceeds_the_budget(budget):
    log = _log()
    out = brief_context(log, budget_chars=budget)
    assert len(out) <= budget
    assert out  # not empty


def test_brief_keeps_head_tail_errors_in_original_order():
    log = _log()
    lines = log.split("\n")
    out = brief_context(log, budget_chars=1500)
    out_lines = out.split("\n")
    assert out_lines[0] == lines[0]
    assert out_lines[-1] == lines[-1]
    exemplars = list(error_fingerprints(log).values())
    for ex in exemplars:
        assert ex in out_lines
    kept = [ln for ln in out_lines if not ln.startswith("[…")]
    positions = [lines.index(ln) for ln in kept]
    assert positions == sorted(positions)
    # every non-marker line is an original line, uncut
    assert all(ln in set(lines) for ln in kept)


def test_brief_error_exemplars_come_before_warnings_and_query_hits():
    log = _log()
    exemplars = list(error_fingerprints(log).values())
    # budget with room for the errors but not for much else
    need = sum(len(e) + 1 for e in exemplars) + 700
    out = brief_context(log, budget_chars=need)
    assert all(e in out for e in exemplars)


def test_brief_adds_warning_exemplars_when_they_fit_and_skips_them_otherwise():
    log = _log()
    big = brief_context(log, budget_chars=4000)
    assert re.search(r"\bWARN(?:ING)?\b", big)
    tiny_errors_only = brief_context(log, budget_chars=700)
    assert len(tiny_errors_only) <= 700


def test_brief_query_terms_pull_in_matching_lines():
    log = _log()
    lines = log.split("\n")
    target = next(
        ln for ln in lines[1000:] if "cache hit" in ln and "key=session:" in ln
    )
    session = target.split("key=session:")[1].split()[0]
    plain = brief_context(log, budget_chars=1500)
    asked = brief_context(log, budget_chars=1500, query=f"what did session:{session} do?")
    assert target not in plain.split("\n")
    assert target in asked.split("\n")
    assert len(asked) <= 1500
    # errors still come first: every exemplar survives the query line
    assert set(error_fingerprints(log).values()) <= set(asked.split("\n"))


def test_brief_filler_query_adds_nothing():
    log = _log()
    assert brief_context(log, budget_chars=1200, query="continue") == brief_context(
        log, budget_chars=1200
    )


def test_brief_marks_gaps_with_the_default_marker():
    out = brief_context(_log(), budget_chars=1200)
    markers = re.findall(r"^\[… (\d+) chars omitted …\]$", out, re.M)
    assert markers
    total_omitted = sum(int(m) for m in markers)
    assert total_omitted + len(out) > 0.9 * len(_log()) - len(markers) * 60


def test_brief_uses_the_callers_gap_marker():
    log = _log()
    calls = []

    def marker(omitted, total):
        calls.append((omitted, total))
        return f"<<{omitted}/{total}>>"

    out = brief_context(log, budget_chars=1200, gap_marker=marker)
    assert calls and all(total == len(log) for _, total in calls)
    assert "[…" not in out
    assert len(out) <= 1200
    n_markers = len(re.findall(r"^<<\d+/\d+>>$", out, re.M))
    # one call per emitted marker, plus the single probe that sizes the widest
    # marker for the budget (it asks about a span as long as the whole input)
    assert len(calls) == n_markers + 1
    assert calls[0] == (len(log), len(log))


def test_brief_is_deterministic():
    log = _log()
    assert brief_context(log, budget_chars=900) == brief_context(log, budget_chars=900)


def test_brief_truncates_one_overlong_line_with_a_marker():
    text = "x" * 5000
    out = brief_context(text, budget_chars=200)
    assert len(out) <= 200
    assert out.startswith("xxxx")
    assert "chars omitted" in out
    # the omitted count is honest
    m = re.search(r"\[… (\d+) chars omitted …\]", out)
    assert int(m.group(1)) + out.index("[…") == 5000


def test_brief_with_a_budget_too_small_for_any_line_is_a_plain_prefix():
    assert brief_context("a\nb\nc", budget_chars=1) == "a"
    assert brief_context("x" * 50, budget_chars=10) == "x" * 10
    assert brief_context("\n" * 100 + "ERROR boom" + "\n" * 100, budget_chars=20) == "ERROR boom"


def test_brief_never_cuts_a_line_that_fits():
    lines = [f"line {i}: " + "w" * 60 for i in range(100)]
    lines[50] = "ERROR " + "e" * 150
    out = brief_context("\n".join(lines), budget_chars=500)
    assert ("ERROR " + "e" * 150) in out.split("\n")
    for ln in out.split("\n"):
        assert ln.startswith("[…") or ln in set(lines)


def test_brief_blank_gaps_are_not_marked():
    text = "head\n\n\n\nERROR boom\n\n\n" + "filler line\n" * 80 + "tail"
    out = brief_context(text, budget_chars=60)
    assert "head" in out and "ERROR boom" in out
    assert out.split("\n")[1] == "ERROR boom"  # no marker for the blank run between them


# ------------------------------------------------------- extract_evidence_lines


def test_evidence_is_original_lines_in_original_order_capped():
    log = _log()
    lines = log.split("\n")
    found = extract_evidence_lines(log, "", limit=8)
    assert 0 < len(found) <= 8
    assert all(ln in set(lines) for ln in found)
    positions = [lines.index(ln) for ln in found]
    assert positions == sorted(positions)


def test_evidence_ranks_errors_first_one_per_fingerprint():
    log = _log()
    exemplars = list(error_fingerprints(log).values())
    found = extract_evidence_lines(log, "", limit=len(exemplars))
    assert set(found) == set(exemplars)
    assert len(extract_evidence_lines(log, "", limit=1)) == 1
    assert extract_evidence_lines(log, "", limit=1)[0] == exemplars[0]


def test_evidence_then_query_hits_then_identifier_dense_lines():
    text = "\n".join(
        [
            "plain narrative sentence one",
            "ERROR the build failed",
            "we discussed the frobnicator today",
            "another plain sentence",
            "see src/app/core/engine.py version 2.14.1 sha 3fa9c2d7e1b4a",
            "the frobnicator is configured with mode=fast level=3",
            "yet another plain sentence",
        ]
    )
    found = extract_evidence_lines(text, "frobnicator", limit=10)
    assert "ERROR the build failed" in found
    assert "we discussed the frobnicator today" in found
    assert "the frobnicator is configured with mode=fast level=3" in found
    assert "see src/app/core/engine.py version 2.14.1 sha 3fa9c2d7e1b4a" in found
    assert "plain narrative sentence one" not in found
    # with room for only two, errors and query hits outrank identifier density
    two = extract_evidence_lines(text, "frobnicator", limit=2)
    assert "ERROR the build failed" in two
    assert "see src/app/core/engine.py version 2.14.1 sha 3fa9c2d7e1b4a" not in two


def test_evidence_dedupes_repeats_and_ignores_blanks():
    text = "\n".join(["", "ERROR disk 1 full", "ERROR disk 2 full", "", "ERROR disk 3 full"])
    assert extract_evidence_lines(text, "", limit=10) == ["ERROR disk 1 full"]


@pytest.mark.parametrize("limit", [0, -3])
def test_evidence_limit_zero_or_negative_is_empty(limit):
    assert extract_evidence_lines("ERROR x", "", limit=limit) == []
    assert extract_evidence_lines("", "q", limit=5) == []


# ----------------------------------------------------------------- contains_secret


def test_contains_secret_is_the_public_alias():
    assert contains_secret("key = AKIAIOSFODNN7EXAMPLE")
    assert contains_secret("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
    assert contains_secret("token: ghp_0123456789abcdefghijKL")
    assert contains_secret('api_key = "abcdefghijklmnopqrstuv"')
    assert not contains_secret("an ordinary paragraph about logs")
    assert not contains_secret("")
    assert not contains_secret(None)  # type: ignore[arg-type]
    for sample in ("AKIAIOSFODNN7EXAMPLE", "plain text", ""):
        assert contains_secret(sample) == cc._contains_secret(sample)


# ------------------------------------------------------------------ content_hint


@pytest.mark.parametrize("hint", [None, "code", "numbered_code", "log", "json", "text", "diff", "grep", "test"])
def test_every_documented_hint_is_accepted_and_recorded(hint):
    result = compress_context(
        "plain words\n\nmore words " * 30, "words", ccr=False, citations=False,
        content_hint=hint,
    )
    assert result.receipt["content_hint"] == hint


@pytest.mark.parametrize("hint", ["Code", "yaml", "csv", "", "numbered", 5, ["code"]])
def test_unknown_hint_raises(hint):
    with pytest.raises(ValueError):
        compress_context("x\n\ny", "q", content_hint=hint)  # type: ignore[arg-type]


def test_hint_is_recorded_on_fail_open_receipts_too():
    result = compress_context("short", "continue", content_hint="log")
    assert result.fail_open
    assert result.receipt is None or result.receipt.get("content_hint") == "log"
    # a hard fail-open (industrial limit) still records it
    from tameru.industrial import IndustrialLimits

    hard = compress_context(
        "x" * 100, "needle-1", content_hint="grep", limits=IndustrialLimits(max_input_chars=10)
    )
    assert hard.fail_open and hard.receipt["content_hint"] == "grep"


def _numbered_code(fmt: str) -> str:
    out = []
    for i in range(60):
        out += [
            f"def func_{i}(a, b, c=None):",
            f'    """Compute thing {i}."""',
            f"    total = a + b * {i}, c",
            "    if c is None:",
            f"        return total[0], {i}",
            f"    return total, c, {i}",
            "",
        ]
    if fmt == "pipe":
        return "\n".join(f"{i + 1}|{ln}" for i, ln in enumerate(out))
    if fmt == "tab":
        return "\n".join(f"{i + 1:6d}\t{ln}" for i, ln in enumerate(out))
    return "\n".join(out)


@pytest.mark.parametrize("fmt,hint", [("pipe", "numbered_code"), ("tab", "numbered_code"), ("plain", "code")])
def test_code_hints_keep_function_bodies_and_the_gutter(fmt, hint):
    text = _numbered_code(fmt)
    result = compress_context(
        text, "what does func_26 do?", ccr=False, citations=False, content_hint=hint
    )
    assert not result.fail_open
    out = result.compressed_text
    assert "def func_26(a, b, c=None):" in out
    assert "total = a + b * 26, c" in out
    assert "return total, c, 26" in out
    assert result.content_type == "code"
    if fmt != "plain":  # the gutter stays in the output
        assert re.search(r"^\s*\d+(\||\t)def func_26", out, re.M) or re.search(
            r"^\s*\d+(\||\t)\s*def func_26", out, re.M
        )


@pytest.mark.parametrize("fmt", ["pipe", "tab"])
def test_without_the_hint_numbered_code_is_shredded(fmt):
    """The 1.3.0 failure the hint exists for: code read through a gutter is
    detected as a table and the function body is lost."""
    text = _numbered_code(fmt)
    result = compress_context(text, "what does func_26 do?", ccr=False, citations=False)
    assert "total = a + b * 26, c" not in result.compressed_text


def _code_with_a_later_override_comment() -> str:
    out = []
    for i in range(30):
        out += [f"def helper_{i}(value):", f"    return value + {i}", ""]
    out += ["def compute_total(order, discount):", "    subtotal = sum(order.items)",
            "    return subtotal - discount", ""]
    out += ["def apply_discount(order, discount):",
            "    # discount override: compute_total is deprecated, order discount applied here",
            "    return compute_total(order, discount)", ""]
    for i in range(30, 60):
        out += [f"def helper_{i}(value):", f"    return value + {i}", ""]
    return "\n".join(out)


@pytest.mark.parametrize("numbered", [False, True])
def test_code_hint_is_not_subject_to_prose_supersession(numbered):
    """Temporal supersession reads prose markers ("override", "deprecated") and
    drops an earlier block that shares vocabulary with the later one. In code
    that evicted the very function the query named. With a code hint the
    function body survives."""
    code = _code_with_a_later_override_comment()
    hint = "code"
    if numbered:
        code = "\n".join(f"{i + 1}|{ln}" for i, ln in enumerate(code.split("\n")))
        hint = "numbered_code"
    result = compress_context(
        code, "what does compute_total return?", ccr=False, citations=False,
        content_hint=hint,
    )
    assert not result.fail_open
    assert "def compute_total(order, discount):" in result.compressed_text
    assert "return subtotal - discount" in result.compressed_text


def test_code_hint_skips_the_csv_path_for_code_with_commas():
    code = "\n".join(
        [f"x_{i} = foo(a, b, c)  # step {i}" for i in range(40)]
        + ["def special_handler(a, b, c):", "    return a, b, c", ""]
        + [f"y_{i} = bar(1, 2, 3)  # filler {i}" for i in range(40)]
    )
    hinted = compress_context(
        code, "what does special_handler return?", ccr=False, citations=False,
        content_hint="code",
    )
    assert "return a, b, c" in hinted.compressed_text


def test_code_hint_with_generic_query_is_not_a_csv_fail_open():
    code = "\n".join(f"v_{i} = foo(a, b, c, {i})" for i in range(60))
    result = compress_context(code, "", ccr=False, citations=False, content_hint="code")
    assert result.fail_open  # empty query: fail open, but not through the CSV rule
    assert "csv" not in " ".join(result.reasons).lower()


def test_log_hint_forces_log_routing():
    text = "\n".join(f"stage {i} finished ok in {i * 3}ms on shard-{i % 4}" for i in range(80))
    assert compress_context(text, "shard-2", ccr=False, citations=False).content_type != "log"
    forced = compress_context(
        text, "shard-2", ccr=False, citations=False, content_hint="log"
    )
    assert forced.content_type == "log"


def test_log_hint_never_reads_a_java_style_log_as_a_csv():
    """logback timestamps ("12:00:00,123") give every line one comma, so the
    detector calls the log a two-column CSV and the CSV adapter keeps a header
    plus the rows that match. The log hint skips the adapters."""
    log = "\n".join(
        f"2026-03-14 12:00:{i % 60:02d},{i % 1000:03d} "
        + ("ERROR" if i % 40 == 7 else "INFO ")
        + f" req-{i:04d} handled"
        for i in range(300)
    )
    from tameru.format_adapters import detect_format

    assert detect_format(log) == "csv"
    plain = compress_context(log, "what happened to req-0120?", ccr=False, citations=False)
    assert plain.receipt["industrial"]["applied"]  # the adapter treated it as a table
    hinted = compress_context(
        log, "what happened to req-0120?", ccr=False, citations=False, content_hint="log"
    )
    assert hinted.content_type == "log"
    assert not hinted.receipt["industrial"]["applied"]
    assert "req-0120" in hinted.compressed_text
    assert error_fingerprints(log).keys() <= error_fingerprints(hinted.compressed_text).keys()


def test_json_hint_forces_json_routing_and_text_hint_forces_text():
    log = "\n".join(
        f"2026-03-14 12:00:{i:02d} INFO  w1 request {i} served in {i}ms" for i in range(60)
    )
    assert cc.route_content_type(log.split("\n")) == "log"
    assert compress_context(log, "request 7", ccr=False, citations=False,
                            content_hint="text").content_type == "text"
    assert compress_context(log, "request 7", ccr=False, citations=False,
                            content_hint="json").content_type == "json"


@pytest.mark.parametrize("hint", ["diff", "grep", "test"])
def test_recorded_only_hints_behave_like_none(hint):
    text = "\n\n".join(f"Entry {i}: marker-{i} plus standard operational content." for i in range(30))
    plain = compress_context(text, "marker-7", ccr=False, citations=False)
    hinted = compress_context(text, "marker-7", ccr=False, citations=False, content_hint=hint)
    assert hinted.compressed_text == plain.compressed_text
    assert hinted.receipt["content_hint"] == hint


# -------------------------------------------------------------- estimate_tokens


def test_estimate_tokens_fast_path_matches_the_definition():
    samples = [
        "plain ascii words 123",
        "ascii with … ellipsis and × times § section – dash",
        "日本語のテキスト mixed with ascii",
        "[… 12 chars omitted …]",
        "",
    ]
    for text in samples:
        if not text:
            assert estimate_tokens(text) == 0
            continue
        accounting = all(ord(c) < 128 or c in cc._FAST_ACCOUNTING_PUNCT for c in text)
        expected = (
            len(cc._TOKEN_RE.findall(text)) if (text.isascii() or accounting)
            else len(cc.token_units(text))
        )
        assert estimate_tokens(text) == max(1, expected)
