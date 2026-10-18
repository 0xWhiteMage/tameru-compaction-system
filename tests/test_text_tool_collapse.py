"""Repeated-template collapse for text-routed tool output (helm/ansible/pip)."""

import tameru.compress_context as cc


def _run(text: str, query: str):
    return cc.compress_context(
        text, query, ccr=False, citations=False, anchor_errors=True
    )


def test_helm_repeated_debug_collapses():
    lines = ['Release "shop" does not exist. Installing it now.']
    lines += [
        f"client.go:{100 + i * 7}: [debug] creating {i} resource(s)"
        for i in range(30)
    ]
    lines.append("Error: INSTALLATION FAILED: timed out waiting for the condition")
    text = "\n".join(lines)
    r = _run(text, "")
    assert "Error: INSTALLATION FAILED" in r.compressed_text
    assert not r.fail_open
    assert len(r.compressed_text) < 0.25 * len(text)


def test_helm_unique_line_survives():
    lines = ['Release "shop" does not exist. Installing it now.']
    lines += [
        f"client.go:{100 + i * 7}: [debug] creating {i} resource(s)"
        for i in range(15)
    ]
    lines.append("client.go:999: [debug] skipping hook pre-install (disabled)")
    lines += [
        f"client.go:{100 + i * 7}: [debug] creating {i} resource(s)"
        for i in range(15, 30)
    ]
    lines.append("Error: INSTALLATION FAILED: timed out waiting for the condition")
    text = "\n".join(lines)
    r = _run(text, "")
    assert "skipping hook pre-install (disabled)" in r.compressed_text
    assert not r.fail_open


def test_ansible_repeated_tasks_collapse():
    lines = []
    for i in range(20):
        lines.append(f"TASK [role{i} : configure] ****")
        lines.append(f"ok: [web{i}]")
    lines.append("TASK [db : migrate] ****")
    lines.append(
        'fatal: [db1]: FAILED! => {"changed": false, '
        '"msg": "migration 0042 failed: relation users exists"}'
    )
    lines.append("")
    lines.append("PLAY RECAP ****")
    lines.append("db1 : ok=12 changed=1 unreachable=0 failed=1")
    text = "\n".join(lines)
    r = _run(text, "")
    assert "migration 0042 failed" in r.compressed_text
    assert "failed=1" in r.compressed_text
    assert not r.fail_open
    assert len(r.compressed_text) < 0.45 * len(text)


def test_pip_repeated_satisfied_keeps_error():
    lines = [
        f"Requirement already satisfied: pkg{i} in "
        f"./venv/lib/python3.12/site-packages ({i + 1}.0)"
        for i in range(30)
    ]
    lines.append(
        "ERROR: Could not find a version that satisfies the "
        "requirement torch==2.9.9 (from versions: none)"
    )
    lines.append("ERROR: No matching distribution found for torch==2.9.9")
    text = "\n".join(lines)
    for query in ("what failed to install", ""):
        r = _run(text, query)
        assert "torch==2.9.9" in r.compressed_text
        assert not r.fail_open


def test_looks_like_repetitive_guards():
    # 30 blank-separated paragraphs -> too many blank lines.
    paras = [
        f"Paragraph {i} has some prose that goes on for a while."
        for i in range(30)
    ]
    prose = "\n\n".join(paras).split("\n")
    assert cc._looks_like_repetitive_tool_output(prose) is False

    # markdown doc with a heading.
    md = ["# Title", ""] + [f"- item {i}" for i in range(30)]
    assert cc._looks_like_repetitive_tool_output(md) is False

    # 15 repeated lines -> too few non-blank lines.
    few = [f"line {i % 3}" for i in range(15)]
    assert cc._looks_like_repetitive_tool_output(few) is False

    # 25 all-distinct lines (distinct words, so digit-masking cannot merge
    # them into one template) -> no template reaches the 5x threshold.
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
        "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
        "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
        "victor", "whiskey", "xray", "yankee",
    ]
    distinct = [f"unique line {w} with different words" for w in words]
    assert cc._looks_like_repetitive_tool_output(distinct) is False


def test_unified_diff_hunks_not_collapsed():
    lines = ["diff --git a/src/m0.py b/src/m0.py"]
    for i in range(30):
        lines.append("@@ -10,6 +10,6 @@")
        lines.append(f"-old line {i}")
        lines.append(f"+new line {i}")
    assert cc._looks_like_repetitive_tool_output(lines) is False


def test_grep_rows_not_collapsed():
    lines = [f"src/m{i}.py:1:    value = compute(x)" for i in range(30)]
    assert cc._looks_like_repetitive_tool_output(lines) is False


def test_distinctive_query_helm_unchanged():
    lines = ['Release "shop" does not exist. Installing it now.']
    lines += [
        f"client.go:{100 + i * 7}: [debug] creating {i} resource(s)"
        for i in range(30)
    ]
    lines.append("Error: INSTALLATION FAILED: timed out waiting for the condition")
    text = "\n".join(lines)
    r = _run(text, "INC-2026-1147 rollback")
    assert "Error: INSTALLATION FAILED" in r.compressed_text
