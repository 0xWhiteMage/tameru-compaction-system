from tameru.agent_formats import detect_test_runner, preprocess_test_output


def _make_text() -> str:
    head = "top - 10:01:02 up 12 days,  3:04,  2 users,  load average: 7.91, 6.02, 4.11\nTasks: 312 total,   2 running, 310 sleeping,   0 stopped,   0 zombie\n%Cpu(s): 93.1 us,  4.2 sy,  0.0 ni,  2.1 id\nMiB Mem :  15890.2 total,    312.4 free,  14980.1 used\n\n    PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND\n"
    busy = "   8812 app       20   0 9123456 7.1g  12345 R 389.0  45.7  88:12.33 java\n"
    idle = "".join(f"   {500 + i} root      20   0       0      0      0 S   0.0   0.0   0:00.{i:02d} kworker/{i}:1\n" for i in range(40))
    zombie = "   9001 app       20   0       0      0      0 Z   0.0   0.0   0:00.00 defunct-x\n"
    return head + busy + idle + zombie


def test_top_reducer():
    text = _make_text()
    assert detect_test_runner(text) == "top"
    out = preprocess_test_output(text, "")
    assert "load average: 7.91" in out
    assert "8812 app" in out
    assert "389.0" in out
    assert "defunct-x" in out
    assert "kworker/7:1" not in out
    assert "process rows omitted" in out
    assert len(out) < 0.4 * len(text)


def test_top_reducer_repeated_iteration():
    text = _make_text()
    out2 = preprocess_test_output(text + "\n" + text, "")
    assert out2.count("load average: 7.91") == 2


def test_top_not_detected_without_summary():
    idle = "".join(f"   {500 + i} root      20   0       0      0      0 S   0.0   0.0   0:00.{i:02d} kworker/{i}:1\n" for i in range(40))
    assert detect_test_runner(idle) is None
