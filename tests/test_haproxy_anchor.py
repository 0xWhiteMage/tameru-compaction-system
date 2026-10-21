from tameru.compress_context import _strip_anchor_prefix, compress_context


def test_strip_haproxy_anchor():
    line = (
        "Oct 21 13:30:00 lb1 haproxy[71]: "
        "10.1.0.9:51234 [21/Oct/2026:13:30:00.001] web~ api/<NOSRV> "
        "0/-1/-1/-1/0 503 217 - - SC-- 10/10/0/0/0 0/0 "
        '"GET /api/items HTTP/1.1"'
    )
    assert _strip_anchor_prefix(line) == "api/<NOSRV> 503 SC--"


def test_compress_haproxy_503_anchor():
    text = "\n".join(
        f'Oct 21 13:{i:02d}:00 lb1 haproxy[71]: 10.1.0.{i}:5{i}00 '
        f'[21/Oct/2026:13:{i:02d}:00.123] web~ api/app1 '
        f'0/0/1/{i + 10}/{i + 11} 200 512 - - ---- 10/10/0/0/0 0/0 '
        '"GET /api/items HTTP/1.1"'
        for i in range(30)
    ) + (
        "\nOct 21 13:30:00 lb1 haproxy[71]: 10.1.0.9:51234 "
        "[21/Oct/2026:13:30:00.001] web~ api/<NOSRV> "
        "0/-1/-1/-1/0 503 217 - - SC-- 10/10/0/0/0 0/0 "
        '"GET /api/items HTTP/1.1"\n'
    )
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "<NOSRV>" in r.compressed_text
    assert " 503 " in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(text)
