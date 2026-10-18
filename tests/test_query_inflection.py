from tameru.compress_context import _term_test, _term_in_text, _inflection_stem, compress_context


POSITIVE = [
    ("fail", "card authorization failed"),
    ("failing", "job failed"),
    ("failed", "failure in step 3"),
    ("error", "2 errors found"),
    ("errors", "error: bad"),
    ("payments", "payment declined"),
    ("timeouts", "timeout after 30s"),
]

NEGATIVE = [
    ("fail", "failover started"),
    ("error", "errorless run"),
    ("test", "contest results"),
    ("status", "statue"),
    ("case", "cash"),
    ("port", "portal open"),
]


def test_positive_matches():
    for term, text in POSITIVE:
        assert _term_test(term)(text)
        assert _term_in_text(term, text)


def test_negative_no_match():
    for term, text in NEGATIVE:
        assert not _term_test(term)(text)
        assert not _term_in_text(term, text)


def test_term_test_matches_term_in_text():
    for term, text in POSITIVE + NEGATIVE:
        assert _term_test(term)(text) == _term_in_text(term, text)


def test_syllabic_rule_unchanged():
    assert _term_test("エラー")("サーバーエラー発生") is True


def test_inflection_stem():
    assert _inflection_stem("failing") == "fail"
    assert _inflection_stem("failed") == "fail"
    assert _inflection_stem("errors") == "error"
    assert _inflection_stem("process") == "process"
    assert _inflection_stem("status") == "status"
    assert _inflection_stem("cases") == "case"
    assert _inflection_stem("go") is None
    assert _inflection_stem("k8s") is None


def test_compress_context_inflection_query():
    lines = [
        f"2026-10-18 06:30:{i:02d} INFO checkout: order {100 + i} accepted"
        for i in range(40)
    ]
    lines.append(
        "2026-10-18 06:31:00 WARN checkout: card authorization failed for order 8812 (issuer declined)"
    )
    lines.extend(
        f"2026-10-18 06:32:{i:02d} INFO checkout: order {200 + i} accepted"
        for i in range(10)
    )
    text = "\n".join(lines)
    result = compress_context(
        text,
        "which payments are failing",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )
    assert "authorization failed" in result.compressed_text
    assert "8812" in result.compressed_text
    assert len(result.compressed_text) < 0.5 * len(text)
    assert hasattr(result, "compressed_text")
    assert hasattr(result, "fail_open")
