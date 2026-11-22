import pytest

from tameru.format_adapters import FormatLimits, adapt_format


CASES = [
    ("markdown", "# needle\nanswer\n# quiet\nother", 2, len("# needle\nanswer")),
    ("yaml", "needle:\n  value: yes\nquiet:\n  value: other", 4, len("  value: other")),
    ("xml", "<root>\n<row>needle</row>\n<row>quiet</row>\n</root>", 2, len("<row>needle</row>")),
    ("ini", "[needle]\nvalue=1\n[quiet]\nvalue=2", 2, len("[needle]\nvalue=1")),
    ("html", "<html>\n<body>\n<div>needle</div>\n<div>quiet</div>\n</body>\n</html>", 2, len("<div>needle</div>")),
    ("vertical", "n\ne\ne\nd\nl\ne\n\nq\nu\ni\ne\nt", 2, len("n\ne\ne\nd\nl\ne")),
]


@pytest.mark.parametrize("kind,text,count,size", CASES)
@pytest.mark.parametrize("bound", ["records", "chars"])
def test_line_adapters_decline_over_the_requested_limit(kind, text, count, size, bound):
    limits = FormatLimits(max_records=count - 1) if bound == "records" else FormatLimits(max_record_chars=size - 1)
    result = adapt_format(text, "needle", limits, format_name=kind)
    assert not result.applied
    assert result.text == text
    assert "limit" in result.reason


@pytest.mark.parametrize("kind,text,count,size", CASES)
def test_line_adapters_accept_exact_limit_boundaries(kind, text, count, size):
    result = adapt_format(text, "needle", FormatLimits(max_records=count, max_record_chars=size), format_name=kind)
    assert result.applied


@pytest.mark.parametrize("limits", [FormatLimits(max_records=1), FormatLimits(max_record_chars=1)])
def test_weak_query_yaml_document_outliers_obey_limits(limits):
    text = "\n---\n".join(f"name: worker-{i}\nstatus: healthy" for i in range(6))
    result = adapt_format(text, "", limits, format_name="yaml")
    assert not result.applied
    assert result.text == text
    assert "limit" in result.reason


def test_weak_query_yaml_document_outliers_accept_exact_limits():
    documents = [f"name: worker-{i}\nstatus: healthy" for i in range(6)]
    text = "\n---\n".join(documents)
    result = adapt_format(text, "", FormatLimits(max_records=6, max_record_chars=len(documents[0]) + 4), format_name="yaml")
    assert result.applied


@pytest.mark.parametrize("kind,text,count,size", CASES)
def test_empty_line_formats_are_unchanged_under_small_limits(kind, text, count, size):
    result = adapt_format("", "needle", FormatLimits(max_records=1, max_record_chars=1), format_name=kind)
    assert not result.applied
    assert result.text == ""
