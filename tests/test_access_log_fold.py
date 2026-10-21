from tameru.compress_context import classify_line, compress_context, preprocess_logs


def _line(i, status, method="GET"):
    return f'10.0.0.{i} - - [21/Oct/2026:10:{i:02d}:11 +0900] "{method} /api/items/{100 + i} HTTP/1.1" {status} {500 + i} "-" "curl/8.4"'


def test_classify_access_log_line():
    assert classify_line(_line(1, 200)) == "log"


def test_preprocess_folds_2xx_and_keeps_4xx_3xx_unique():
    lines = [_line(i, 404 if i in (7, 23) else (301 if i == 12 else 200)) for i in range(40)]
    out = preprocess_logs(lines, "")
    assert any(o.startswith("[\u00d737]") for o in out)
    assert _line(7, 404) in out and _line(23, 404) in out and _line(12, 301) in out


def test_5xx_is_kept_untouched():
    lines = [_line(i, 200) for i in range(30)] + [_line(31, 503, "POST")]
    out = preprocess_logs(lines, "")
    assert _line(31, 503, "POST") in out
    assert len(out) <= 4


def test_single_post_2xx_is_not_folded_into_get_run():
    lines = [_line(i, 200) for i in range(30)] + [_line(31, 201, "POST")]
    out = preprocess_logs(lines, "")
    assert _line(31, 201, "POST") in out


def test_compress_context_keeps_5xx_and_saves_space():
    text = "\n".join(_line(i, 200) for i in range(40)) + "\n" + '10.0.0.77 - - [21/Oct/2026:10:41:02 +0900] "POST /api/checkout HTTP/1.1" 502 157 "-" "Mozilla/5.0"' + "\n"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True, min_savings_ratio=0.1)
    assert '"POST /api/checkout HTTP/1.1" 502' in r.compressed_text
    assert len(r.compressed_text) < len(text) * 0.3
