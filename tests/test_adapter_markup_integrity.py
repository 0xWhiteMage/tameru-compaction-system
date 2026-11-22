import xml.etree.ElementTree as ET

import pytest

from tameru.format_adapters import adapt_format


@pytest.mark.parametrize("root", ["<root invalid>", '<root a="1" a="2">', "<root p:a='1'>"])
def test_invalid_xml_root_fails_open(root):
    text = f"{root}\n<row>needle</row>\n<row>quiet</row>\n</root>"
    result = adapt_format(text, "needle", format_name="xml")
    assert not result.applied
    assert not result.structurally_valid
    assert result.text == text


def test_malformed_xml_child_is_not_a_safe_multiline_decline():
    text = "<root>\n<row>needle</bad>\n<row>quiet</row>\n</root>"
    result = adapt_format(text, "needle", format_name="xml")
    assert not result.structurally_valid
    assert result.text == text


def test_valid_multiline_xml_child_remains_a_safe_decline():
    text = "<root>\n<row>\nneedle\n</row>\n<row>quiet</row>\n</root>"
    result = adapt_format(text, "needle", format_name="xml")
    assert not result.applied
    assert result.structurally_valid
    assert result.text == text


def test_valid_xml_is_still_selected():
    text = '<root a="1">\n<row>needle</row>\n<row>quiet</row>\n</root>'
    result = adapt_format(text, "needle", format_name="xml")
    assert result.applied
    assert ET.fromstring(result.text).attrib == {"a": "1"}


@pytest.mark.parametrize("text", [
    "<html>\n<body>\n<div>needle</div>\n<div>quiet</div>\n</html>\n</body>",
    "<html>\n<body>\n<div>needle</div>\n</body>\n<div>quiet</div>\n</html>",
    "<html>\n<body>\n<body>\n<div>needle</div>\n<div>quiet</div>\n</body>\n</body>\n</html>",
])
def test_invalid_html_wrapper_order_fails_open(text):
    result = adapt_format(text, "needle", format_name="html")
    assert not result.applied
    assert not result.structurally_valid
    assert result.text == text


def test_valid_html_wrappers_and_doctype_are_preserved():
    text = "<!doctype html>\n<html>\n<body>\n<div>needle</div>\n<div>quiet</div>\n</body>\n</html>"
    result = adapt_format(text, "needle", format_name="html")
    assert result.applied
    assert result.text == "<!doctype html>\n<html>\n<body>\n<div>needle</div>\n</body>\n</html>"


@pytest.mark.parametrize("kind", ["xml", "html"])
def test_empty_markup_is_unchanged(kind):
    assert adapt_format("", "needle", format_name=kind).text == ""
