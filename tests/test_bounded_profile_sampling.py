import json

import pytest

from tameru import format_adapters, industrial, unicode_profile


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("limit", [0, 1, 6, 32, 128])
def test_bounded_lines_match_splitlines_without_stripping_records(separator, limit):
    text = separator.join(["", " \t", "  α  ", "\u2000{}\u2000", "β", ""]) * 50
    expected = [line for line in text.splitlines() if line.strip()][:limit]
    assert unicode_profile._sample_nonblank_lines(text, limit) == expected


def test_empty_profile_sample():
    assert unicode_profile._sample_nonblank_lines("", 32) == []
    assert not unicode_profile._looks_vertical_ocr("")


@pytest.mark.parametrize("text", ["", "a", "a\nb", '{"a":1}\n{"b":2}', '\u2000{"a":1}\nnull', "\n".join(['{"a":1}'] * 40)])
def test_ndjson_detection_matches_original_sample_rules(text):
    lines = [line for line in text.splitlines() if line.strip()]
    expected = False
    if len(lines) >= 2:
        candidates = sum(line.lstrip().startswith(("{", "[")) for line in lines[:32])
        parsed = sum(format_adapters._json_loads(line) is not None for line in lines[:32])
        expected = candidates >= max(2, min(len(lines), 32) // 2) and parsed >= 1
    assert format_adapters._looks_ndjson(text) == expected


def test_vertical_probe_consumes_at_most_three_graphemes_per_line(monkeypatch):
    consumed = []

    def clusters(line):
        for i in range(100):
            assert i < 3
            consumed.append(i)
            yield "α"

    monkeypatch.setattr(unicode_profile, "iter_graphemes", clusters)
    assert not unicode_profile._looks_vertical_ocr("\n".join(["α" * 100] * 6))
    assert len(consumed) == 18


@pytest.mark.parametrize("text", ["ascii", "α\u202e\ud800", "a\nb\nc\nd\ne\nf"])
def test_complete_profile_does_not_repeat_the_safety_scan(text, monkeypatch):
    def unexpected(value):
        raise AssertionError("complete profile was scanned twice")

    monkeypatch.setattr(industrial, "unicode_safety_counts", unexpected)
    result = industrial._profile_input(text)
    expected = unicode_profile.profile_text(text)
    assert (result.bidi_controls, result.bidi_overrides, result.malformed_surrogates) == (
        expected.bidi_controls, expected.bidi_overrides, expected.malformed_surrogates
    )


def test_truncated_profile_still_scans_safety_in_the_omitted_middle(monkeypatch):
    text = "a" * 20 + "\u202e\ud800" + "b" * 20
    scans = []
    real_scan = industrial.unicode_safety_counts

    def spy(value):
        scans.append(value)
        return real_scan(value)

    monkeypatch.setattr(industrial, "unicode_safety_counts", spy)
    result = industrial._profile_input(text, industrial.IndustrialLimits(max_profile_chars=4))
    assert scans == [text]
    assert result.profile_truncated
    assert (result.bidi_controls, result.bidi_overrides, result.malformed_surrogates) == (1, 1, True)


def test_ocr_sampling_matches_original_grapheme_predicate():
    for lines in (["α"] * 5, ["α"] * 6, ["👩‍💻", "á", "αβ"] * 50, ["αβγ"] * 6):
        text = "\n".join(lines)
        expected = len(lines) >= 6 and sum(len(unicode_profile.graphemes(line)) <= 2 for line in lines[:128]) / min(len(lines), 128) >= 0.8
        assert unicode_profile._looks_vertical_ocr(text) == expected
        json.dumps(industrial._profile_input(text).to_dict())
