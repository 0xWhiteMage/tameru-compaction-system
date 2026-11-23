import pytest

from tameru.compress_context import compress_context


@pytest.mark.parametrize("level", ["WARN", "ERROR"])
def test_structured_anchor_depth_failure_is_verbatim_noop(level):
    record = (
        '{"level":"' + level + '","message":"capacity notice","detail":'
        + "[" * 10_000 + "0" + "]" * 10_000 + "}"
    )
    original = "INFO background sync complete\n" * 200 + record

    result = compress_context(original, "", anchor_errors=True, ccr=False)

    assert result.compressed_text == original
    assert result.fail_open
