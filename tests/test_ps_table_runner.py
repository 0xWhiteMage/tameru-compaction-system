from tameru.agent_formats import detect_test_runner, _classify_ps_table
from tameru.compress_context import compress_context


def _eventlog() -> str:
    rows = "".join(
        f"   {9000 - i} Oct 21 0{i % 10}:{i:02d}  Information Service Control M...   1073748860 The Windows Update service entered the running state.\n"
        for i in range(40)
    )
    return (
        "\n   Index Time          EntryType   Source                 InstanceID Message\n"
        "   ----- ----          ---------   ------                 ---------- -------\n"
        + rows
        + "   8959 Oct 21 03:12  Error       Disk                   3221487627 The device, \\Device\\Harddisk1\\DR1, has a bad block.\n"
    )


def _services() -> str:
    rows = "".join(f"Running  Svc{i:<15d} Example Service {i}\n" for i in range(40))
    return (
        "\nStatus   Name               DisplayName\n"
        "------   ----               -----------\n"
        + rows
        + "Stopped  Spooler            Print Spooler\n"
    )


def test_eventlog_detect_and_compress():
    eventlog = _eventlog()
    assert detect_test_runner(eventlog) == "ps_table"
    out = compress_context(eventlog, "", ccr=False, citations=False).compressed_text
    assert "has a bad block" in out
    assert "EntryType" in out
    assert "-----" in out
    assert len(out) < 0.3 * len(eventlog)


def test_services_detect_and_compress():
    services = _services()
    assert detect_test_runner(services) == "ps_table"
    for query in ("", "which services are stopped"):
        out = compress_context(services, query, ccr=False, citations=False).compressed_text
        assert "Stopped  Spooler" in out
        assert len(out) < 0.4 * len(services)


def test_services_classify_keeps_expected_rows():
    services = _services()
    lines = services.splitlines()
    keep, _, _ = _classify_ps_table(lines)
    kept = [line for line, k in zip(lines, keep) if k and line.strip()]

    assert len(kept) == 5
    assert kept[0] == "Status   Name               DisplayName"
    assert kept[1] == "------   ----               -----------"
    assert kept[2] == f"Running  Svc{0:<15d} Example Service 0"
    assert kept[3] == f"Running  Svc{39:<15d} Example Service 39"
    assert kept[4] == "Stopped  Spooler            Print Spooler"


def test_ps_table_negatives():
    nine_rows = (
        "\nStatus   Name\n"
        "------   ----\n"
        + "".join(f"Running  Svc{i:<15d} Example Service {i}\n" for i in range(9))
    )
    assert detect_test_runner(nine_rows) != "ps_table"

    markdown_rule = (
        "\nTitle\n"
        "---\n"
        + "".join(f"row {i}\n" for i in range(10))
    )
    assert detect_test_runner(markdown_rule) != "ps_table"

    no_dash = (
        "\nStatus   Name\n"
        + "".join(f"Running  Svc{i:<15d} Example Service {i}\n" for i in range(10))
    )
    assert detect_test_runner(no_dash) != "ps_table"
