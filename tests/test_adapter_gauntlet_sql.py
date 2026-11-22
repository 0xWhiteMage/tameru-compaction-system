from tameru.format_adapters import adapt_format


def test_sql_gauntlet_nested_comment_declines():
    # Some supported SQL dialects nest block comments and others do not.
    source = "/* outer /* inner */ fake-log; needle-42; */\nSELECT 'ordinary';"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert not result.applied
    assert result.text == source
