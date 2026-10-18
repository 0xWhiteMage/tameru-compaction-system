from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def _go(n):
    logs = "\n".join(f"22/10/18 07:00:{i % 60:02d} poller: fetched page {i} ok" for i in range(n))
    return logs + "\npanic: close of nil channel\n\ngoroutine 9 [running]:\nmain.(*Bus).Stop(...)\n\t/srv/bus.go:31\nmain.main()\n\t/srv/main.go:22 +0x3d"


def test_go_panic_frames_survive_anchoring():
    for n in (30, 120):
        out = compress_context(_go(n), "", ccr=False, citations=False, anchor_errors=True).compressed_text
        assert "close of nil channel" in out and "bus.go:31" in out and "main.go:22" in out and "goroutine 9" in out


def test_go_long_stack_keeps_last_frame():
    frames = "".join(f"pkg.f{i}(0x{i})\n\t/src/f{i}.go:{i + 10} +0x1\n" for i in range(12))
    text = "\n".join(f"[w] job {i} ok" for i in range(80)) + "\npanic: boom\n\ngoroutine 3 [running]:\n" + frames + "created by pkg.Start in goroutine 1\n\t/src/start.go:5 +0x33"
    out = compress_context(text, "", ccr=False, citations=False, anchor_errors=True).compressed_text
    assert "panic: boom" in out and "f0.go:10" in out and "start.go:5" in out


def test_maven_surefire_reduced():
    text = "\n".join(f"[INFO] Running com.a.T{i}\n[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.1 s -- in com.a.T{i}" for i in range(30))
    text += (
        "\n[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.1 s <<< FAILURE! -- in com.a.PriceTest\n"
        "[ERROR] com.a.PriceTest.rounds -- Time elapsed: 0.01 s <<< FAILURE!\norg.opentest4j.AssertionFailedError: expected: <10> but was: <9>\n"
        "\tat com.a.PriceTest.rounds(PriceTest.java:33)\n[INFO]\n[ERROR] Tests run: 152, Failures: 1, Errors: 0, Skipped: 0\n[INFO] BUILD FAILURE"
    )
    assert detect_test_runner(text) == "maven"
    out = preprocess_test_output(text)
    assert out
    for want in (
        "PriceTest.rounds",
        "expected: <10> but was: <9>",
        "PriceTest.java:33",
        "Tests run: 152, Failures: 1",
        "BUILD FAILURE",
    ):
        assert want in out
    assert "com.a.T7" not in out


def test_stack_trace_is_not_yaml():
    from tameru.format_adapters import detect_format

    logs = "\n".join(
        f"22/10/18 07:00:{i % 60:02d} poller: fetched page {i} ok"
        for i in range(30)
    )
    text = (
        logs
        + "\npanic: close of nil channel\n\ngoroutine 9 [running]:\n"
        "main.(*Bus).Stop(...)\n\t/srv/bus.go:31\n"
        "main.main()\n\t/srv/main.go:22 +0x3d"
    )
    assert detect_format(text) != "yaml"
    assert (
        detect_format("server:\n  port: 8080\n  host: example\nlogging:\n  level: info\n")
        == "yaml"
    )


def test_maven_old_surefire_without_in_suffix():
    text = "\n".join(f"[INFO] Running com.a.M{i}Test\n[INFO] Tests run: {i + 3}, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.{i} s" for i in range(40))
    text += ("\n[ERROR] Tests run: 12, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.8 s <<< FAILURE! - in com.a.TaxTest\n"
             "[ERROR] com.a.TaxTest.vat  Time elapsed: 0.02 s  <<< FAILURE!\norg.opentest4j.AssertionFailedError: expected: <1> but was: <2>\n"
             "\tat com.a.TaxTest.vat(TaxTest.java:33)\n[ERROR] Tests run: 612, Failures: 1, Errors: 0, Skipped: 3\n[INFO] BUILD FAILURE")
    out = preprocess_test_output(text)
    assert out and len(out) < len(text) // 3
    for want in ("TaxTest.vat", "TaxTest.java:33", "Tests run: 612, Failures: 1", "BUILD FAILURE", "Tests run: 12, Failures: 1"):
        assert want in out


def test_node_describe_repeated_warnings_collapse():
    head = (
        "Name:               ip-10-0-7-21\nRoles:              worker\n"
        + "".join(
            f"                    label{i}=value{i}\n" for i in range(30)
        )
    )
    head += (
        "Conditions:\n"
        "  Type             Status  Reason                       Message\n"
        "  MemoryPressure   True    KubeletHasInsufficientMemory "
        "kubelet has insufficient memory available\n"
    )
    ev = (
        "Events:\n"
        "  Type     Reason                Age   From     Message\n"
        "  Warning  OOMKilling  9m  kernel-monitor  "
        "Memory cgroup out of memory\n"
    )
    ev += "".join(
        f"  Warning  EvictionThresholdMet  {i}m    kubelet  "
        f"Attempting to reclaim memory from pod batch-{100 + i}\n"
        for i in range(40)
    )
    ev += (
        "  Normal   NodeReady             2d    kubelet  "
        "Node status is now: NodeReady"
    )
    text = head + ev
    out = preprocess_test_output(text)
    assert out
    for want in (
        "MemoryPressure   True",
        "OOMKilling",
        "batch-100",
        "batch-139",
        "NodeReady",
    ):
        assert want in out
    assert "batch-120" not in out
    res = compress_context(text, "", ccr=False, citations=False)
    assert len(res.compressed_text) < 0.5 * len(text)


def test_runner_prefilter_keeps_detection():
    import random
    rng = random.Random(0)
    prose = "\n\n".join(f"Paragraph {i} discusses module {i % 13} with words {rng.random()}." for i in range(200))
    assert detect_test_runner(prose) is None
    assert detect_test_runner("running 2 tests\ntest a ... ok\ntest b ... ok\n\ntest result: ok. 2 passed; 0 failed") == "cargo"
    assert detect_test_runner("=== RUN   TestA\n--- PASS: TestA (0.00s)\nok  \tex.com/a\t0.01s") == "go"
    assert detect_test_runner("tests/t.py ..... [100%]\n5 passed in 0.10s") == "pytest"
