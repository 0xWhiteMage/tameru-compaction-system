from tameru.compress_context import compress_context


def test_collapse_split_error_line():
    text = (
        "\n".join(
            f"src/legacy/file{i}.ts(1{i:03d},5): warning TS6133: 'unused{i}' is declared but its value is never read."
            for i in range(80)
        )
        + "\nsrc/services/billing.ts(112,7): error TS2322: Type 'string | undefined' is not assignable to type 'string'."
        + "\nsrc/services/billing.ts(140,19): error TS2339: Property 'currency' does not exist on type 'Invoice'."
        + "\n\nFound 2 errors in the same file, starting at: src/services/billing.ts:112"
    )

    for query in ("", "fix the typescript compile errors"):
        r = compress_context(
            text,
            query,
            ccr=False,
            citations=False,
            inline_short_gaps=True,
            min_savings_ratio=0.1,
            anchor_errors=True,
            prose_brief=True,
        )
        assert "billing.ts(112,7): error TS2322" in r.compressed_text
        assert "billing.ts(140,19): error TS2339" in r.compressed_text
        assert len(r.compressed_text) < len(text) * 0.12
