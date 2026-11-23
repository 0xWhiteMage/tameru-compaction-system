from tameru.format_adapters import adapt_format


def test_sql_gauntlet_nested_comment_declines():
    # Some supported SQL dialects nest block comments and others do not.
    source = "/* outer /* inner */ fake-log; needle-42; */\nSELECT 'ordinary';"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert not result.applied
    assert result.text == source


def test_sql_gauntlet_bracketed_identifier_is_kept_whole():
    target = "SELECT [prefix; needle-42]]suffix] FROM logs;"
    source = f"SELECT label FROM baseline;\n{target}"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert result.applied
    assert result.text == target


def test_sql_gauntlet_executable_comment_declines():
    source = "/*!40101 SET @mode = 'strict' */;\nSELECT 'needle-42';"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert not result.applied
    assert result.text == source


def test_sql_gauntlet_client_commands_decline():
    source = "\\connect archive\nSELECT 'unrelated';\nSELECT 'needle-42';"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert not result.applied
    assert result.text == source


def test_sql_gauntlet_go_batches_decline():
    source = "SELECT 'ordinary';\r\n go 2 -- repeat batch\r\nSELECT 'needle-42';"
    result = adapt_format(source, "needle-42", format_name="sql")
    assert not result.applied
    assert result.text == source


def test_sql_gauntlet_custom_statement_delimiter_declines():
    source = (
        "SELECT 'ordinary';\n"
        "DELIMITER //\n"
        "CREATE PROCEDURE needle_42() BEGIN\nSELECT 1;\nEND//\n"
        "DELIMITER ;\n"
        "SELECT 'unrelated';"
    )
    result = adapt_format(source, "needle_42", format_name="sql")
    assert not result.applied
    assert result.text == source


def test_sql_gauntlet_directive_text_in_literal_is_not_a_command():
    target = "SELECT '\nDELIMITER //\nneedle-42';"
    result = adapt_format("SELECT 'ordinary';\n" + target, "needle-42", format_name="sql")
    assert result.applied
    assert result.text == target
