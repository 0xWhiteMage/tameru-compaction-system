from tameru.compress_context import compress_context


def _cron_text() -> str:
    lines = []
    for i in range(40):
        lines.append(
            f"Oct 21 09:{i:02d}:01 db-1 CRON[{100 + i * 7}]: "
            "(root) CMD (/usr/local/bin/backup.sh --incremental)"
        )
    lines.append(
        "Oct 21 09:40:01 db-1 CRON[3321]: (root) MAIL "
        "(mailed 312 bytes of output but got status 0x004b from MTA)"
    )
    return "\n".join(lines)


def test_rare_topic_anchor_keeps_mail_error_line():
    text = _cron_text()
    result = compress_context(
        text,
        "did cron fail to send mail",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert not result.fail_open
    assert "0x004b" in result.compressed_text
    assert len(result.compressed_text) < 0.15 * len(text)


def test_common_topic_query_is_unaffected():
    text = _cron_text()
    result = compress_context(
        text,
        "show cron backup runs",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "backup.sh" in result.compressed_text


def test_prose_mail_query_still_contains_mail_delivery():
    lines = [
        f"Paragraph {i} talks about the weather and nothing else."
        for i in range(30)
    ]
    lines.append("One line mentions mail delivery.")
    text = "\n".join(lines)
    result = compress_context(
        text,
        "what about mail",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "mail delivery" in result.compressed_text
