from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def _log():
    return (
        "\n".join(
            f"# Query_time: 0.00{i % 10}  Lock_time: 0.000  Rows_sent: 1  Rows_examined: 1\nSELECT * FROM users WHERE id = {i};"
            for i in range(25)
        )
        + "\n# Query_time: 41.207  Lock_time: 0.000  Rows_sent: 12  Rows_examined: 98123456\nSELECT * FROM orders o JOIN items i ON i.order_id = o.id WHERE o.status LIKE '%pending%';\n"
    )


def test_slowlog_detect_and_keep():
    text = _log()
    assert detect_test_runner(text) == "slowlog"
    out = preprocess_test_output(text)
    assert "41.207" in out
    assert "98123456" in out
    assert "o.status LIKE" in out
    assert "id = 0;" in out
    assert "id = 13;" not in out


def test_slowlog_compress_context():
    text = _log()
    r = compress_context(text, "", ccr=False, citations=False)
    assert "41.207" in r.compressed_text
    assert "98123456" in r.compressed_text
    assert len(r.compressed_text) < len(text) * 0.5


def test_slowlog_headers():
    parts = []
    for i in range(8):
        parts.append(
            f"# Time: 2026-10-21T04:0{i}:00Z\n"
            f"# User@Host: app[app] @ [10.0.0.5]  Id: 1{i}\n"
            "# Query_time: 0.002  Lock_time: 0.000  Rows_sent: 1  Rows_examined: 5\n"
            f"SET timestamp=176101920{i};\n"
            f"SELECT {i};"
        )
    parts.append(
        "# Time: 2026-10-21T04:09:00Z\n"
        "# User@Host: app[app] @ [10.0.0.5]  Id: 19\n"
        "# Query_time: 12.500  Lock_time: 0.000  Rows_sent: 1  Rows_examined: 5\n"
        "SET timestamp=1761019209;\n"
        "SELECT sleep(12);"
    )
    text = "\n".join(parts)
    out = preprocess_test_output(text)
    assert "SELECT sleep(12);" in out
    assert "12.500" in out
    assert "Id: 19" in out
    assert "SELECT 4;" not in out


def test_slowlog_requires_five_query_time_lines():
    text = "\n".join(
        f"# Query_time: 0.00{i}  Lock_time: 0.000  Rows_sent: 1  Rows_examined: 1\nSELECT {i};"
        for i in range(4)
    )
    assert detect_test_runner(text) != "slowlog"
