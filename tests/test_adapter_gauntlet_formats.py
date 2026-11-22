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
