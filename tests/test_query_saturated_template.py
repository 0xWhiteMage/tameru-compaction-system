from tameru.compress_context import compress_context, preprocess_logs


def test_query_saturated_template_collapses_when_discriminating_hit_exists():
    lines = [
        f"2026-10-21 10:{i:02d}:00 WARN loader: spec.template.containers[0].env[{i}] hides previous definition"
        for i in range(12)
    ] + [
        "2026-10-21 10:13:00 ERROR install failed: spec.template.containers[0].image required value"
    ]
    out = preprocess_logs(lines, "why did install fail spec.template.containers image")
    assert any(line.startswith("[\u00d712]") for line in out)
    assert lines[-1] in out
    assert len(out) <= 4


def test_volatile_selector_record_kept():
    lines = [
        f"2026-10-21 10:{i:02d}:00 INFO Etiqa policy {i}: recycling balance {1000 + i} units"
        for i in range(30)
    ]
    out = preprocess_logs(lines, "What is the recycling balance for Etiqa policy 17?")
    assert "2026-10-21 10:17:00 INFO Etiqa policy 17: recycling balance 1017 units" in out
    assert any(line.startswith("[\u00d729]") for line in out)


def test_volatile_selector_record_kept_next_to_error():
    lines = [
        f"2026-10-21 10:{i:02d}:00 INFO Etiqa policy {i}: recycling balance {1000 + i} units"
        for i in range(30)
    ] + ["2026-10-21 11:00:00 ERROR Etiqa sync failed: upstream timeout"]
    out = preprocess_logs(lines, "What is the recycling balance for Etiqa policy 17?")
    assert "2026-10-21 10:17:00 INFO Etiqa policy 17: recycling balance 1017 units" in out
    assert "2026-10-21 11:00:00 ERROR Etiqa sync failed: upstream timeout" in out


def test_non_english_query_only_hits_repeats_keeps_error():
    text = (
        "\n".join(
            f"2026-10-17 10:{i:02d}:00 ИНФО Платёж {i} проведён"
            for i in range(40)
        )
        + "\n2026-10-17 11:00:00 ОШИБКА Не удалось списать средства: недостаточно средств на счёте 40817\n"
    )
    r = compress_context(
        text,
        "почему платёж не прошёл",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "недостаточно средств" in r.compressed_text
