from tameru.agent_formats import detect_test_runner, _classify_bundle_assets
from tameru.compress_context import compress_context


def _failed_text() -> str:
    return (
        "".join(
            f"asset chunk-{i}.js {100 + i * 7} KiB [emitted] [minimized] (name: chunk-{i})\n"
            for i in range(30)
        )
        + "\nERROR in ./src/pages/Checkout.tsx 12:0-41\n"
        + "Module not found: Error: Can't resolve './PaymentForm' in '/app/src/pages'\n"
        + "\nwebpack 5.90.0 compiled with 1 error in 8123 ms\n"
    )


def test_failed_build_keeps_error_lines_not_asset_lines() -> None:
    text = _failed_text()
    assert detect_test_runner(text) == "bundle_assets"

    lines = text.splitlines()
    keep = _classify_bundle_assets(lines)[0]

    assert sum(keep[:30]) == 0
    for index, line in enumerate(lines):
        if index >= 30 and line:
            assert keep[index] is True


def test_failed_build_compression_contains_error_and_is_small() -> None:
    text = _failed_text()
    compressed = compress_context(text, "", ccr=False, citations=False)

    assert "Checkout.tsx" in compressed.compressed_text
    assert "Can't resolve './PaymentForm'" in compressed.compressed_text
    assert "compiled with 1 error" in compressed.compressed_text
    assert len(compressed.compressed_text) < 0.25 * len(text)


def test_failed_build_keeps_flagged_asset_lines() -> None:
    asset_lines = [
        f"asset chunk-{i}.js {100 + i * 7} KiB [emitted] [minimized] (name: chunk-{i})\n"
        for i in range(30)
    ]
    asset_lines[3] = "asset chunk-3.js 121 KiB [emitted] [big] (name: chunk-3)\n"
    text = "".join(asset_lines) + (
        "\nERROR in ./src/pages/Checkout.tsx 12:0-41\n"
        "Module not found: Error: Can't resolve './PaymentForm' in '/app/src/pages'\n"
        "\nwebpack 5.90.0 compiled with 1 error in 8123 ms\n"
    )

    keep = _classify_bundle_assets(text.splitlines())[0]

    assert keep[3] is True
    assert sum(keep[:30]) == 1


def test_successful_build_keeps_first_two_and_largest_three_assets() -> None:
    text = (
        "".join(
            f"asset chunk-{i}.js {100 + i * 7} KiB [emitted] [minimized] (name: chunk-{i})\n"
            for i in range(30)
        )
        + "\nwebpack 5.90.0 compiled successfully in 8123 ms\n"
    )

    keep = _classify_bundle_assets(text.splitlines())[0]

    assert sum(keep[:30]) == 5
    for index in (0, 1, 27, 28, 29):
        assert keep[index] is True
    for index in range(30):
        if index not in (0, 1, 27, 28, 29):
            assert keep[index] is False
