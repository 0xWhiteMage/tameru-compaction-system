from tameru.agent_formats import adapt_unified_diff
from tameru.compress_context import compress_context


def _build_diff():
    return "".join(f"diff --git a/svc/mod{i}.py b/svc/mod{i}.py\n--- a/svc/mod{i}.py\n+++ a/svc/mod{i}.py\n@@ -{i+3},3 +{i+3},3 @@\n import os\n-VERSION = '1.{i}'\n+VERSION = '1.{i+1}'\n" for i in range(20)) + "diff --git a/svc/http.py b/svc/http.py\n--- a/svc/http.py\n+++ a/svc/http.py\n@@ -10,3 +10,3 @@\n class Client:\n-    timeout = 5\n+    timeout = 30\n"


def _build_two_file_diff():
    parts = []
    for name in ("a.py", "b.py"):
        parts.append(f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ a/{name}\n")
        for n in range(1, 4):
            parts.append(f"@@ -{2 * n},1 +{2 * n},1 @@\n-old{n}\n+new{n}\n")
    return "".join(parts)


def test_weak_query_keeps_http_and_marks_missing_files():
    d = _build_diff()
    res = adapt_unified_diff(d, "where was the timeout changed", gap_marker=None)
    assert res.kept_records == 1
    assert "+    timeout = 30" in res.text
    assert "diff --git a/svc/http.py b/svc/http.py" in res.text
    for i in range(20):
        assert f"diff --git a/svc/mod{i}.py b/svc/mod{i}.py" in res.text
    assert "VERSION = '1.5'" not in res.text
    assert "--- a/svc/mod5.py" not in res.text
    assert "20 files without a match" in res.text
    assert len(res.text) < len(d)


def test_compress_context_diff_receipt():
    d = _build_diff()
    result = compress_context(d, "where was the timeout changed", ccr=False, citations=False)
    assert "svc/http.py" in result.compressed_text
    assert "timeout = 30" in result.compressed_text
    assert len(result.compressed_text) < len(d)
    assert result.receipt["adapter"]["name"] == "diff"


def test_two_file_weak_query_keeps_four_records():
    d = _build_two_file_diff()
    res = adapt_unified_diff(d, "where was frobnicate changed", gap_marker=None)
    assert res.kept_records == 4
    assert "+new1" in res.text
    assert "+new3" in res.text
    assert "+new2" not in res.text
    assert "without a match" not in res.text
