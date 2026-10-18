from tameru.compress_context import _strip_anchor_prefix


def test_strip_anchor_prefix_notice():
    assert (
        _strip_anchor_prefix(
            "2026-10-18 09:11:00 NOTICE patroni: failover started, promoting pg-2 to leader"
        )
        == "NOTICE failover started, promoting pg-2 to leader"
    )


def test_strip_anchor_prefix_crit():
    assert (
        _strip_anchor_prefix(
            "2026-10-18 09:11:00 CRIT patroni: failover started, promoting pg-2 to leader"
        )
        == "CRIT failover started, promoting pg-2 to leader"
    )


def test_strip_anchor_prefix_alert():
    assert (
        _strip_anchor_prefix(
            "2026-10-18 09:11:00 ALERT patroni: failover started, promoting pg-2 to leader"
        )
        == "ALERT failover started, promoting pg-2 to leader"
    )


def test_strip_anchor_prefix_noticeable_unchanged():
    assert (
        _strip_anchor_prefix("2026-10-18 09:11:00 NOTICEABLE thing")
        == "2026-10-18 09:11:00 NOTICEABLE thing"
    )
