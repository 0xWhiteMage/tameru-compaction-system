import tameru.compress_context as cc


def _build_log() -> str:
    lines = [
        f"2026-10-18 06:20:{i:02d}.123 INFO  [worker-{i % 5}] c.acme.sync.SyncJob - sync batch completed rows={i}"
        for i in range(50)
    ]
    lines.append("2026-10-18 06:21:00.001 ERROR [worker-3] c.acme.sync.SyncJob - sync batch failed")
    lines.append("java.net.SocketTimeoutException: Read timed out")
    lines.extend(f"\tat c.acme.sync.Client{i}.call(Client{i}.java:{i})" for i in range(12))
    lines.extend(
        f"2026-10-18 06:21:01.{i:03d} INFO  [worker-{i % 5}] c.acme.sync.SyncJob - sync batch completed rows={i}"
        for i in range(6)
    )
    return "\n".join(lines)


def _is_fail_open(result) -> bool:
    for name in ("fail_open", "is_fail_open"):
        value = getattr(result, name, None)
        if value is None:
            continue
        if callable(value):
            value = value()
        return bool(value)
    return False


def test_anchor_probe_order(monkeypatch):
    text = _build_log()
    query = "what went wrong with the sync job"
    real = cc.compress_context
    calls = []

    def spy(text_arg, query_arg="", **kw):
        calls.append(query_arg)
        return real(text_arg, query_arg, **kw)

    monkeypatch.setattr(cc, "compress_context", spy)
    result = real(text, query, anchor_errors=True)

    compressed = result.compressed_text
    assert "SocketTimeoutException" in compressed
    assert not _is_fail_open(result)
    assert len(calls) <= 2
    assert calls
    assert calls[0].startswith(query + "\n")
    assert len(compressed) < 0.5 * len(text)
