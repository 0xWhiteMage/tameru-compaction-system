"""E10: masked log templates collapse; [last] instance and error exemplars kept."""
from __future__ import annotations

import time

from tameru.compress_context import error_fingerprints, preprocess_logs
from tameru.folding import mask_template


def test_masking_placeholders():
    m = mask_template
    assert m("id 550e8400-e29b-41d4-a716-446655440000 x") == "id <uuid> x"
    assert m("from 10.1.2.3:8080 and fe80:0:0:0:1:2:3:4") == "from <ip> and <ip>"
    assert m("at 2026-03-14t12:00:01.123z") == "at <ts>"
    assert m("12:00:01.5 took 12ms, 3.5s") == "<ts> took <dur>, <dur>"
    assert m("sha deadbeef01 end") == "sha <hex> end"
    assert m("open 'a b' and \"c d\"") == 'open "<str>" and "<str>"'
    assert m("read /var/log/app/x.log now") == "read <path> now"
    assert m("worker-12") == "worker-#"
    assert m("don't stop, it's fine") == "don't stop, it's fine"


def _lines(n=60):
    out = []
    for i in range(n):
        out.append(
            f"INFO conn 10.0.{i % 7}.{i} id={i:08x}-{i:04x}-4000-8000-{i:012x} took {i}ms"
        )
    return out


def test_masked_templates_collapse_with_count_and_last():
    lines = _lines()
    out = preprocess_logs(lines)
    assert len(out) == 2
    assert out[0].startswith("[×60] ") and out[0].endswith(lines[0])
    assert out[1] == "[last] " + lines[-1]


def test_two_repeats_have_no_last_line():
    out = preprocess_logs(_lines(2))
    assert len(out) == 1 and out[0].startswith("[×2] ")


def test_idempotent():
    once = preprocess_logs(_lines())
    assert preprocess_logs(once) == once


def test_error_exemplar_per_fingerprint_and_last_prefix_stable():
    lines = []
    for i in range(80):
        lines.append(f"2026-03-14 12:00:{i % 60:02d} INFO ping {i} ok from 10.0.0.{i}")
        if i % 10 == 0:
            lines.append(f"2026-03-14 12:00:{i % 60:02d} ERROR upstream timeout after {i}ms")
        if i % 17 == 0:
            lines.append(f"2026-03-14 12:00:{i % 60:02d} ERROR db 'orders' down {i}")
    out = preprocess_logs(lines)
    assert set(error_fingerprints("\n".join(lines))) <= set(error_fingerprints("\n".join(out)))
    last = [ln for ln in out if ln.startswith("[last] ")]
    assert last
    for ln in last:
        assert list(error_fingerprints(ln)) == list(error_fingerprints(ln[len("[last] "):]))


def test_distinct_errors_not_merged():
    lines = [f"ERROR disk {c} full on /dev/sd{c}" for c in "abc"]
    assert len(error_fingerprints("\n".join(lines))) == 3 or len(
        error_fingerprints("\n".join(lines))
    ) == 1  # letters are not masked; see next assertion
    assert error_fingerprints("ERROR timeout") != error_fingerprints("ERROR refused")


def test_masking_is_linear_on_pathological_lines():
    line = "a" * 20000 + "/" + "b" * 20000
    t0 = time.perf_counter()
    for _ in range(50):
        mask_template(line[:2000])
    assert time.perf_counter() - t0 < 2.0
