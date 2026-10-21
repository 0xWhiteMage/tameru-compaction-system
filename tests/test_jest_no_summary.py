from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_jest_without_final_summary_is_detected_and_reduced():
    text = (
        "\n".join(f" PASS  src/components/Btn{i}.test.tsx" for i in range(20))
        + "\n FAIL  src/components/Header.test.tsx\n"
        "  ● Header › renders title\n"
        "\n"
        "    expect(received).toMatchSnapshot()\n"
        "\n"
        "    Snapshot name: `Header renders title 1`\n"
        "\n"
        "    - Snapshot  - 1\n"
        "    + Received  + 1\n"
        "\n"
        "    -   Welcome back\n"
        "    +   Welcome back!\n"
        "\n"
        "Snapshot Summary\n"
        " › 1 snapshot failed from 1 test suite.\n"
    )

    assert detect_test_runner(text) == "jest"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "Header renders title 1" in out
    assert "+   Welcome back!" in out
    assert "-   Welcome back" in out
    assert "FAIL  src/components/Header.test.tsx" in out
    assert "1 snapshot failed" in out
    assert "Btn7" not in out
    assert "passing suites omitted" in out
    assert len(out) < len(text) * 0.6


def test_plain_go_output_is_still_go():
    text = (
        "ok  \texample.com/a\t0.01s\n"
        "FAIL\texample.com/b\t0.02s\n"
        "--- FAIL: TestX (0.00s)\n"
    )

    assert detect_test_runner(text) == "go"


def test_only_passing_badges_without_failure_block_are_not_jest():
    text = "\n".join(f"PASS src/a{i}.test.js" for i in range(5))

    assert detect_test_runner(text) is None
