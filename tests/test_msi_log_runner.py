from tameru.agent_formats import detect_test_runner, _classify_msi_log
from tameru.compress_context import compress_context

MSI_TEXT = (
    "=== Verbose logging started: 10/21/2026  09:40:02  Build type: SHIP UNICODE 5.00.10011.00 ===\n"
    + "".join(
        f"MSI (s) (A4:B8) [09:40:{i:02d}:123]: Doing action: Action{i}\n"
        f"Action start 9:40:{i:02d}: Action{i}.\n"
        f"Action ended 9:40:{i:02d}: Action{i}. Return value 1.\n"
        for i in range(30)
    )
    + "CustomAction InstallDriver returned actual error code 1603 (note this may not be 100% accurate if translation happened inside sandbox)\n"
    + "Action ended 9:41:12: InstallFinalize. Return value 3.\n"
    + "MSI (s) (A4:B8) [09:41:12:880]: Product: Example Agent -- Installation failed.\n"
    + "=== Logging stopped: 10/21/2026  09:41:12 ===\n"
)


def test_msi_log_detection_and_compression():
    assert detect_test_runner(MSI_TEXT) == "msi_log"

    for query in ("", "why did the install fail"):
        out = compress_context(MSI_TEXT, query, ccr=False, citations=False).compressed_text
        assert "error code 1603" in out
        assert "Return value 3" in out
        assert "Installation failed" in out
        assert "Verbose logging started" in out
        assert len(out) < 0.25 * len(MSI_TEXT)


def test_classify_msi_log_keeps_failure_and_drops_success():
    lines = MSI_TEXT.splitlines()
    keep, _, _ = _classify_msi_log(lines)

    assert keep[lines.index("Action ended 9:41:12: InstallFinalize. Return value 3.")]
    assert not keep[lines.index("Action ended 9:40:05: Action5. Return value 1.")]


def test_msi_log_detection_requires_ten_routine_lines():
    text = (
        "=== Verbose logging started: 10/21/2026  09:40:02  Build type: SHIP UNICODE 5.00.10011.00 ===\n"
        + "".join(
            f"MSI (s) (A4:B8) [09:40:{i:02d}:123]: Doing action: Action{i}\n"
            f"Action start 9:40:{i:02d}: Action{i}.\n"
            f"Action ended 9:40:{i:02d}: Action{i}. Return value 1.\n"
            for i in range(3)
        )
    )
    assert detect_test_runner(text) != "msi_log"


def test_msi_log_detection_requires_marker():
    text = "".join(
        f"Action start 9:40:{i:02d}: Action{i}.\n"
        f"Action ended 9:40:{i:02d}: Action{i}. Return value 1.\n"
        for i in range(10)
    )
    assert detect_test_runner(text) != "msi_log"
