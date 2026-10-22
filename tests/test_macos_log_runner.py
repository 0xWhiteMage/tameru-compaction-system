from tameru.agent_formats import detect_test_runner, _classify_macos_log
from tameru.compress_context import compress_context


def _default_lines():
    routine = [
        f"2026-10-22 09:{i:02d}:10.000000+0900 0x1a{i:02x}    Default     0x0                  412    0    backupd: [com.apple.TimeMachine:General] Backing up {100 + i} items"
        for i in range(40)
    ]
    lines = routine[:25]
    lines.append(
        "2026-10-22 09:25:30.000000+0900 0x2f1a    Error       0x0                  412    0    backupd: [com.apple.TimeMachine:General] Failed to mount backup disk: error 21 for /Volumes/Backups of alice-mbp"
    )
    lines.extend(routine[25:])
    lines.append("-" * 80)
    lines.append("Log      - Default:         40, Info:                0, Debug:             0, Error:          1, Fault:          0")
    return lines


def test_detect_and_compress_default_style():
    header = (
        "Filtering the log data using \"process == \\\"backupd\\\"\"\n"
        "Timestamp                       Thread     Type        Activity             PID    TTL  \n"
    )
    text = header + "\n".join(_default_lines())

    assert detect_test_runner(text) == "macos_log"

    for query in ("", "why did the backup fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "Failed to mount backup disk: error 21" in out
        assert "Backing up 100 items" in out
        assert "Backing up 139 items" in out
        assert "Error:          1" in out
        assert len(out) < 0.4 * len(text)


def test_classify_keeps_adjacent_and_edge_routine_lines():
    lines = _default_lines()
    keep, _, _ = _classify_macos_log(lines)

    kept_routine = sum(
        1
        for kept, line in zip(keep, lines)
        if kept and "Default" in line and "Backing up" in line
    )

    assert kept_routine == 4


def test_detect_compact_style():
    lines = [
        f"2026-10-22 09:{i:02d}:10.000 Df backupd[412:1a{i:02x}] [com.apple.TimeMachine:General] Backing up {i} items"
        for i in range(30)
    ]
    lines.insert(
        15,
        "2026-10-22 09:15:10.000 E  backupd[412:2f1a] [com.apple.TimeMachine:General] Failed to mount backup disk",
    )
    text = "\n".join(lines)

    assert detect_test_runner(text) == "macos_log"


def test_detect_negative_without_error():
    header = (
        "Filtering the log data using \"process == \\\"backupd\\\"\"\n"
        "Timestamp                       Thread     Type        Activity             PID    TTL  \n"
    )
    lines = [
        line
        for line in _default_lines()
        if "Error" not in line and not line.startswith("Log")
    ]
    text = header + "\n".join(lines)

    assert detect_test_runner(text) != "macos_log"
