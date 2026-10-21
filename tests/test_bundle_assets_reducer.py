from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def test_vite_bundle_assets_reducer() -> None:
    asset_lines = [
        f"dist/assets/page{i}-{i:04x}.js   {10 + i}.12 kB │ gzip: {3 + i}.40 kB"
        for i in range(30)
    ]
    text = (
        "vite v5.4.2 building for production...\n"
        "transforming...\n"
        "✓ 812 modules transformed.\n"
        "rendering chunks...\n"
        + "\n".join(asset_lines)
        + "\n"
        "dist/assets/vendor-9f8e7d.js   1,284.55 kB │ gzip: 402.11 kB\n"
        "\n"
        "(!) Some chunks are larger than 500 kB after minification.\n"
        "✓ built in 9.81s\n"
    )

    assert detect_test_runner(text) == "bundle_assets"
    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text

    assert "vendor-9f8e7d.js" in compressed
    assert "larger than 500 kB" in compressed
    assert "✓ built in 9.81s" in compressed
    assert "page0-" in compressed
    assert "page10-" not in compressed
    assert len(compressed) < 0.5 * len(text)


def test_webpack_bundle_assets_reducer() -> None:
    lines = [
        f"asset chunk{i}.js {20 + i}.5 KiB [emitted] [immutable] (name: c{i})"
        for i in range(12)
    ]
    lines.append("asset main.js 1.2 MiB [emitted] [immutable] [big] (name: main)")
    lines.append(
        "WARNING in asset size limit: The following asset(s) exceed the recommended size limit (244 KiB)."
    )
    lines.append("webpack 5.94.0 compiled with 1 warning in 4210 ms")
    text = "\n".join(lines)

    assert detect_test_runner(text) == "bundle_assets"
    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text

    assert "main.js 1.2 MiB" in compressed
    assert "asset size limit" in compressed


def test_esbuild_bundle_assets_reducer() -> None:
    lines = [f"  dist/chunk-{i:02d}.js  {i + 1}.3kb" for i in range(10)]
    lines.append("  dist/out.js      1.2mb ⚠️")
    lines.append("⚡ Done in 41ms")
    text = "\n".join(lines)

    assert detect_test_runner(text) == "bundle_assets"
    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text

    assert "dist/out.js" in compressed


def test_bundle_assets_not_triggered() -> None:
    lines = [
        f"dist/assets/page{i}-{i:04x}.js   {10 + i}.12 kB │ gzip: {3 + i}.40 kB"
        for i in range(5)
    ]
    text = "\n".join(lines)
    assert detect_test_runner(text) != "bundle_assets"

    prose = "The bundle is about 12 kB after compression."
    assert detect_test_runner(prose) != "bundle_assets"
