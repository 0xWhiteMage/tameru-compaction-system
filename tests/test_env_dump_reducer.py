from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def _dump(extra=()):
    lines = [f"FEATURE_{i}_ENABLED=true" for i in range(40)]
    lines.extend(extra)
    lines.append("DATABASE_HOST=db-prod-2.internal")
    lines.append("DATABASE_PORT=5432")
    return "\n".join(lines) + "\n"


def _secret_dump():
    lines = [f"FEATURE_{i}_ENABLED=true" for i in range(40)]
    secrets = [
        "DB_PASSWORD=hunter2",
        "STRIPE_SECRET_KEY=sk_live_" + "x" * 24,
        "SESSION_TOKEN=abc",
    ]
    needles = ["hunter2", "sk_live_", "SESSION_TOKEN"]
    cache = [f"CACHE_{i}_TTL=60" for i in range(10)]
    lines = lines[:20] + secrets + cache + lines[20:]
    lines.append("DATABASE_HOST=db-prod-2.internal")
    lines.append("DATABASE_PORT=5432")
    return "\n".join(lines) + "\n", needles


def _kept_positions(out, text):
    lines = text.split("\n")
    kept = [ln for ln in out.split("\n") if ln and not ln.startswith("[…")]
    return [lines.index(ln) for ln in kept if ln in lines]


def test_env_dump_detect_and_fold():
    text = _dump()
    assert detect_test_runner(text) == "env_dump"
    out = preprocess_test_output(text)
    assert "DATABASE_HOST=db-prod-2.internal" in out
    assert "FEATURE_0_ENABLED=true" in out
    assert "FEATURE_7_ENABLED" not in out


def test_env_dump_flipped_value_kept():
    lines = [f"FEATURE_{i}_ENABLED=true" for i in range(40)]
    lines[13] = "FEATURE_13_ENABLED=false"
    lines.append("DATABASE_HOST=db-prod-2.internal")
    lines.append("DATABASE_PORT=5432")
    text = "\n".join(lines) + "\n"
    out = preprocess_test_output(text)
    assert "FEATURE_13_ENABLED=false" in out


def test_env_dump_no_query_drops_secrets_and_keeps_order():
    text, needles = _secret_dump()
    out = preprocess_test_output(text)

    for needle in needles:
        assert needle not in out

    assert "DATABASE_HOST=db-prod-2.internal" in out

    for ln in out.split("\n"):
        if ln.startswith("[…"):
            assert "=" not in ln
            for needle in needles:
                assert needle not in ln

    positions = _kept_positions(out, text)
    assert positions == sorted(positions)


def test_env_dump_compressed_without_ccr():
    text, needles = _secret_dump()

    r = compress_context(text, "", ccr=False, citations=False)
    assert r.compressed_text
    for needle in needles:
        assert needle not in r.compressed_text

    r2 = compress_context(text, "which database host is configured", ccr=False, citations=False)
    for needle in needles:
        assert needle not in r2.compressed_text
    assert "db-prod-2.internal" in r2.compressed_text


def test_env_dump_explicit_query_does_not_multiply_or_move():
    text, _ = _secret_dump()
    out = preprocess_test_output(text, "what is DB_PASSWORD")

    if "DB_PASSWORD=hunter2" in out:
        assert out.count("DB_PASSWORD=hunter2") == 1
    assert out.count("hunter2") <= 1

    positions = _kept_positions(out, text)
    assert positions == sorted(positions)


def test_env_dump_lone_long_opaque_value_dropped():
    text = _dump(extra=("BUILD_ID=0123456789abcdefghij0123",))
    assert detect_test_runner(text) == "env_dump"
    out = preprocess_test_output(text)
    assert "BUILD_ID=0123456789abcdefghij0123" not in out
    assert "0123456789abcdefghij0123" not in out


def test_env_dump_ccr_does_not_archive_secret(tmp_path):
    text, _ = _secret_dump()
    r = compress_context(text, "", ccr=True, ccr_dir=str(tmp_path), citations=False)

    assert "ccr skipped: secret material detected" in r.reasons

    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            assert "hunter2" not in content


def test_env_dump_not_triggered_for_small_prose_logfmt():
    small = "\n".join(f"FEATURE_{i}_ENABLED=true" for i in range(10)) + "\n"
    assert detect_test_runner(small) != "env_dump"

    prose = "\n".join(f"step {i}: completed" for i in range(20)) + "\n"
    assert detect_test_runner(prose) != "env_dump"

    logfmt = "\n".join(
        'ts=2026-10-20T03:00:00Z level=info msg="consumer heartbeat" queue=orders lag=12'
        for _ in range(25)
    ) + "\n"
    assert detect_test_runner(logfmt) != "env_dump"
