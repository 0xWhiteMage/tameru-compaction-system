from tameru.agent_formats import detect_test_runner, preprocess_test_output

HEADER = "USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"
ROWS = [
    f"www-data  {1000 + i}  0.{i % 10}  0.4 {200000 + i} {20000 + i} ?        S    09:00   0:00 php-fpm: pool www"
    for i in range(30)
]


def test_ps_aux_big_listing_is_reduced():
    text = (
        "\n".join(
            [
                HEADER,
                *ROWS,
                "root      77712 98.7 31.2 9921000 5120000 ?     R    10:01  41:13 /usr/bin/python3 /opt/etl/reindex.py --all",
            ]
        )
        + "\n"
    )

    assert detect_test_runner(text) == "ps_aux"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert HEADER in out
    assert "reindex.py --all" in out
    assert "98.7" in out
    assert "process rows omitted" in out
    assert "1017" not in out
    assert len(out) < len(text) * 0.4


def test_ps_aux_keeps_zombie_and_d_state_rows():
    text = (
        "\n".join(
            [
                HEADER,
                *ROWS,
                "app       4242  0.0  0.0      0     0 ?        Z    10:00   0:00 [worker] <defunct>",
                "root      5151  0.1  0.2  10000  2000 ?        D    10:00   0:03 /usr/sbin/nfsd",
            ]
        )
        + "\n"
    )

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "<defunct>" in out
    assert "/usr/sbin/nfsd" in out


def test_ps_aux_short_listing_is_not_detected():
    text = HEADER + "\nroot 1 0.0 0.1 1000 100 ? Ss 09:00 0:01 /sbin/init\n"
    assert detect_test_runner(text) is None
