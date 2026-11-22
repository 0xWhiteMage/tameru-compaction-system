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


def test_format_gauntlet_yaml_outliers_keep_sequence_value():
    common = "kind: Job\nargs:\n  - ready"
    unusual = "kind: Job\nargs:\n  - retry"
    source = "\n---\n".join([common] * 5 + [unusual])
    result = adapters.adapt_format(source, "", format_name="yaml")
    assert result.applied
    assert unusual in result.text
    assert result.kept_records == 2


def test_format_gauntlet_yaml_commented_document_markers():
    first = "--- # first\nkind: Job\nmetadata:\n  name: ordinary\nspec:\n  enabled: true"
    target = "--- # second\nkind: Job\nmetadata:\n  name: needle-42\nspec:\n  enabled: false"
    result = adapters.adapt_format(f"{first}\n{target}", "needle-42", format_name="yaml")
    assert result.applied
    assert result.text == target


def test_format_gauntlet_yaml_subtree_preserves_literal_block_scalar():
    source = "config: |-\n  # literal data\n  needle-42\nordinary: absent"
    result = adapters.adapt_format(source, "needle-42", format_name="yaml")
    assert not result.applied
    assert result.text == source


def test_format_gauntlet_yaml_keeps_parent_with_inline_comment():
    source = "settings: # operating parameters\n  endpoint: needle-42\nordinary: absent"
    result = adapters.adapt_format(source, "needle-42", format_name="yaml")
    assert result.applied
    assert result.text == "settings: # operating parameters\n  endpoint: needle-42"


def test_format_gauntlet_xml_detection_does_not_parse_a_dtd(monkeypatch):
    source = "<!DOCTYPE root>\n<root>\n<item>needle-42</item>\n</root>"

    def unexpected_parser(text):
        raise AssertionError("XML with a DTD must not reach the parser")

    monkeypatch.setattr(adapters.ET, "fromstring", unexpected_parser)
    result = adapters.adapt_format(source, "needle-42", allow_reports=False)
    assert result.format == "xml"
    assert not result.applied
    assert result.text == source


def test_format_gauntlet_pipe_table_treats_quotes_as_literal():
    target = '| "needs attention | warning |'
    source = "\n".join(["| state | level |", "|---|---|"] + ["| normal | ok |"] * 25 + [target])
    result = adapters.adapt_format(source, "", format_name="markdown_table")
    assert result.applied
    assert target in result.text
    assert result.kept_records == 1


def test_format_gauntlet_csv_treats_midfield_quote_as_literal():
    target = 'needle-42,displayed as "production'
    source = f"id,note\nordinary,backup\n{target}\nother,test"
    result = adapters.adapt_format(source, "needle-42")
    assert result.format == "csv"
    assert result.applied
    assert result.text == f"id,note\n{target}"


def test_format_gauntlet_pipe_table_treats_escaped_pipe_as_data():
    target = r"| connection \| replica | warning |"
    source = "\n".join(["| state | level |", "|---|---|"] + ["| normal | ok |"] * 25 + [target])
    assert adapters.detect_format(source) == "markdown_table"
    result = adapters.adapt_format(source, "")
    assert result.applied
    assert target in result.text
    assert result.kept_records == 1
