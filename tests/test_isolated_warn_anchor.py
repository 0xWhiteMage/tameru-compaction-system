from tameru.compress_context import _anchor_regions, compress_context


def test_isolated_warn_anchor_basic():
    lines = [f"2026-10-18 08:20:{i:02d} INFO cache: evicted {i * 3} keys" for i in range(50)]
    lines.append("2026-10-18 08:21:00 WARN cache: memory usage at 93% of limit")
    lines.extend(f"2026-10-18 08:22:{i:02d} INFO cache: evicted {i * 7} keys" for i in range(6))
    text = "\n".join(lines)

    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert any("93%" in region for region in regions)

    result = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert not result.fail_open
    assert "93%" in result.compressed_text
    assert len(result.compressed_text) < 0.3 * len(text)


def test_isolated_warn_guard_c_too_many_warn_lines():
    lines = []
    for i in range(45):
        if i % 3 == 2:
            lines.append(f"WARN sync: lag {i}s on shard s{i}")
        else:
            lines.append(f"INFO sync: ok {i}")
    text = "\n".join(lines)

    assert _anchor_regions(text, 8) == []


def test_isolated_warn_guard_b_not_leveled_log():
    lines = ["The system was started in the morning." for _ in range(29)]
    lines.append("WARNING: do not run this in production")
    text = "\n".join(lines)

    assert _anchor_regions(text, 8) == []


def test_isolated_warn_guard_a_too_few_lines():
    lines = [f"INFO app: step {i}" for i in range(9)]
    lines.append("WARN app: slow")
    text = "\n".join(lines)

    assert _anchor_regions(text, 8) == []


def test_isolated_warn_guard_d_repeated_warn_template():
    lines = [f"INFO pool: ok {i}" for i in range(40)]
    lines.append("WARN pool: size 10 reached")
    lines.append("WARN pool: size 12 reached")
    text = "\n".join(lines)

    assert _anchor_regions(text, 8) == []


def test_error_anchor_precedes_isolated_warn():
    lines = [f"INFO app: ok {i}" for i in range(20)]
    lines.append("ERROR db down")
    lines.extend(f"INFO app: ok {i}" for i in range(20, 30))
    lines.append("WARN disk 91%")
    lines.extend(f"INFO app: ok {i}" for i in range(30, 40))
    text = "\n".join(lines)

    regions = _anchor_regions(text, 8)
    assert any("db down" in region for region in regions)
    assert not any("91%" in region for region in regions)
