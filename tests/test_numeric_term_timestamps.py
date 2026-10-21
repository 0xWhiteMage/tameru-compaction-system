from tameru.compress_context import _term_test, compress_context


def test_numeric_term_matches_error_and_exit():
    t = _term_test("11")
    assert t("innodb unable to lock ./ibdata1 error: 11")
    assert t("exit status 11")


def test_numeric_term_does_not_match_clock_times():
    t = _term_test("11")
    assert not t("2026-10-21t04:00:11.000000z 0 [note] aborted connection")
    assert not t("at 11:30:00 the job ran")
    assert not t("13:11:02 tick")


def test_numeric_term_matches_port_after_letter_colon():
    assert _term_test("8080")("listening on localhost:8080")


def test_compress_context_keeps_error_and_drops_note_timestamps():
    text = (
        "\n".join(
            f"2026-10-21T04:{i:02d}:11.000000Z 0 [Note] [MY-010914] [Server] "
            f"Aborted connection {100 + i} to db: 'app' user: 'app' "
            f"host: '10.0.0.{i}' (Got timeout reading communication packets)."
            for i in range(30)
        ) + "\n2026-10-21T04:31:02.123456Z 12 [ERROR] [MY-012574] [InnoDB] "
        "Unable to lock ./ibdata1 error: 11\n"
    )

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "Unable to lock ./ibdata1" in r.compressed_text
    assert len(r.compressed_text) < 0.25 * len(text)
