from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_go_package_fold():
    text = (
        "\n".join(
            f"# example.com/svc/pkg{i}\nok      example.com/svc/pkg{i}     0.0{i}s"
            for i in range(18)
        )
        + "\n?       example.com/svc/cmd     [no test files]\n"
        "--- FAIL: TestLedgerBalance (0.01s)\n"
        "    ledger_test.go:88: balance = 120, want 100\n"
        "FAIL\n"
        "FAIL    example.com/svc/ledger  0.212s\n"
    )

    assert detect_test_runner(text) == "go"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "ledger_test.go:88: balance = 120, want 100" in out
    assert "FAIL    example.com/svc/ledger  0.212s" in out
    assert "--- FAIL: TestLedgerBalance" in out
    assert "pkg5" not in out
    assert "[no test files]" not in out
    assert "18 passing suites omitted" in out
    assert len(out) < len(text) * 0.4


def test_go_package_header_build_error_kept():
    text2 = (
        "# example.com/svc/api\n"
        "api/handler.go:12:2: undefined: Foo\n"
        "FAIL    example.com/svc/api [build failed]\n"
        + "\n".join(f"ok      example.com/svc/p{i}     0.01s" for i in range(5))
        + "\n"
    )

    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "# example.com/svc/api" in out2
    assert "undefined: Foo" in out2
