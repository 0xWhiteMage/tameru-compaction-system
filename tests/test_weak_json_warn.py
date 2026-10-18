import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import _is_weak_failure_line, compress_context


def _unpack_compression(out):
    if isinstance(out, tuple):
        text = None
        fail_open = False
        for item in out:
            if isinstance(item, str) and text is None:
                text = item
            elif isinstance(item, bool) and fail_open is False:
                fail_open = item
            elif isinstance(item, int) and item in (0, 1) and fail_open is False:
                fail_open = bool(item)
        if text is not None:
            return text, fail_open

    if isinstance(out, dict):
        text = (
            out.get("text")
            or out.get("result")
            or out.get("output")
            or out.get("compacted")
            or out.get("compressed")
            or ""
        )
        fail_open = bool(out.get("fail_open", out.get("failed_open", False)))
        return text, fail_open

    for attr in ("text", "result", "output", "compacted", "compressed"):
        if hasattr(out, attr):
            text = getattr(out, attr)
            fail_open = bool(getattr(out, "fail_open", getattr(out, "failed_open", False)))
            return text, fail_open

    return str(out), False


def test_json_warn_failure_line_is_weak():
    line = (
        '{"ts": "09:00", "level": "warn", "msg": "replication failed", '
        '"node": "n4", "reason": "peer unreachable"}'
    )
    assert _is_weak_failure_line(line) is True


def test_json_warn_without_failure_word_is_not_weak():
    assert _is_weak_failure_line('{"level": "warn", "msg": "heartbeat"}') is False


def test_json_info_with_failure_word_is_not_weak():
    assert _is_weak_failure_line('{"level": "info", "msg": "replication failed"}') is False


def test_logfmt_warn_failure_line_is_weak():
    assert _is_weak_failure_line('level=warn msg="probe timeout"') is True


def test_json_warn_anchor_does_not_fail_open():
    lines = []
    for i in range(50):
        lines.append(
            json.dumps(
                {
                    "ts": f"08:{i:02d}",
                    "level": "info",
                    "msg": "heartbeat",
                    "node": f"n{i}",
                }
            )
        )

    lines.append(
        '{"ts": "09:00", "level": "warn", "msg": "replication failed", '
        '"node": "n4", "reason": "peer unreachable"}'
    )
    text = "\n".join(lines)

    r = compress_context(text, "", ccr=False, anchor_errors=True, citations=False)

    assert r.fail_open is False
    assert "peer unreachable" in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(text)
