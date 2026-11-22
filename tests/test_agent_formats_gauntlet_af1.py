import tracemalloc

import pytest

from tameru import agent_formats as af


@pytest.mark.parametrize("detector", [af.looks_like_diagnostics, af.looks_like_stack_trace])
def test_diagnostic_sample_memory_bound(detector):
    text = "plain line\n" * 200000
    tracemalloc.start()
    try:
        assert not detector(text)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1000000
    assert not detector("")


def test_npm_tree_linear_ancestry(monkeypatch):
    original = af._NPM_TREE_LINE_RE
    calls = 0

    class CountingPattern:
        def match(self, line):
            nonlocal calls
            calls += 1
            return original.match(line)

    monkeypatch.setattr(af, "_NPM_TREE_LINE_RE", CountingPattern())
    lines = ["root@1", "├── parent@1"] + ["│ ├── bad@1 invalid"] * 200
    assert af._classify_npm_tree(lines)[0] == [True] * len(lines)
    assert calls <= 3 * len(lines)


def test_stem_cache_bound():
    matcher = af._StemMatcher(("needle",))
    for i in range(5000):
        token = "word" + "".join(chr(97 + (i // (26 ** j)) % 26) for j in range(3))
        matcher.hit(token)
    assert len(matcher._memo) <= 4096
    assert matcher.hit("needle")
    assert not af._StemMatcher(()).hit("needle")


def test_slowlog_oversized_metadata():
    lines = ["# Query_time: 1 Lock_time: 0 Rows_sent: 1 Rows_examined: 1",
             "SELECT 1;", "# Query_time: 2 Lock_time: 0 Rows_sent: 1 Rows_examined: " + "9" * 5000]
    assert af._classify_slowlog(lines)[0] == [True] * len(lines)


def test_curl_response_local_cap():
    lines = ["< HTTP/1.1 200 OK"] + [f"< x-{i}: a" for i in range(4)]
    lines += ["< HTTP/1.1 201 OK"] + [f"< x-{i}: b" for i in range(4)]
    assert af._classify_curl_verbose(lines)[0] == [True] * len(lines)


def test_slowlog_malformed_decimal():
    text = "\n".join("# Query_time: 1..2 Lock_time: 0 Rows_sent: 1 Rows_examined: 2" for _ in range(5))
    assert not af._detect_slowlog(text)
    assert af._classify_slowlog(text.splitlines())[0] == [True] * 5


def test_curl_unknown_response_data():
    lines = ["< unexpected response payload"] + [f"< x-{i}: value" for i in range(8)]
    keep = af._classify_curl_verbose(lines)[0]
    assert keep[0] and not keep[1]


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_ps_invalid_utilization(value):
    lines = [f"user {i} {cpu} 1 100 10 ? S 12:00 0:00 app" for i, cpu in enumerate(["2", value, "3"])]
    assert af._classify_ps_aux(lines)[0] == [True] * 3


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_top_invalid_utilization(value):
    lines = [f"{i} user 20 0 100 10 10 S {cpu} 1 0:00 app" for i, cpu in enumerate(["2", value, "3"])]
    assert af._classify_top(["PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND"] + lines)[0] == [True] * 4


def test_rollout_resource_anchors():
    lines = [f'Waiting for deployment "{name}" rollout to finish: {i} of 9' for name in ("a", "b") for i in range(8)]
    keep = af._classify_rollout_wait(lines)[0]
    assert [i for i, flag in enumerate(keep) if flag] == [0, 6, 7, 8, 14, 15]
    assert af._classify_rollout_wait([])[0] == []


def test_ansible_large_recap_counts():
    lines = ["PLAY RECAP ***", "a : ok=1 changed=0 unreachable=0 failed=0",
             "b : ok=1 changed=0 unreachable=" + "9" * 5000 + " failed=0"]
    assert af._classify_ansible(lines)[0] == [True, True, True]


def test_ansible_repeated_plays():
    lines = ["PLAY RECAP ***", "a : ok=1 changed=0 unreachable=0 failed=0",
             "PLAY [next] ***", "TASK [x] ***", "ok: [a]", "ok: [b]"]
    assert af._classify_ansible(lines)[0][-2:] == [True, False]


def test_ansible_host_details():
    lines = ["TASK [x] ***", "ok: [a]", 'ok: [b] => {"msg": "disk failing"}', "ok: [c]"]
    assert af._classify_ansible(lines)[0] == [True, True, True, False]


def test_audit_header_without_blank():
    lines = ["# npm audit report", "pkg", "Severity: low", "details"]
    keep = af._classify_npm_audit(lines)[0]
    assert keep[0] and not keep[1]


def test_audit_mixed_severity():
    lines = ["pkg", "Severity: low", "Severity: critical", "exploit"]
    assert af._classify_npm_audit(lines)[0] == [True] * len(lines)
    assert af._classify_npm_audit([])[0] == []


@pytest.mark.parametrize("body", ["@@ -1,3 +1,3 @@\n a", "@@ -1,0 +1,1 @@\n a", "@@ -1 +1 @@\n?bad", "@@ -1," + "9" * 5000 + " +1 @@\n a"])
def test_diff_malformed_hunks(body):
    text = "--- a/x.py\n+++ b/x.py\n" + body
    result = af.adapt_unified_diff(text, "needle")
    assert result is not None and result.text == text


def test_grep_oversized_line_number():
    assert af._grep_parse_line('file.py:' + '9' * 5000 + ':body') is None
    assert af._grep_parse_line('file.py:12:body') == ('m', 'file.py', 12, 'body')
    assert af._grep_parse_line('') is None


def test_grep_saturated_file_orientation():
    text = "\n".join(f"{path}.py:{i + 1}:needle()" for path in ("a", "b") for i in range(10))
    result = af.adapt_grep_lines(text, "needle", per_file_cap=2)
    assert result is not None and result.kept_records == 2


@pytest.mark.parametrize("cap", [0, -1, 1.5, True, None])
def test_grep_invalid_cap(cap):
    text = "x.py:1:hello\nx.py:2:world"
    result = af.adapt_grep_lines(text, "needle", per_file_cap=cap)
    assert result is not None and result.text == text


def test_grep_uncertain_lines():
    text = "x.py:1:needle\nx.py:2:other\nx.py:3:third\nUNKNOWN TRAILER"
    result = af.adapt_grep_lines(text, "needle")
    assert result is not None and result.text == text


@pytest.mark.parametrize("line,kind", [(r"C:\src\x.py:12:body", "m"), (r"C:\src\x.py-12-body", "c")])
def test_grep_windows_paths(line, kind):
    assert af._grep_parse_line(line) == (kind, r"C:\src\x.py", 12, "body")
