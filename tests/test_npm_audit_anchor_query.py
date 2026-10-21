from tameru.agent_formats import preprocess_test_output


def _npm_audit_text():
    low = "".join(
        f"pkg{i}  <1.{i}.0\n"
        f"Severity: low\n"
        f"Prototype pollution in pkg{i} - https://github.com/advisories/GHSA-test-{i:04d}\n"
        f"fix available via `npm audit fix`\n"
        f"node_modules/pkg{i}\n"
        f"\n"
        for i in range(10)
    )
    return (
        "# npm audit report\n\n"
        + low
        + "lodash-x  <4.17.21\n"
        + "Severity: critical\n"
        + "Command injection in lodash-x - https://github.com/advisories/GHSA-test-9999\n"
        + "fix available via `npm audit fix --force`\n"
        + "node_modules/lodash-x\n"
        + "\n"
        + "11 vulnerabilities (10 low, 1 critical)\n"
    )


def test_anchor_query_does_not_rekeep_low_severity_lines():
    text = _npm_audit_text()
    out = preprocess_test_output(text, "Severity: critical")
    assert out.count("Severity: low") == 0
    assert "Severity: critical" in out


def test_package_query_still_rekeeps_package_lines():
    text = _npm_audit_text()
    out = preprocess_test_output(text, "is pkg4 affected?")
    assert "pkg4  <1.4.0" in out
