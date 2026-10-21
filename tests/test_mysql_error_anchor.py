from tameru.compress_context import _strip_anchor_prefix, compress_context


def test_mysql_error_prefix_stripped():
    assert (
        _strip_anchor_prefix(
            "2026-10-21T04:31:02.123456Z 12 [ERROR] [MY-012574] [InnoDB] Unable to lock ./ibdata1 error: 11"
        )
        == "ERROR Unable to lock ./ibdata1 error: 11"
    )


def test_mysql_error_anchor_compresses_note_lines():
    text = "\n".join(
        f"2026-10-21T04:{i:02d}:11.000000Z 0 [Note] [MY-010914] [Server] Aborted connection {100 + i} to db: 'app' user: 'app' host: '10.0.0.{i}' (Got timeout reading communication packets)."
        for i in range(30)
    ) + "\n2026-10-21T04:31:02.123456Z 12 [ERROR] [MY-012574] [InnoDB] Unable to lock ./ibdata1 error: 11\n"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "MY-012574" in r.compressed_text
    assert "Unable to lock ./ibdata1" in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(text)
