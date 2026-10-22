from tameru.agent_formats import detect_test_runner, _classify_pg_settings
from tameru.compress_context import compress_context


def _sample_text() -> str:
    return (
        "         name          |  setting  | unit |       source\n"
        "-----------------------+-----------+------+--------------------\n"
        + "".join(f" param_{i:<18}| {100 + i:<9} | kB   | default\n" for i in range(50))
        + " max_connections       | 500       |      | configuration file\n"
        + "".join(f" opt_{i:<20}| on        |      | default\n" for i in range(20))
        + " work_mem              | 262144    | kB   | session\n"
        "(72 rows)\n"
    )


def test_detect_and_compress() -> None:
    text = _sample_text()
    assert detect_test_runner(text) == "pg_settings"

    out = compress_context(text, "", ccr=False, citations=False).compressed_text
    assert "max_connections       | 500" in out
    assert "work_mem              | 262144" in out
    assert "source" in out
    assert "(72 rows)" in out
    assert len(out) < 0.4 * len(text)

    out = compress_context(text, "what is param_7 set to", ccr=False, citations=False).compressed_text
    assert "param_7 " in out


def test_classify_drops_default_rows() -> None:
    lines = _sample_text().splitlines()
    keep, _, _ = _classify_pg_settings(lines)
    assert sum(keep) == 5
    assert sum(not kept for kept in keep) == 70
    kept_lines = [line for line, kept in zip(lines, keep) if kept]
    assert any("max_connections" in line for line in kept_lines)
    assert any("work_mem" in line for line in kept_lines)
    assert kept_lines[-1] == "(72 rows)"
    assert all("default" not in line for line in kept_lines)


def test_negatives() -> None:
    no_source = (
        "         name          |  setting  | unit\n"
        "-----------------------+-----------+------\n"
        + "".join(f" param_{i:<18}| {100 + i:<9} | kB   \n" for i in range(50))
        + "(50 rows)\n"
    )
    assert detect_test_runner(no_source) != "pg_settings"

    low_default = (
        "         name          |  setting  | unit |       source\n"
        "-----------------------+-----------+------+--------------------\n"
        + "".join(f" def_{i:<18}| on        |      | default\n" for i in range(10))
        + "".join(f" non_{i:<18}| on        |      | session\n" for i in range(20))
        + "(30 rows)\n"
    )
    assert detect_test_runner(low_default) != "pg_settings"
