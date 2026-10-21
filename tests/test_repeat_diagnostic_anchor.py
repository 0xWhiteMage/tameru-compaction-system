from tameru.compress_context import _anchor_regions, compress_context


def test_tsc_repeat_diagnostic_anchor_regions_and_compression():
    warnings = [
        f"src/legacy/file{i}.ts({100 + i * 13},5): warning TS6133: 'unused{i}' is declared but its value is never read."
        for i in range(80)
    ]
    errors = [
        "src/services/billing.ts(112,7): error TS2322: Type 'string | undefined' is not assignable to type 'string'.",
        "src/services/billing.ts(140,19): error TS2339: Property 'currency' does not exist on type 'Invoice'.",
    ]
    lines = warnings + errors + ["", "Found 2 errors in the same file, starting at: src/services/billing.ts:112"]
    text = "\n".join(lines)

    regions = _anchor_regions(text, 8)
    for region in regions:
        assert region.count("TS6133") <= 2

    compressed = compress_context(text, "", ccr=False, citations=False, anchor_errors=True).compressed_text
    assert "src/services/billing.ts(112,7): error TS2322" in compressed
    assert "src/services/billing.ts(140,19): error TS2339" in compressed
    assert len(compressed) < 0.3 * len(text)



def test_python_traceback_region_contains_error():
    lines = [f"INFO {i}" for i in range(10)] + [
        "Traceback (most recent call last):",
        '  File "a.py", line 3, in f',
        "    g()",
        "ValueError: bad",
    ]
    text = "\n".join(lines)
    regions = _anchor_regions(text, 8)
    assert any("ValueError: bad" in region for region in regions)
