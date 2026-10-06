"""E5: pytest / jest / go test / cargo test output keeps failures + summary."""
import re

from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context, preprocess_test_runner


def _pytest(n_pass: int = 300, verbose: bool = False) -> str:
    head = [
        "============================= test session starts ==============================",
        "platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0",
        "rootdir: /work/proj",
        f"collected {n_pass + 2} items",
        "",
    ]
    if verbose:
        body = [f"tests/test_mod.py::test_case_{i} PASSED{' ' * 20}[{i % 100:3d}%]" for i in range(n_pass)]
        body.insert(40, "tests/test_mod.py::test_broken FAILED                          [ 13%]")
    else:
        body = [f"tests/test_mod_{k}.py " + "." * 50 for k in range(n_pass // 50)]
        body.append("tests/test_mod_x.py .F.F" + "." * 20 + "  [100%]")
    tail = [
        "",
        "=================================== FAILURES ===================================",
        "________________________________ test_broken ________________________________",
        "",
        ">   def test_broken(): assert compute(41) == 42",
        "E   assert 41 == 42",
        "E    +  where 41 = compute(41)",
        "",
        "tests/test_mod_x.py:9: AssertionError",
        "________________________________ test_other _________________________________",
        "",
        "E   KeyError: 'session_token_77'",
        "",
        "tests/test_mod_x.py:21: KeyError",
        "=============================== warnings summary ===============================",
        "tests/test_mod_0.py::test_deprecated",
        "  /work/proj/tests/test_mod_0.py:3: DeprecationWarning: old api",
        "",
        "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html",
        "=========================== short test summary info ============================",
        "FAILED tests/test_mod_x.py::test_broken - assert 41 == 42",
        "FAILED tests/test_mod_x.py::test_other - KeyError: 'session_token_77'",
        f"=================== 2 failed, {n_pass} passed, 1 warning in 3.21s ====================",
    ]
    return "\n".join(head + body + tail)


JEST = "\n".join(
    [f"PASS src/suite_{i}.test.js\n  ✓ case a of suite {i} (2 ms)\n  ✓ case b of suite {i} (1 ms)" for i in range(60)]
    + [
        "FAIL src/billing.test.js",
        "  ● invoices › rounds half up",
        "",
        "    expect(received).toBe(expected) // Object.is equality",
        "",
        "    Expected: 10.13",
        "    Received: 10.12",
        "",
        "      14 |   expect(round(10.125)).toBe(10.13);",
        "",
        "      at Object.<anonymous> (src/billing.test.js:14:29)",
        "",
        "  ● Console",
        "",
        "    console.log",
        "      noisy debug output",
        "",
        "PASS src/last.test.js",
        "",
        "Test Suites: 1 failed, 61 passed, 62 total",
        "Tests:       1 failed, 120 passed, 121 total",
        "Snapshots:   0 total",
        "Time:        4.2 s",
        "Ran all test suites.",
    ]
)

GO = "\n".join(
    ["=== RUN   TestAlpha", "    a_test.go:3: fine", "--- PASS: TestAlpha (0.00s)"]
    + [
        line
        for i in range(120)
        for line in (
            f"=== RUN   TestCase{i}",
            f"    case_test.go:{i}: log line {i}",
            f"--- PASS: TestCase{i} (0.00s)",
        )
    ]
    + [
        "=== RUN   TestBad",
        "    a_test.go:4: want 1 got 2",
        "--- FAIL: TestBad (0.00s)",
        "=== RUN   TestSub",
        "=== RUN   TestSub/a",
        "--- PASS: TestSub (0.00s)",
        "    --- PASS: TestSub/a (0.00s)",
        "FAIL",
        "FAIL\texample.com/ex\t0.012s",
        "ok  \texample.com/other\t0.004s",
        "FAIL",
    ]
)

CARGO = "\n".join(
    [
        "   Compiling ex v0.1.0 (/work/ex)",
        "    Finished `test` profile [unoptimized + debuginfo] target(s) in 5.92s",
        "     Running unittests src/lib.rs (target/debug/deps/ex-1d5eddbe27cf7782)",
        "",
        "running 152 tests",
    ]
    + [f"test tests::ok_{i} ... ok" for i in range(150)]
    + [
        "test tests::bad_one ... FAILED",
        "test tests::skipped ... ignored",
        "",
        "failures:",
        "",
        "---- tests::bad_one stdout ----",
        "",
        "thread 'tests::bad_one' panicked at src/lib.rs:5:28:",
        "assertion `left == right` failed: numbers differ",
        "  left: 1",
        " right: 2",
        "",
        "",
        "failures:",
        "    tests::bad_one",
        "",
        "test result: FAILED. 150 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.01s",
    ]
)


def test_runner_detection():
    assert detect_test_runner(_pytest()) == "pytest"
    assert detect_test_runner(JEST) == "jest"
    assert detect_test_runner(GO) == "go"
    assert detect_test_runner(CARGO) == "cargo"
    assert detect_test_runner("just some\nplain log lines\n") is None
    assert detect_test_runner("Test Files  1 passed (1)\nTests  5 passed (5)") is None


def test_pytest_keeps_failures_short_summary_and_final_line():
    for verbose in (False, True):
        text = _pytest(verbose=verbose)
        out = preprocess_test_output(text, "")
        assert out is not None and len(out) < len(text) / 2
        assert "= FAILURES =" in out
        assert "E   assert 41 == 42" in out
        assert "KeyError: 'session_token_77'" in out
        assert "short test summary info" in out
        assert "FAILED tests/test_mod_x.py::test_other - KeyError: 'session_token_77'" in out
        assert out.rstrip().endswith("2 failed, 300 passed, 1 warning in 3.21s ====================")
        assert "DeprecationWarning" not in out and "platform linux" not in out
        assert re.search(r"\[… \d+ passing tests? omitted …\]", out)


def test_pytest_passing_count_in_marker_matches():
    out = preprocess_test_output(_pytest(n_pass=300, verbose=True), "")
    counts = [int(n) for n in re.findall(r"\[… (\d+) passing tests? omitted …\]", out)]
    assert sum(counts) == 300  # the failing verbose line is kept, not counted


def test_pytest_all_passing_reduces_to_the_summary():
    text = "\n".join(
        ["=" * 30 + " test session starts " + "=" * 30, "collected 200 items", ""]
        + ["tests/test_a.py " + "." * 50] * 4
        + ["", "=" * 20 + " 200 passed in 1.10s " + "=" * 20]
    )
    out = preprocess_test_output(text, "")
    assert out.rstrip().endswith("200 passed in 1.10s " + "=" * 20)
    assert "[… 200 passing tests omitted …]" in out


def test_quiet_pytest_summary_line_is_kept():
    text = "\n".join(["." * 60] * 3 + ["tests/t.py ....."] * 5 + ["2 passed in 0.10s"])
    # not a recognised runner shape without headers: left alone
    assert preprocess_test_output(text, "") is None


def test_jest_keeps_failure_blocks_and_summary():
    out = preprocess_test_output(JEST, "")
    assert out is not None and len(out) < len(JEST) / 2
    assert "● invoices › rounds half up" in out
    assert "Expected: 10.13" in out and "Received: 10.12" in out
    assert "FAIL src/billing.test.js" in out
    assert "Test Suites: 1 failed, 61 passed, 62 total" in out
    assert "Tests:       1 failed, 120 passed, 121 total" in out
    assert "PASS src/suite_3.test.js" not in out
    assert "noisy debug output" not in out
    assert re.search(r"\[… 120 passing tests omitted …\]", out)


def test_go_keeps_fail_blocks_and_package_lines():
    out = preprocess_test_output(GO, "")
    assert out is not None and len(out) < len(GO) / 3
    assert "--- FAIL: TestBad (0.00s)" in out
    assert "    a_test.go:4: want 1 got 2" in out
    assert "FAIL\texample.com/ex\t0.012s" in out
    assert "ok  \texample.com/other\t0.004s" in out
    assert "=== RUN" not in out and "--- PASS" not in out and "log line 7" not in out
    counts = [int(n) for n in re.findall(r"\[… (\d+) passing tests? omitted …\]", out)]
    assert sum(counts) == 1 + 120 + 1 + 1  # TestAlpha, 120 cases, TestSub and TestSub/a


def test_cargo_keeps_failure_blocks_failures_list_and_result():
    out = preprocess_test_output(CARGO, "")
    assert out is not None and len(out) < len(CARGO) / 2
    assert "---- tests::bad_one stdout ----" in out
    assert "assertion `left == right` failed: numbers differ" in out
    assert "failures:\n    tests::bad_one" in out
    assert "test tests::bad_one ... FAILED" in out
    assert "test result: FAILED. 150 passed; 1 failed" in out
    assert "tests::ok_17 ... ok" not in out
    assert "[… 150 passing tests omitted …]" in out


def test_query_naming_a_passing_test_keeps_its_line():
    out = preprocess_test_output(CARGO, "did ok_77 pass?")
    assert "test tests::ok_77 ... ok" in out
    assert "tests::ok_78 ... ok" not in out


def test_gap_marker_replaces_the_count_marker():
    out = preprocess_test_output(CARGO, "", gap_marker=lambda o, t: f"<<gap {o}>>")
    assert "<<gap" in out and "passing tests" not in out


def test_vitest_legacy_path_still_works():
    text = "\n".join(
        ["✓ src/a.test.ts (3 tests) 4ms"] * 20 + ["Tests  60 passed (60)", "Test Files  20 passed (20)"]
    )
    out = preprocess_test_runner(text, "")
    assert "Tests  60 passed (60)" in out and "✓ src/a.test.ts" not in out


def test_through_compress_context_with_hint_and_detection():
    for text in (_pytest(), JEST, GO, CARGO):
        for hint in (None, "test"):
            result = compress_context(
                text, "why did the test fail?", ccr=False, citations=False, content_hint=hint
            )
            assert len(result.compressed_text) < len(text) * 0.6
            assert result.receipt["content_hint"] == hint
    result = compress_context(
        CARGO, "why did bad_one fail?", ccr=False, citations=False, content_hint="test"
    )
    assert "numbers differ" in result.compressed_text
    assert "test result: FAILED" in result.compressed_text


def test_reduced_jest_run_keeps_failing_test_names_through_scoring():
    """Block scoring must not drop the failing test's file/name lines that the
    reduction kept ("which tests failed?" used to lose 9 of 12 names)."""
    from tameru.compress_context import compress_context

    text = "".join(f"PASS src/c{i}.test.js (1.{i % 9} s)\n" for i in range(120))
    for i in range(12):
        text += (
            f"FAIL src/f{i}.test.js\n  ● Suite {i} › does thing {i}\n\n"
            f"    expect(received).toBe(expected)\n\n    Expected: {i}\n"
            f"    Received: {i + 1}\n\n      at Object.<anonymous> (src/f{i}.test.js:11:20)\n\n"
        )
    text += "Test Suites: 12 failed, 120 passed, 132 total\nTests:       12 failed, 480 passed, 492 total\n"
    for query in ("which tests failed?", "continue"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert len(out) < len(text)
        for i in range(12):
            assert f"does thing {i}" in out and f"f{i}.test.js" in out
