import pytest

from tameru.format_adapters import FormatLimits, adapt_format


def test_ndjson_field_limit_is_enforced_without_report_routing():
    text = '{"needle":1,"a":2}\n{"quiet":2,"b":3}'
    result = adapt_format(text, "needle", FormatLimits(max_fields=1), format_name="ndjson", allow_reports=False)
    assert not result.applied
    assert not result.structurally_valid
    assert result.text == text


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_ndjson_rejects_nonfinite_constants_without_report_routing(constant):
    text = '{"needle":' + constant + '}\n{"quiet":2}'
    result = adapt_format(text, "needle", format_name="ndjson", allow_reports=False)
    assert not result.applied
    assert not result.structurally_valid
    assert result.text == text


def test_ndjson_nested_objects_obey_field_limits():
    text = '{"needle":{"a":1,"b":2}}\n{"quiet":2}'
    assert not adapt_format(text, "needle", FormatLimits(max_fields=1), format_name="ndjson", allow_reports=False).applied


def test_ndjson_exact_field_limit_preserves_record_bytes():
    text = '{"needle": 1, "a":2}\n{"quiet":2}'
    result = adapt_format(text, "needle", FormatLimits(max_fields=2), format_name="ndjson", allow_reports=False)
    assert result.text == '{"needle": 1, "a":2}'
    assert result.applied


def test_empty_ndjson_is_unchanged():
    assert adapt_format("", "needle", format_name="ndjson", allow_reports=False).text == ""


def test_null_records_keep_the_existing_safe_decline():
    text = 'null\n{"needle":1}\n{"quiet":2}'
    result = adapt_format(text, "needle", format_name="ndjson", allow_reports=False)
    assert not result.applied
    assert result.text == text
