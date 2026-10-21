from tameru.compress_context import classify_line, route_content_type, compress_context


def test_apache_error_line_classified_as_log():
    line = (
        "[Wed Oct 21 10:00:00.000000 2026] [mpm_event:notice] "
        "[pid 1:tid 1] AH00489: Apache/2.4.58 configured -- resuming normal operations"
    )
    assert classify_line(line) == "log"


def test_apache_error_lines_route_to_log():
    lines = [
        "[Wed Oct 21 10:%02d:00.000000 2026] [mpm_event:notice] "
        "[pid 1:tid 1] AH00489: Apache/2.4.58 configured -- resuming normal operations" % i
        for i in range(25)
    ] + [
        "[Wed Oct 21 10:25:13.441201 2026] [proxy:error] [pid 88:tid 140] "
        "(111)Connection refused: AH00957: http: attempt to connect to 127.0.0.1:9000 (backend) failed"
    ]
    assert route_content_type(lines) == "log"


def test_apache_error_context_preserves_error_details():
    lines = [
        "[Wed Oct 21 10:%02d:00.000000 2026] [mpm_event:notice] "
        "[pid 1:tid 1] AH00489: Apache/2.4.58 configured -- resuming normal operations" % i
        for i in range(25)
    ] + [
        "[Wed Oct 21 10:25:13.441201 2026] [proxy:error] [pid 88:tid 140] "
        "(111)Connection refused: AH00957: http: attempt to connect to 127.0.0.1:9000 (backend) failed"
    ]
    r = compress_context(
        "\n".join(lines) + "\n",
        "why is the site returning 503",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "AH00957" in r.compressed_text
    assert "127.0.0.1:9000" in r.compressed_text


def test_plain_weekday_month_text_not_log():
    assert classify_line("Wed is a weekday and Oct a month") != "log"
