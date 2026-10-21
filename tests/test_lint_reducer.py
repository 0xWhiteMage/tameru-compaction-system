from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def test_ruff_lint_reducer():
    text = (
        "\n".join(
            f"src/pkg/mod{i}.py:{i + 10}:1: E501 Line too long ({i + 100} > 88)"
            for i in range(35)
        )
        + '\nsrc/pkg/auth.py:12:5: S105 Possible hardcoded password assigned to: "secret"\nFound 36 errors.\n'
    )
    assert detect_test_runner(text) == "lint"
    out = preprocess_test_output(text)
    assert "auth.py:12:5: S105" in out
    assert "Found 36 errors." in out
    assert "mod0.py" in out
    assert "mod20.py" not in out


def test_mypy_lint_reducer():
    text = "\n".join(
        [
            f"src/app/models{i}.py:{i + 3}: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]"
            for i in range(30)
        ]
        + [
            'src/app/billing.py:88: error: Argument 1 to "charge" has incompatible type "str"; expected "Decimal"  [arg-type]',
            "Found 1 error in 1 file (checked 64 source files)",
        ]
    )
    r = compress_context(text, "", ccr=False, citations=False)
    assert "billing.py:88" in r.compressed_text
    assert "arg-type" in r.compressed_text
    assert "models20.py" not in r.compressed_text


def test_few_lint_lines_not_detected():
    text = "\n".join(
        f"src/pkg/mod{i}.py:{i + 10}:1: E501 Line too long ({i + 100} > 88)"
        for i in range(4)
    )
    assert detect_test_runner(text) != "lint"


def test_gcc_like_lint_keeps_distinct_messages():
    lines = [f"src/a{i}.c:{i}:5: error: unknown type name 'T{i}'" for i in range(10)]
    lines += [
        "src/z.c:1:1: error: expected ';' before '}' token",
        "src/z.c:2:1: error: implicit declaration of function 'foo'",
        "src/z.c:3:1: warning: unused variable 'x'",
    ]
    text = "\n".join(lines)
    out = preprocess_test_output(text)
    assert "src/a0.c" in out
    assert "src/a9.c" not in out
    assert "expected ';' before '}' token" in out
    assert "implicit declaration of function 'foo'" in out
    assert "unused variable 'x'" in out
