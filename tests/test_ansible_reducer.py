from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def _fixture_text() -> str:
    return (
        "PLAY [web] " + "*" * 60 + "\n"
        "\n"
        "TASK [Gathering Facts] " + "*" * 50 + "\n"
        + "\n".join(f"ok: [web{i}]" for i in range(12))
        + "\n"
        "\n"
        "TASK [deploy app] " + "*" * 55 + "\n"
        + "\n".join(f"changed: [web{i}]" for i in range(11))
        + "\n"
        'fatal: [web11]: UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh: connect to host web11 port 22: Connection timed out", "unreachable": true}\n'
        "\n"
        "PLAY RECAP " + "*" * 60 + "\n"
        + "\n".join(
            f"web{i}                      : ok=2    changed=1    unreachable=0    failed=0"
            for i in range(11)
        )
        + "\n"
        "web11                      : ok=1    changed=0    unreachable=1    failed=0\n"
    )


def test_detects_ansible_and_reduces_repeated_host_lines() -> None:
    text = _fixture_text()
    assert detect_test_runner(text) == "ansible"

    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text

    assert "UNREACHABLE" in compressed
    assert "Connection timed out" in compressed
    assert "web11                      : ok=1    changed=0    unreachable=1" in compressed
    assert "PLAY RECAP" in compressed
    assert "TASK [deploy app]" in compressed
    assert "ok: [web0]" in compressed
    assert "changed: [web0]" in compressed
    assert "changed: [web7]" not in compressed
    assert "web5                      : ok=2" not in compressed
    assert len(compressed) < 0.6 * len(text)


def test_keeps_failed_recap_row() -> None:
    text = (
        "PLAY [web] " + "*" * 60 + "\n"
        "TASK [deploy app] " + "*" * 55 + "\n"
        + "\n".join(f"changed: [web{i}]" for i in range(8))
        + "\n"
        "PLAY RECAP " + "*" * 60 + "\n"
        + "\n".join(
            f"web{i}                      : ok=2    changed=1    unreachable=0    failed=0"
            for i in (0, 1, 2, 4)
        )
        + "\n"
        "web3 : ok=1 changed=0 unreachable=0 failed=1\n"
    )

    compressed = compress_context(text, "", ccr=False, citations=False).compressed_text
    assert "web3 : ok=1 changed=0 unreachable=0 failed=1" in compressed


def test_short_single_task_not_detected() -> None:
    assert detect_test_runner("TASK [x] ***\n") is None


def test_many_ok_lines_single_failed_recap_not_detected() -> None:
    text = (
        "PLAY [web] " + "*" * 60 + "\n"
        "TASK [deploy app] " + "*" * 55 + "\n"
        + "\n".join(f"ok: [web{i:02d}]" for i in range(30))
        + "\n"
        "PLAY RECAP " + "*" * 60 + "\n"
        "web01 : ok=1 changed=0 unreachable=0 failed=1\n"
    )
    assert detect_test_runner(text) is None
