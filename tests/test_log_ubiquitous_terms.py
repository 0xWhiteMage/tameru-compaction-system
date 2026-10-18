from tameru.compress_context import (
    CompressResult,
    compress_context,
    score_blocks,
    segment_blocks,
)


def _log() -> str:
    lines = [
        f"2026-10-18 11:00:{i:02d}.123 INFO  [http-nio-8080-exec-1] o.e.billing.Api - handled request id={1000+i}"
        for i in range(30)
    ]
    lines.append("2026-10-18 11:59:00.001 ERROR [http-nio-8080-exec-3] o.e.billing.Api - request failed")
    lines.append("java.lang.NullPointerException: boom")
    lines.extend(
        f"\tat org.example.billing.Step{i}.run(Step{i}.java:{10+i})"
        for i in range(8)
    )
    return "\n".join(lines)


def test_score_blocks_ignores_ubiquitous_term_when_other_term_hits() -> None:
    blocks = score_blocks(segment_blocks(_log().split("\n")), "billing failed")

    assert len(blocks) < 10

    failed_block = next((block for block in blocks if "request failed" in block["text"]), None)
    assert failed_block is not None
    assert failed_block["term_hits"] >= 1

    for block in blocks:
        if "failed" not in block["text"]:
            assert block["term_hits"] == 0


def test_score_blocks_ubiquitous_or_common_terms_do_not_explode_hits() -> None:
    blocks = score_blocks(segment_blocks(_log().split("\n")), "billing handled")

    failed_block = next((block for block in blocks if "request failed" in block["text"]), None)
    assert failed_block is not None
    assert failed_block["term_hits"] <= 2


def test_compress_context_keeps_error_and_saves_space() -> None:
    result = compress_context(
        _log(),
        "billing failed",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )

    assert not result.fail_open
    assert "request failed" in result.compressed_text
    assert "NullPointerException" in result.compressed_text
    assert len(result.compressed_text) < 0.7 * len(_log())

def test_compress_context_fail_open_retry_anchors_on_errors() -> None:
    result = compress_context(
        _log(),
        "why did the billing request fail",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )

    assert not result.fail_open
    assert "request failed" in result.compressed_text
    assert "NullPointerException" in result.compressed_text
    assert len(result.compressed_text) < 0.7 * len(_log())


def test_compress_context_large_log_fail_open_retry_is_noop() -> None:
    lines = _log().split("\n")
    big = "\n".join(lines * 20)
    assert len(big) > 30000

    result = compress_context(
        big,
        "why did the billing request fail",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )

    assert isinstance(result, CompressResult)


def test_compress_context_no_errors_informative_query_runs_no_probe() -> None:
    text = "\n".join(
        [
            "INFO 2024-05-01T10:00:00Z billing service started",
            "INFO 2024-05-01T10:00:01Z billing request accepted id=1",
            "INFO 2024-05-01T10:00:02Z billing request accepted id=2",
            "INFO 2024-05-01T10:00:03Z billing request accepted id=3",
            "INFO 2024-05-01T10:00:04Z billing request accepted id=4",
            "INFO 2024-05-01T10:00:05Z billing request accepted id=5",
            "INFO 2024-05-01T10:00:06Z billing request accepted id=6",
            "INFO 2024-05-01T10:00:07Z billing request accepted id=7",
            "INFO 2024-05-01T10:00:08Z billing request accepted id=8",
            "INFO 2024-05-01T10:00:09Z billing request accepted id=9",
        ]
    )
    kwargs = dict(
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )

    result = compress_context(text, "why did the billing request fail", anchor_errors=True, **kwargs)
    baseline = compress_context(text, "why did the billing request fail", anchor_errors=False, **kwargs)

    assert result.compressed_text == baseline.compressed_text
    assert result.fail_open == baseline.fail_open


def test_generic_small_erroring_log_prefers_anchored_result():
    lines = [
        f"2026-10-18 05:10:{i:02d}.{100 + i} INFO  [pool-2-thread-{i}] c.shop.order.OrderService - order processed ok id={500 + i}"
        for i in range(45)
    ]
    lines.append("2026-10-18 05:11:00.010 ERROR [pool-2-thread-7] c.shop.order.OrderService - order processing failed")
    lines.append('org.springframework.dao.DataIntegrityViolationException: duplicate key value violates unique constraint "orders_pkey"')
    lines.extend(f"\tat c.shop.order.Repo{i}.save(Repo{i}.java:{200 + i})" for i in range(18))
    lines.append("\t... 30 more")
    lines.extend(
        f"2026-10-18 05:11:{i:02d}.{200 + i} INFO  [pool-2-thread-{i}] c.shop.order.OrderService - order processed ok id={600 + i}"
        for i in range(8)
    )
    text = "\n".join(lines)
    query = "why did order processing fail"

    result = compress_context(
        text,
        query,
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )
    plain = compress_context(
        text,
        query,
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=False,
        prose_brief=True,
        min_savings_ratio=0.1,
    )

    assert not result.fail_open
    assert "DataIntegrityViolationException" in result.compressed_text
    assert "order processing failed" in result.compressed_text
    assert len(result.compressed_text) <= len(plain.compressed_text)
    assert len(result.compressed_text) < 0.35 * len(text)


def test_anchored_preference_keeps_error_adjacent_context():
    lines = []
    for i in range(1, 81):
        if i == 40:
            lines.append("ERROR payment gateway timeout order=991")
        elif i == 41:
            lines.append("retry 1/3")
        elif i == 42:
            lines.append("ERROR payment gateway timeout order=992")
        else:
            lines.append(
                f"2026-10-11 12:00:{i:02d} INFO worker-{i % 10} processed batch {i:03d} in 12ms "
                + "x" * 40
            )

    text = "\n".join(lines)
    result = compress_context(
        text,
        "why did the payment gateway time out?",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        gap_marker=lambda omitted, total: f"[{omitted} lines omitted]",
        min_savings_ratio=0.1,
    )

    assert (
        "ERROR payment gateway timeout order=991\n"
        "retry 1/3\n"
        "ERROR payment gateway timeout order=992"
    ) in result.compressed_text
    assert result.receipt["query_source"] in ("caller", "error-anchored")
