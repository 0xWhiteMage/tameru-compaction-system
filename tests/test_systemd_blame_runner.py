import pytest

from tameru.agent_formats import (
    _classify_systemd_blame,
    _systemd_duration_seconds,
    detect_test_runner,
)
from tameru.compress_context import compress_context


def test_systemd_duration_seconds():
    assert _systemd_duration_seconds("1min 21.004s") == pytest.approx(81.004)
    assert _systemd_duration_seconds("412ms") == pytest.approx(0.412)
    assert _systemd_duration_seconds("87us") == pytest.approx(8.7e-05)


def _sample_text() -> str:
    return (
        "Startup finished in 2.1s (kernel) + 1min 34.2s (userspace) = 1min 36.3s\n"
        "1min 21.004s cloud-init.service\n"
        + "".join(f"{100 + (i * 37) % 800}ms unit-{i}.service\n" for i in range(40))
    )


def test_detect_and_compress_systemd_blame():
    text = _sample_text()
    assert detect_test_runner(text) == "systemd_blame"
    for query in ("", "what slows down boot"):
        out = compress_context(text, query, ccr=False, citations=False).compressed_text
        assert "1min 21.004s cloud-init.service" in out
        assert "Startup finished in" in out
        assert len(out) < 0.5 * len(text)


def test_classify_systemd_blame_keeps_slowest_units():
    text = _sample_text()
    lines = text.splitlines()
    keep, _, _ = _classify_systemd_blame(lines)
    kept = [line for line, is_kept in zip(lines, keep) if is_kept]
    assert len(kept) == 11

    cloud_init = "1min 21.004s cloud-init.service"
    unit_lines = [
        (100 + (i * 37) % 800, i, f"{100 + (i * 37) % 800}ms unit-{i}.service")
        for i in range(40)
    ]
    top_units = {line for _, _, line in sorted(unit_lines, key=lambda item: (-item[0], item[1]))[:9]}
    expected = {cloud_init, *top_units}
    kept_blame = kept[1:]
    assert kept_blame[0] == cloud_init
    assert set(kept_blame) == expected


def test_systemd_blame_negative_requires_ten_lines():
    text = "Startup finished in 2.1s\n" + "".join(f"{100 + i}ms unit-{i}.service\n" for i in range(9))
    assert detect_test_runner(text) != "systemd_blame"
