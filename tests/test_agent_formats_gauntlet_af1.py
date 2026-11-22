import pytest

from tameru import agent_formats as af


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
