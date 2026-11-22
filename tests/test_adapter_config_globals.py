import configparser

from tameru.format_adapters import adapt_format


def test_ini_selection_preserves_inherited_defaults():
    text = "[DEFAULT]\ntimeout=7\n[needle]\nvalue=1\n[quiet]\nvalue=2"
    result = adapt_format(text, "needle", format_name="ini")
    parsed = configparser.ConfigParser()
    parsed.read_string(result.text)
    assert result.applied
    assert parsed.get("needle", "timeout") == "7"
    assert not parsed.has_section("quiet")


def test_toml_selection_preserves_root_assignments_and_comments():
    text = '# global settings\ntitle="original"\n\n[needle]\nvalue=1\n[quiet]\nvalue=2'
    result = adapt_format(text, "needle", format_name="ini")
    assert result.applied
    assert result.text.startswith('# global settings\ntitle="original"\n\n[needle]')


def test_defaults_do_not_turn_a_nonmatching_query_into_a_selection():
    text = "[DEFAULT]\ntimeout=7\n[alpha]\nvalue=1\n[quiet]\nvalue=2"
    assert adapt_format(text, "needle", format_name="ini").text == text


def test_empty_ini_is_unchanged():
    assert adapt_format("", "needle", format_name="ini").text == ""
