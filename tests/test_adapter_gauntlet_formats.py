from tameru import format_adapters as adapters


def test_format_gauntlet_malformed_explicit_pipe_table():
    source = "not a table"
    result = adapters.adapt_format(source, "", format_name="markdown_table")
    assert not result.applied
    assert result.text == source


def test_format_gauntlet_yaml_outliers_preserve_directives():
    source = "%YAML 1.2\n---\n" + "\n---\n".join(["kind: Report\nstatus: ok"] * 6)
    result = adapters.adapt_format(source, "", format_name="yaml")
    assert not result.applied
    assert result.text == source
