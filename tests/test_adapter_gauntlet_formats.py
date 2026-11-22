from tameru import format_adapters as adapters


def test_format_gauntlet_malformed_explicit_pipe_table():
    source = "not a table"
    result = adapters.adapt_format(source, "", format_name="markdown_table")
    assert not result.applied
    assert result.text == source
