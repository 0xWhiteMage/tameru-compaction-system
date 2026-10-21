from tameru.compress_context import (
    classify_line,
    route_content_type,
    _rare_template_lines,
    compress_context,
)


def test_syslog_prefix_classification():
    bsd = "Oct 21 07:00:00 host systemd[1]: Started session-1.scope - Session 1 of User app."
    journal = "2026-10-21T08:00:11+0900 web-2 sshd[812]: Accepted publickey for deploy from 10.0.0.5 port 5123 ssh2"
    dmesg = "[   12.345678] usb 1-1: new high-speed USB device number 5 using xhci_hcd"

    assert classify_line(bsd) == "log"
    assert classify_line(journal) == "log"
    assert classify_line(dmesg) == "log"
    assert classify_line("Oct 21 is my birthday") == "text"

    lines = [
        f"Oct 21 07:{i:02d}:00 host systemd[1]: Started session-{i}.scope - Session {i} of User app."
        for i in range(40)
    ]
    assert route_content_type(lines) == "log"


def test_systemd_rare_restart_anchor_kept():
    lines = [
        f"Oct 21 07:{i:02d}:00 host systemd[1]: Started session-{i}.scope - Session {i} of User app."
        for i in range(40)
    ]
    lines.append(
        "Oct 21 07:41:00 host systemd[1]: app-worker.service: Scheduled restart job, restart counter is at 5."
    )
    lines.extend(
        f"Oct 21 07:5{i}:00 host systemd[1]: Started session-x{i}.scope - Session x{i} of User app."
        for i in range(4)
    )

    text = "\n".join(lines)
    result = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert "restart counter is at 5" in result.compressed_text
    assert not result.fail_open
    assert len(result.compressed_text) < len(text) // 2


def test_dmesg_rare_ext4_anchor():
    lines = [
        f"[{i:5d}.{100000 + i:06d}] usb 1-{i}: new high-speed USB device number {i} using xhci_hcd"
        for i in range(35)
    ]
    ext4 = "[  412.000117] EXT4-fs error (device nvme0n1p2): ext4_find_entry:1455: reading directory lblock 0"
    lines.append(ext4)

    assert ext4 in _rare_template_lines(lines, 8)


def test_rare_template_guards():
    prose = [f"Line {i} talks about topic {i * 7} in plain words." for i in range(35)]
    prose.append("One odd sentence with unique words.")
    assert _rare_template_lines(prose, 8) == []

    syslog = [
        f"Oct 21 07:{i:02d}:00 host systemd[1]: Started session-{i}.scope - Session {i} of User app."
        for i in range(34)
    ]
    syslog.append("Oct 21 07:34:00 host systemd[1]: alpha beta gamma delta")
    syslog.append("Oct 21 07:35:00 host systemd[1]: epsilon zeta eta theta")
    syslog.append("Oct 21 07:36:00 host systemd[1]: iota kappa lambda mu")
    assert _rare_template_lines(syslog, 8) == []

    short = [
        f"Oct 21 07:{i:02d}:00 host systemd[1]: Started session-{i}.scope - Session {i} of User app."
        for i in range(20)
    ]
    assert _rare_template_lines(short, 8) == []
def test_syslog_anchor_prefix_stripping():
    from tameru.compress_context import _strip_anchor_prefix

    assert (
        _strip_anchor_prefix(
            "Oct 21 07:41:00 host systemd[1]: app-worker.service: Scheduled restart job, restart counter is at 5."
        )
        == "app-worker.service: Scheduled restart job, restart counter is at 5."
    )
    assert (
        _strip_anchor_prefix(
            "2026-10-21T08:39:02+0900 web-2 kernel: Out of memory: Killed process 4412 (node)"
        )
        == "Out of memory: Killed process 4412 (node)"
    )
    assert (
        _strip_anchor_prefix("[  412.000117] EXT4-fs error (device nvme0n1p2): bad entry")
        == "EXT4-fs error (device nvme0n1p2): bad entry"
    )


def test_syslog_anchor_prefix_empty_message():
    from tameru.compress_context import _strip_anchor_prefix

    result = _strip_anchor_prefix("Oct 21 07:41:00 host systemd[1]: ")
    assert result.strip() != ""


def test_syslog_systemd_compress():
    from tameru.compress_context import compress_context

    lines = [
        f"Oct 21 07:{i:02d}:00 host systemd[1]: Started session-{i}.scope - Session {i} of User app."
        for i in range(40)
    ]
    lines.append(
        "Oct 21 07:41:00 host systemd[1]: "
        "app-worker.service: Scheduled restart job, restart counter is at 5."
    )
    lines.extend(
        f"Oct 21 07:5{i}:00 host systemd[1]: Started session-x{i}.scope - Session x{i} of User app."
        for i in range(4)
    )
    text = "\n".join(lines)

    result = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    compressed_text = result.compressed_text

    assert len(compressed_text) < 0.2 * len(text)
    assert "restart counter is at 5" in compressed_text
