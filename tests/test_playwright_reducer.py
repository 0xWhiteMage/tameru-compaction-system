from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context

passed = "".join(f"  \u2713  {i} [chromium] \u203a tests/page{i}.spec.ts:{i + 3}:5 \u203a page {i} loads (1.{i}s)\n" for i in range(1, 40))
text = "Running 40 tests using 4 workers\n\n" + passed + "  \u2718  40 [chromium] \u203a tests/cart.spec.ts:88:5 \u203a cart total updates (30.0s)\n\n  1) [chromium] \u203a tests/cart.spec.ts:88:5 \u203a cart total updates\n\n    Error: Timed out 5000ms waiting for expect(locator).toHaveText(expected)\n    Expected string: \"$42.00\"\n\n  1 failed\n  39 passed (1.2m)\n"


def test_detects_playwright():
    assert detect_test_runner(text) == "playwright"


def test_preprocess_keeps_failure_drops_passes():
    out = preprocess_test_output(text, "")
    assert "cart.spec.ts:88" in out
    assert "cart total updates" in out
    assert "1 failed" in out
    assert "39 passed" in out
    assert "page7.spec.ts" not in out
    assert "passed test lines omitted" in out
    assert len(out) < 0.3 * len(text)


def test_end_to_end_compress():
    for q in ("which test failed", ""):
        r = compress_context(text, q, ccr=False, citations=False)
        assert "cart.spec.ts:88" in r.compressed_text
        assert "cart total updates" in r.compressed_text


def test_flaky_pass_kept():
    text2 = text.replace("page 5 loads (1.5s)", "page 5 loads (1.5s) (retry #1)")
    assert text2 != text
    assert "(retry #1)" in preprocess_test_output(text2, "")


def test_not_detected_without_running_header():
    assert detect_test_runner(passed) is None
