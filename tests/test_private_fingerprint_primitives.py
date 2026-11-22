import inspect
import re

from tameru import folding
from tameru._fingerprint_patterns import _HEXRUN_RE, _UUID_RE
from tameru.agent_formats import _ENV_DIGITS_RE
from tameru.compress_context import (
    _DIGITS_RE,
    _counterfactual_overlap_ambiguity,
    _summary_anchor_region,
)


def test_fingerprint_paths_share_the_same_immutable_patterns():
    assert folding._M_UUID is _UUID_RE
    assert folding._M_HEX is _HEXRUN_RE
    assert folding._M_DIGITS is _DIGITS_RE is _ENV_DIGITS_RE


def test_shared_digit_pattern_keeps_unicode_semantics():
    for text in ("", "no digits", "id-123", "١٢ and １２", "a123b456"):
        assert _DIGITS_RE.sub("#", text) == re.sub(r"\d+", "#", text)


def test_shared_hex_and_uuid_patterns_keep_case_and_boundaries():
    text = "00112233-aabb-ccdd-eeff-001122334455 AABBCC aabbcc 12345"
    assert _UUID_RE.findall(text) == ["00112233-aabb-ccdd-eeff-001122334455"]
    assert _HEXRUN_RE.findall(text) == re.findall(r"[0-9a-f]{6,}", text)


def test_private_helpers_drop_only_unused_arguments():
    assert list(inspect.signature(_summary_anchor_region).parameters) == ["line"]
    assert _summary_anchor_region(" INFO 20/40 tasks done ") == "20/40 tasks done"
    assert _summary_anchor_region("") is None
    parameters = inspect.signature(_counterfactual_overlap_ambiguity).parameters
    assert "log_dir" not in parameters
    assert "pin_patterns" not in parameters
    assert not _counterfactual_overlap_ambiguity([], set(), query="")
