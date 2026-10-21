from tameru.compress_context import compress_context


def test_short_syslog_rare_template_compressed():
    text = "\n".join(
        f"Oct 21 {h:02d}:00:01 host CRON[{100 + h * 7}]: (root) CMD (/usr/local/bin/backup.sh)"
        for h in range(18)
    ) + "\nOct 21 19:00:02 host CRON[7781]: (root) MAIL (mailed 312 bytes of output but got status 0x004b from MTA)\n"

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert "status 0x004b" in r.compressed_text
    assert "MAIL" in r.compressed_text
    assert len(r.compressed_text) < len(text) * 0.5
    assert not r.fail_open


def test_short_leveled_log_guard():
    lines = [f"2026-10-21 10:00:{i:02d} INFO worker tick ok" for i in range(17)]
    lines.append("2026-10-21 10:00:59 INFO worker reloaded config")
    text = "\n".join(lines)

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert r.compressed_text == text or "reloaded config" in r.compressed_text


def test_threshold_syslog_keeps_mail():
    text = "\n".join(
        f"Oct 21 {h:02d}:00:01 host CRON[{100 + h * 7}]: (root) CMD (/usr/local/bin/backup.sh)"
        for h in range(14)
    ) + "\nOct 21 19:00:02 host CRON[7781]: (root) MAIL (mailed 312 bytes of output but got status 0x004b from MTA)\n"

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert "status 0x004b" in r.compressed_text
    assert "MAIL" in r.compressed_text


def test_below_threshold_syslog_fail_open():
    text = "\n".join(
        f"Oct 21 {h:02d}:00:01 host CRON[{100 + h * 7}]: (root) CMD (/usr/local/bin/backup.sh)"
        for h in range(13)
    ) + "\nOct 21 19:00:02 host CRON[7781]: (root) MAIL (mailed 312 bytes of output but got status 0x004b from MTA)\n"

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert r.fail_open
