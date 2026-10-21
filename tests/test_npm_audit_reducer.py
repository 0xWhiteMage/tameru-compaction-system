from tameru.agent_formats import detect_test_runner, preprocess_test_output


def _low_advisories() -> str:
    return "".join(
        f"pkg{i}  <1.{i}.0\n"
        "Severity: low\n"
        f"Prototype pollution in pkg{i} - https://github.com/advisories/GHSA-test-{i:04d}\n"
        "fix available via `npm audit fix`\n"
        f"node_modules/pkg{i}\n"
        "\n"
        for i in range(10)
    )


def test_npm_audit_reducer_keeps_critical_and_summary():
    low = _low_advisories()
    text = (
        "# npm audit report\n\n"
        + low
        + "lodash-x  <4.17.21\n"
        "Severity: critical\n"
        "Command injection in lodash-x - https://github.com/advisories/GHSA-test-9999\n"
        "fix available via `npm audit fix --force`\n"
        "node_modules/lodash-x\n"
        "\n"
        "11 vulnerabilities (10 low, 1 critical)\n"
    )

    assert detect_test_runner(text) == "npm_audit"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "Severity: critical" in out
    assert "lodash-x" in out
    assert "11 vulnerabilities (10 low, 1 critical)" in out
    assert "pkg4" not in out
    assert "low-severity advisory lines omitted" in out
    assert "# npm audit report" in out
    assert len(out) < len(text) * 0.4


def test_npm_audit_reducer_keeps_moderate():
    low = _low_advisories()
    text2 = (
        "# npm audit report\n\n"
        + low[: low.index("pkg3")]
        + "minimist-x  <1.2.6\n"
        "Severity: moderate\n"
        "Prototype pollution - https://github.com/advisories/GHSA-test-5555\n"
        "node_modules/minimist-x\n"
        "\n"
        "4 vulnerabilities (3 low, 1 moderate)\n"
    )

    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "Severity: moderate" in out2
    assert "minimist-x" in out2


def test_npm_audit_not_detected_without_report_header():
    assert detect_test_runner("Severity: low\nSeverity: low\nSeverity: low\n") is None
