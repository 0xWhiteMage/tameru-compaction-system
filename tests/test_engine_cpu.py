"""v1.4.2: engine CPU. The same output is analysed once, not once per call.

A host that compacts one tool result asks the engine about the same text many
times: the adaptive extract, fixed-budget retries, briefs at growing sizes,
error-template checks. Profiled on a 50 KB log, a 650 KB log, numbered source,
grep output and a JSON dump, most of that time was the same pure scans over
the same text (``preprocess_logs``, ``score_blocks``, the secrets regex, the
critical-line and error-template scans) plus per-line regexes that cannot
match. These tests pin the work counts and prove, against reference copies of
the previous implementations, that the faster scanners return the same values.
Output equality over a large corpus is checked outside the suite (see the
CHANGELOG); nothing here asserts milliseconds.
"""
from __future__ import annotations

import random
import re

import pytest

from tameru import compress_context as cc
from tameru import folding
from tameru import format_adapters as fa
from tameru.compress_context import compress_context

KW = dict(ccr=False, citations=False)


def app_log(n: int = 700, seed: int = 4) -> str:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        ts = f"2026-03-14 12:{i // 60 % 60:02d}:{i % 60:02d}.{i % 1000:03d}"
        h = "%08x" % rng.getrandbits(32)
        if i % 97 == 40:
            out.append(f"{ts} ERROR web-1 upstream timeout after {rng.randint(1, 999)}ms req={h}")
        elif i % 211 == 7:
            out.append(f"{ts} WARN  db-1 slow query {rng.randint(500, 3000)}ms table=orders req={h}")
        else:
            out.append(f"{ts} INFO  web-{i % 3} GET /api/v1/users/{h}/profile 200 {rng.randint(1, 999)}ms")
    return "\n".join(out)


LOG = app_log()
QUERY = "why did the upstream timeout errors happen on web-1?"


@pytest.fixture(autouse=True)
def cold():
    cc._clear_memos()
    yield
    cc._clear_memos()


class Counter:
    """Wrap ``module.name`` so its calls are counted (the real function still runs)."""

    def __init__(self, monkeypatch, module, name):
        self.calls = 0
        real = getattr(module, name)

        def counted(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, counted)


class SearchCounter:
    """Count ``.search`` calls of a module-level compiled pattern."""

    def __init__(self, monkeypatch, module, name):
        self.calls = 0
        real = getattr(module, name)
        outer = self

        class Wrapped:
            def search(self, *args, **kwargs):
                outer.calls += 1
                return real.search(*args, **kwargs)

            def __getattr__(self, attr):
                return getattr(real, attr)

        monkeypatch.setattr(module, name, Wrapped())


# --- work counts -----------------------------------------------------------


def test_preprocess_logs_fingerprints_each_line_once(monkeypatch):
    counter = Counter(monkeypatch, cc, "_log_fingerprint")
    rng = random.Random(9)
    words = ["alpha", "bravo", "cargo", "delta", "echo", "fable", "gamma", "harbor", "ivory", "jungle"]
    # every line has its own template, so none collapses and all are kept
    lines = [
        f"{rng.choice(words)}-{i // 10} {rng.choice(words)}{i % 10} {rng.choice(words)} stage "
        f"{rng.choice(words)}{rng.choice(words)} completed"
        for i in range(300)
    ] + ["2026-03-14 ERROR web-1 upstream timeout after 12ms", "ERROR web-2 upstream timeout after 99ms"]
    cc.preprocess_logs(lines, QUERY)
    # collapse + count attach + error restore used to fingerprint the kept
    # lines a second (and every error line a third) time
    assert counter.calls <= len(set(lines)) + 4


def test_retries_reuse_the_analysis_of_the_same_text(monkeypatch):
    logs = Counter(monkeypatch, cc, "preprocess_logs")
    scored = Counter(monkeypatch, cc, "score_blocks")
    segmented = Counter(monkeypatch, cc, "segment_blocks")
    secrets = SearchCounter(monkeypatch, cc, "_SECRETS_RE")
    # a credential keyword, so the screen has to run its regex (the literal
    # prefilter rules out a text without any)
    text = LOG + "\n2026-03-14 12:59:59 INFO web-1 refreshed auth_token ok"
    base = compress_context(text, QUERY, **KW)
    first = (logs.calls, scored.calls, segmented.calls, secrets.calls)
    assert first == (1, 1, 1, 1)
    for ratio in (0.4, 0.3, 0.25):
        compress_context(text, QUERY, mode="fixed", budget_ratio=ratio, **KW)
    # four calls, one analysis
    assert (logs.calls, scored.calls, segmented.calls, secrets.calls) == first
    assert not base.fail_open


def test_error_templates_of_one_text_are_scanned_once(monkeypatch):
    counter = Counter(monkeypatch, cc, "_is_error_line")
    cc.error_fingerprints(LOG)
    once = counter.calls
    assert once >= len(LOG.split("\n"))
    for _ in range(4):
        cc.error_fingerprints(LOG)
    assert counter.calls == once


def test_brief_at_growing_budgets_scans_the_text_once(monkeypatch):
    counter = Counter(monkeypatch, cc, "_is_error_line")
    cc.brief_context(LOG, budget_chars=1200, query=QUERY)
    once = counter.calls
    for budget in (1800, 2700):
        cc.brief_context(LOG, budget_chars=budget, query=QUERY)
    assert counter.calls == once


def test_log_line_with_no_error_literal_skips_the_error_regexes(monkeypatch):
    # An error line always holds ERROR/FATAL/CRITICAL/PANIC/FAIL/Error:/Exception:/
    # Traceback/panic:; the other ~99% of log lines are ruled out by one scan.
    count = SearchCounter(monkeypatch, cc, "_ERR_LEVEL_RE")
    for i in range(500):
        assert not cc._is_error_line(f"2026-03-14 INFO GET /api/v1/users/{i} 200 {i}ms")
    assert count.calls == 0
    assert cc._is_error_line("2026-03-14 ERROR boom")
    assert count.calls == 1


# --- results of the memoized analyses are private copies ----------------------


def test_memoized_results_cannot_be_altered_by_callers():
    fps = cc.error_fingerprints(LOG)
    expected = dict(fps)
    fps.clear()
    assert cc.error_fingerprints(LOG) == expected

    lines, kind = cc.preprocess(LOG, QUERY)
    keep = list(lines)
    lines.clear()
    again, kind2 = cc.preprocess(LOG, QUERY)
    assert again == keep and kind2 == kind

    crit = cc._extract_critical_lines(LOG)
    keep = list(crit)
    crit.append("junk")
    assert cc._extract_critical_lines(LOG) == keep

    for fn, arg in (
        (cc.distinctive_query_terms, "check web-1 and payments-api"),
        (cc._extract_entities, "see /srv/app/main.py and `Foo`"),
        (cc._extract_terms, "upstream timeout errors"),
        (cc.search_units, "upstream timeout"),
    ):
        first = fn(arg)
        snapshot = list(first)
        first.append("junk")
        assert fn(arg) == snapshot


def test_blocks_of_a_repeated_call_are_not_polluted_by_pins():
    cold_result = compress_context(LOG, QUERY, **KW)
    cc._clear_memos()
    compress_context(LOG, QUERY, pin_patterns=[r"web-2"], **KW)  # marks blocks pinned / boosts scores
    warm_result = compress_context(LOG, QUERY, **KW)
    assert warm_result.compressed_text == cold_result.compressed_text
    assert warm_result.receipt == cold_result.receipt


def test_degraded_view_does_not_leak_into_the_next_call():
    big = "\n".join(f"line {i} " + "x" * 90 for i in range(400)) + "\nERROR needle-7 fails\n"
    kw = dict(ccr=False, citations=False)
    reference = compress_context(big, "needle-7", **kw).compressed_text
    compress_context(big, "needle-7", degraded_view=True, **kw)
    assert compress_context(big, "needle-7", **kw).compressed_text == reference


# --- the faster scanners return what the previous implementations returned ----


def old_detect_json_payloads(text):
    payloads = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "{[":
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                c = text[j]
                if escape:
                    escape = False
                elif c == "\\" and in_string:
                    escape = True
                elif c == '"':
                    in_string = not in_string
                elif not in_string:
                    if c in "{[":
                        depth += 1
                    elif c in "}]":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            if j < n and depth == 0:
                candidate = text[i:j + 1]
                if len(candidate) > 200:
                    payloads.append((i, j + 1, candidate))
                i = j + 1
            else:
                break
        else:
            i += 1
    return payloads


def old_split_delimited_records(text):
    records = []
    start = 0
    index = 0
    in_quotes = False
    while index < len(text):
        char = text[index]
        if char == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
            index += 1
            continue
        if not in_quotes and char in {"\n", "\r"}:
            records.append(text[start:index])
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
            start = index + 1
        index += 1
    if in_quotes:
        return None
    if start < len(text):
        records.append(text[start:])
    elif text.endswith(("\n", "\r")):
        records.append("")
    while records and not records[-1]:
        records.pop()
    return records


def old_mask_template(s):
    s = folding._M_DQ.sub(folding._volatile('"<str>"'), s)
    s = folding._M_SQ.sub(folding._volatile('"<str>"'), s)
    s = folding._M_TS.sub("<ts>", s)
    s = folding._M_UUID.sub("<uuid>", s)
    s = folding._M_IP4.sub("<ip>", s)
    s = folding._M_IP6.sub("<ip>", s)
    s = folding._M_PATH.sub(folding._volatile("<path>"), s)
    s = folding._M_DUR.sub("<dur>", s)
    s = folding._M_HEX.sub("<hex>", s)
    s = folding._M_DIGITS.sub("#", s)
    return " ".join(s.split())


def old_is_error_line(line):
    s = cc._without_zero_counts(line[: cc._RX_LINE_CAP])
    head = s
    prefix = cc._COUNT_PREFIX_RE.match(s)
    if prefix:
        head = s[prefix.end():]
    return bool(
        cc._ERR_LEVEL_RE.search(s)
        or cc._ERR_EXC_RE.match(head)
        or cc._ERR_TRACEBACK in s
        or cc._ERR_PANIC_RE.search(s)
    )


def old_extract_critical_lines(text):
    critical = []
    for line in text.split("\n"):
        t = line.strip()
        if not t:
            continue
        scan = t[: cc._RX_LINE_CAP]
        if cc._CRITICAL_ERROR_RE.search(scan):
            critical.append(t)
            continue
        start = cc._lead_ts_end(scan)
        if (len(t) > 15 and cc._CRITICAL_KV_RE.search(scan, start)) or cc._CRITICAL_NUM_RE.search(
            scan, start
        ):
            critical.append(t)
    return critical


def old_is_progress_bar(line):
    t = line.strip()
    if not t:
        return False
    if re.search(r"(\[[=#>\-. ]*\]\s*)?\d{1,3}\s*(%|/\s*\d+)", t):
        return True
    return bool(re.match(r"^Compiling [\w-]+ ", t))


FRAGMENTS = [
    "ERROR", "error", "Error:", "FATAL", "fail", "FAILED", "panic:", "Exception:", "KeyError:",
    "Traceback (most recent call last)", "0 errors", "errors: 0", "failed=0", "[×3] ", "INFO", "WARN",
    "2026-03-14", "12:03:45.123", "10.0.0.1:8080", "fe80::1:2:3", "/srv/data/a1.db", "/var/log/x/y/z",
    '"quoted 12"', "'single 3'", "deadbeef", "123e4567-e89b-12d3-a456-426614174000", "12ms", "3.5s",
    "45%", "[=====>   ] 50%", "3/10", "Compiling foo v1.2.3", "Downloading x", "key=value", "host: db-1",
    "timeout", "denied", "v1.2.3", "{", "}", "[", "]", '"', "\\", ",", "x", " ", "\t", "²", "é", "日本",
]


def random_line(rng):
    return rng.choice(["", " ", "_", "  "]).join(rng.choice(FRAGMENTS) for _ in range(rng.randint(0, 9)))


def test_scanners_match_the_previous_implementations():
    rng = random.Random(20260114)
    for _ in range(4000):
        line = random_line(rng)
        assert cc._is_error_line(line) == old_is_error_line(line), line
        assert cc._is_progress_bar(line) == old_is_progress_bar(line), line
        for s in (line, line.lower()):
            assert folding.mask_template(s) == old_mask_template(s), s
        text = "\n".join(random_line(rng) for _ in range(rng.randint(1, 5)))
        assert cc._extract_critical_lines(text) == old_extract_critical_lines(text), text
        assert cc._detect_json_payloads(text) == old_detect_json_payloads(text), text
        assert fa._split_delimited_records(text) == old_split_delimited_records(text), text


def test_json_payload_scan_matches_on_large_documents():
    blobs = [
        '{"a": [1, 2, {"b": "x\\"y]"}], "pad": "' + "p" * 220 + '"}',
        "[" + ",".join('{"id": %d, "name": "n%d"}' % (i, i) for i in range(40)) + "]",
        'text {"unterminated": "' + "q" * 300,
        "{" * 5 + "]" * 5 + "x" * 300,
    ]
    for blob in blobs:
        for text in (blob, "prefix " + blob + " middle " + blob + " tail"):
            assert cc._detect_json_payloads(text) == old_detect_json_payloads(text)


def test_secret_screen_is_unchanged_by_the_literal_prefilter():
    rng = random.Random(7)
    secrets = [
        "-----BEGIN RSA PRIVATE KEY-----", "AKIAABCDEFGHIJKLMNOP", "ghp_" + "a" * 24, "github_pat_" + "b" * 24,
        "xoxb-1234567890-abc", "sk-" + "c" * 24, "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        "AIza" + "d" * 35, "sk_live_" + "e" * 16, "Authorization: Bearer " + "f" * 24,
        'password = "' + "g" * 20 + '"', "DB_PASSWORD=correct_horse_battery_staple", "api_key: " + "h" * 20,
        "API-KEY=" + "i" * 20, "ſecret = '" + "j" * 20 + "'", "Key: " + "k" * 20,
    ]
    benign = ["hello world", "password", "secret santa", "token", "bearer", "sk", "the key", "x = 1", "日本語"]
    for _ in range(3000):
        parts = [rng.choice(secrets + benign) for _ in range(rng.randint(0, 4))]
        text = rng.choice(["\n", " ", "; ", ""]).join(parts)
        assert cc._contains_secret(text) == (cc._SECRETS_RE.search(text) is not None), text
    assert cc._contains_secret("x" * 5000 + "\nAKIAABCDEFGHIJKLMNOP\n")
    assert not cc._contains_secret(LOG)


# --- memory bound ------------------------------------------------------------


def test_texts_above_the_memo_cap_are_not_remembered(monkeypatch):
    # A long-lived server must not pin six copies of an 8 MB output in a dozen
    # caches: texts above ``_MEMO_MAX_CHARS`` are analysed on every call.
    text = LOG
    monkeypatch.setattr(cc, "_MEMO_MAX_CHARS", len(text) - 1)
    counter = Counter(monkeypatch, cc, "_is_error_line")
    cc.error_fingerprints(text)
    once = counter.calls
    cc.error_fingerprints(text)
    assert counter.calls == 2 * once
    assert cc._error_fingerprints_cached.cache_info().currsize == 0
    monkeypatch.setattr(cc, "_MEMO_MAX_CHARS", len(text))
    cc.error_fingerprints(text)
    assert cc._error_fingerprints_cached.cache_info().currsize == 1


def test_threads_sharing_the_memos_get_the_same_answers():
    import threading

    texts = [app_log(300, seed=s) for s in range(6)]
    expected = [compress_context(t, QUERY, **KW).compressed_text for t in texts]
    cc._clear_memos()
    failures: list[str] = []

    def work(offset: int) -> None:
        for round_ in range(6):
            for k in range(len(texts)):
                i = (k + offset + round_) % len(texts)
                got = compress_context(texts[i], QUERY, **KW).compressed_text
                if got != expected[i]:
                    failures.append(f"thread {offset} text {i}")

    pool = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for th in pool:
        th.start()
    for th in pool:
        th.join()
    assert not failures
