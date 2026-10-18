import json
from pathlib import Path

import tameru.compress_context as cc


def _java_case():
    lines = []
    for i in range(50):
        lines.append(
            f"2026-10-18 06:20:{i:02d}.123 INFO  [worker-{i % 4}] "
            "c.acme.sync.SyncJob - sync batch completed rows=1200"
        )
    lines.append("2026-10-18 06:20:50.900 ERROR [worker-1] c.acme.sync.SyncJob - sync batch failed")
    lines.append("java.net.SocketTimeoutException: Read timed out")
    for i in range(12):
        lines.append(f"\tat c.acme.sync.Client{i}.call(Client{i}.java:{40 + i})")
    for i in range(6):
        lines.append(
            f"2026-10-18 06:20:5{i}.000 INFO  [worker-{i % 4}] "
            "c.acme.sync.SyncJob - sync batch completed rows=1200"
        )
    return "\n".join(lines) + "\n"


QUERY = "what went wrong with the sync job"
COMMON = dict(
    query=QUERY,
    anchor_errors=True,
    citations=False,
    inline_short_gaps=True,
)


def _record_names(d: Path):
    return sorted(p.name for p in d.iterdir())


def _load_record(d: Path):
    files = list(d.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_reuse_ccr_matches_full(tmp_path, monkeypatch):
    text = _java_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = cc.compress_context(text, ccr=True, ccr_dir=dir_a, **COMMON)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = cc.compress_context(text, ccr=True, ccr_dir=dir_b, **COMMON)

    assert "[CC-Retrieve:" in a.compressed_text
    assert a.compressed_text == b.compressed_text
    assert a.compression_risk == b.compression_risk
    assert a.fail_open == b.fail_open
    assert a.kept_tokens == b.kept_tokens
    assert a.keep_ratio == b.keep_ratio
    assert a.reasons == b.reasons
    assert a.receipt == b.receipt

    assert a.ccr["hash"] == b.ccr["hash"]
    assert Path(b.ccr["path"]).name == Path(a.ccr["path"]).name
    assert Path(b.ccr["path"]).exists()

    assert _record_names(dir_a) == _record_names(dir_b)
    assert len(list(dir_a.glob("*.json"))) == 1
    assert len(list(dir_b.glob("*.json"))) == 1
    assert not list(dir_a.glob(".ccr-*"))
    assert not list(dir_b.glob(".ccr-*"))

    ra, rb = _load_record(dir_a), _load_record(dir_b)
    for key in ("stored_at",):
        ra.pop(key, None)
        rb.pop(key, None)
    assert ra == rb


def test_ccr_store_called_once_per_call(tmp_path, monkeypatch):
    text = _java_case()
    calls = []
    real_store = cc._ccr_store

    def spy(caller_text, ccr_dir):
        calls.append(1)
        return real_store(caller_text, ccr_dir)

    monkeypatch.setattr(cc, "_ccr_store", spy)

    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    cc.compress_context(text, ccr=True, ccr_dir=tmp_path / "a", **COMMON)
    assert len(calls) == 1

    calls.clear()
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    cc.compress_context(text, ccr=True, ccr_dir=tmp_path / "b", **COMMON)
    assert len(calls) == 1


def test_reuse_happens_with_ccr_on(tmp_path, monkeypatch):
    text = _java_case()
    calls = []
    real_finalize = cc._finalize_reused_probe

    def spy(res, query_as_given, anchor_lines):
        calls.append(1)
        return real_finalize(res, query_as_given, anchor_lines)

    monkeypatch.setattr(cc, "_finalize_reused_probe", spy)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    cc.compress_context(text, ccr=True, ccr_dir=tmp_path / "b", **COMMON)
    assert len(calls) == 1


def test_auto_strategy_stores_once(tmp_path, monkeypatch):
    text = _java_case()
    calls = []
    real_store = cc._ccr_store

    def spy(caller_text, ccr_dir):
        calls.append(1)
        return real_store(caller_text, ccr_dir)

    monkeypatch.setattr(cc, "_ccr_store", spy)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    result = cc.compress_context(
        text, ccr=True, ccr_dir=tmp_path / "a", strategy="auto", **COMMON
    )
    assert len(calls) == 1
    assert len(list((tmp_path / "a").glob("*.json"))) == 1
    assert not list((tmp_path / "a").glob(".ccr-*"))
    assert Path(result.ccr["path"]).exists()


def test_store_failure_falls_through(tmp_path, monkeypatch):
    text = _java_case()

    def boom(caller_text, ccr_dir):
        raise OSError("disk full")

    monkeypatch.setattr(cc, "_ccr_store", boom)

    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = cc.compress_context(text, ccr=True, ccr_dir=tmp_path / "a", **COMMON)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = cc.compress_context(text, ccr=True, ccr_dir=tmp_path / "b", **COMMON)

    assert "[CC-Retrieve:" not in a.compressed_text
    assert a.ccr is None
    assert b.compressed_text == a.compressed_text
    assert b.ccr is None
    assert b.compression_risk == a.compression_risk
    assert b.fail_open == a.fail_open
    assert b.kept_tokens == a.kept_tokens
    assert b.keep_ratio == a.keep_ratio
    assert b.reasons == a.reasons
    assert b.receipt == a.receipt
