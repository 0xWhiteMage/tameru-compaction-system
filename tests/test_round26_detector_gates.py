from tameru.agent_formats import detect_test_runner


def test_indented_crlf_iostat_zero_rows():
    lines = ["  Device r/s w/s rkB/s wkB/s %util"]
    lines.extend(f"  loop{i} 0.00 0.00 0.00 0.00 0.00" for i in range(10))
    lines.append("  nvme0n1 412.00 3810.00 16480.00 121920.00 99.80")
    text = "\r\n".join(lines) + "\r\n"
    assert detect_test_runner(text) == "zero_rows"


def test_curl_verbose():
    text = (
        "*   Trying 203.0.113.10:443...\n"
        "* Connected to api.example.com (203.0.113.10) port 443\n"
        + "".join(f"* TLSv1.3 (IN), TLS handshake, step {i} (2):\n" for i in range(8))
        + "> GET /v1/orders HTTP/2\n"
        + "> Host: api.example.com\n"
        + ">\n"
        + "< HTTP/2 503\n"
        + "<\n"
        + "body\n"
    )
    assert detect_test_runner(text) == "curl_verbose"


def test_npm_tree():
    text = "app@1.0.0 /srv/app\n" + "".join(f"+-- pkg-{i}@1.0.0\n" for i in range(10))
    assert detect_test_runner(text) == "npm_tree"


def test_rollout_wait():
    text = "".join(
        f'Waiting for deployment "api" rollout to finish: {i} of 10 updated replicas are available...\n'
        for i in range(7)
    )
    assert detect_test_runner(text) == "rollout_wait"


def test_systemd_blame():
    text = "".join(f"{100 + i}ms unit-{i}.service\n" for i in range(12))
    assert detect_test_runner(text) == "systemd_blame"


def test_ping():
    text = (
        "PING h (10.0.0.1) 56(84) bytes of data.\n"
        + "".join(
            f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time=1.{i} ms\n"
            for i in range(9)
        )
    )
    assert detect_test_runner(text) == "ping"


def test_plain_prose_is_not_detected():
    text = (
        "The service restarted after the deploy finished. "
        "Most requests recovered, but a few retries remained. "
        "We should review the timeout settings later."
    )
    assert detect_test_runner(text) not in {
        "zero_rows",
        "curl_verbose",
        "npm_tree",
        "rollout_wait",
        "systemd_blame",
        "ping",
    }
