import tameru.compress_context as cc


def _java_text():
    lines = []
    for i in range(50):
        lines.append(f"2026-10-18 06:20:{i:02d}.123 INFO  [worker-{i}] c.acme.sync.SyncJob - sync batch completed rows={i*7}")
    lines.append("2026-10-18 06:21:00.001 ERROR [worker-3] c.acme.sync.SyncJob - sync batch failed")
    lines.append("java.net.SocketTimeoutException: Read timed out")
    for i in range(12):
        lines.append(f"\tat c.acme.sync.Client{i}.call(Client{i}.java:{i+10})")
    for i in range(6):
        lines.append(f"2026-10-18 06:21:0{i}.123 INFO  [worker-{i}] c.acme.sync.SyncJob - sync batch completed rows={i*7}")
    return "\n".join(lines)


def _retry_text():
    lines = ["INFO start", "ERROR step failed: disk", "INFO retry 1/3", "ERROR step failed: disk"]
    for i in range(30):
        lines.append(f"INFO tick {i}")
    return "\n".join(lines)


def _info_text():
    return "\n".join(f"INFO line {i}" for i in range(40))


def run(text, query, **kw):
    return cc.compress_context(text, query, **kw)


def _assert_equal(a, b):
    assert a.compressed_text == b.compressed_text
    assert a.compression_risk == b.compression_risk
    assert a.fail_open == b.fail_open
    assert a.kept_tokens == b.kept_tokens
    assert a.original_tokens == b.original_tokens
    assert a.reasons == b.reasons
    assert a.keep_ratio == b.keep_ratio
    assert a.receipt == b.receipt


def _spy_finalize_reused_probe(monkeypatch):
    calls = []
    real = cc._finalize_reused_probe

    def wrapper(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(cc, "_finalize_reused_probe", wrapper)
    return calls


def test_java_generic_query(monkeypatch):
    text = _java_text()
    query = "what went wrong with the sync job"
    kw = dict(ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = run(text, query, **kw)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = run(text, query, **kw)
    _assert_equal(a, b)


def test_java_uninformative_query(monkeypatch):
    text = _java_text()
    query = "sync"
    kw = dict(ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = run(text, query, **kw)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = run(text, query, **kw)
    _assert_equal(a, b)


def test_retry_query(monkeypatch):
    text = _retry_text()
    query = "what happened"
    kw = dict(ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = run(text, query, **kw)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = run(text, query, **kw)
    _assert_equal(a, b)


def test_no_anchor_path(monkeypatch):
    text = _info_text()
    query = ""
    kw = dict(ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    a = run(text, query, **kw)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    b = run(text, query, **kw)
    _assert_equal(a, b)


def test_finalize_reused_probe_called_once(monkeypatch):
    calls = _spy_finalize_reused_probe(monkeypatch)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    run(
        _java_text(),
        "what went wrong with the sync job",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
    )
    assert len(calls) == 1


def test_finalize_reused_probe_not_called_when_flag_false(monkeypatch):
    calls = _spy_finalize_reused_probe(monkeypatch)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", False)
    run(
        _java_text(),
        "what went wrong with the sync job",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
    )
    assert len(calls) == 0


def test_finalize_reused_probe_called_with_ccr(monkeypatch, tmp_path):
    calls = _spy_finalize_reused_probe(monkeypatch)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    run(
        _java_text(),
        "what went wrong with the sync job",
        ccr=True,
        ccr_dir=tmp_path,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
    )
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_finalize_reused_probe_not_called_empty_query(monkeypatch):
    calls = _spy_finalize_reused_probe(monkeypatch)
    monkeypatch.setattr(cc, "_REUSE_PROBE_RESULT", True)
    run(
        _info_text(),
        "",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
    )
    assert len(calls) == 0
