from tameru.agent_formats import detect_test_runner, _classify_curl_verbose
from tameru.compress_context import compress_context


def _build_curl_verbose_text() -> str:
    return (
        "*   Trying 203.0.113.10:443...\n"
        "* Connected to api.example.com (203.0.113.10) port 443\n"
        "* ALPN: offers h2,http/1.1\n"
        + "".join(f"* TLSv1.3 (IN), TLS handshake, step {i} (2):\n" for i in range(12))
        + "> GET /v1/orders HTTP/2\n"
        "> Host: api.example.com\n"
        "> User-Agent: curl/8.5.0\n"
        "> Accept: */*\n"
        ">\n"
        "< HTTP/2 503\n"
        "< content-type: application/json\n"
        "< retry-after: 120\n"
        + "".join(f"< x-trace-{i}: t{i}\n" for i in range(10))
        + "<\n"
        + "{\"error\":\"upstream unavailable\",\"region\":\"eu-west\"}\n"
        + "* Connection #0 to host api.example.com left intact\n"
    )


def test_detect_curl_verbose() -> None:
    text = _build_curl_verbose_text()
    assert detect_test_runner(text) == "curl_verbose"


def test_compress_curl_verbose_keeps_key_lines() -> None:
    text = _build_curl_verbose_text()
    for query in ("", "why did the request fail"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "HTTP/2 503" in out
        assert "upstream unavailable" in out
        assert "retry-after: 120" in out
        assert "> GET /v1/orders HTTP/2" in out
        assert "Connected to api.example.com" in out
        assert len(out) < 0.6 * len(text)


def test_classify_curl_verbose_keeps_tls_alert_and_errors() -> None:
    lines = [
        "* TLSv1.3 (IN), TLS alert, unknown CA (560):",
        "* TLSv1.2 (OUT), TLS header, Certificate Status (22):",
        "{ [5 bytes data]",
        "curl: (60) SSL certificate problem: unable to get local issuer certificate",
    ]
    keep, _, _ = _classify_curl_verbose(lines)
    assert keep[0] is True
    assert keep[1] is False
    assert keep[2] is False
    assert keep[3] is True


def test_classify_curl_verbose_keeps_few_response_headers() -> None:
    lines = [
        "> GET /v1/orders HTTP/2",
        "< HTTP/2 503",
        "< x-trace-0: t0",
        "< x-trace-1: t1",
        "< x-trace-2: t2",
        "< x-trace-3: t3",
    ]
    keep, _, _ = _classify_curl_verbose(lines)
    assert keep == [True] * len(lines)


def test_plain_markdown_list_is_not_curl_verbose() -> None:
    text = "".join(f"* item {i}\n" for i in range(10))
    assert detect_test_runner(text) != "curl_verbose"
