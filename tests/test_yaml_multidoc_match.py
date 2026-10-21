from tameru.compress_context import compress_context


def test_yaml_multidoc_secret_match_keeps_enclosing_document() -> None:
    text = (
        "\n---\n".join(
            f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg-{i}\ndata:\n  LOG_LEVEL: info"
            for i in range(20)
        )
        + "\n---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: db-creds\nstringData:\n  DB_PASSWORD: hunter2-plaintext\n"
    )
    r = compress_context(text, "is any secret stored in plain text", ccr=False, citations=False)
    out = r.compressed_text
    assert "db-creds" in out
    assert "DB_PASSWORD" in out
    assert "cfg-7" not in out


def test_yaml_single_doc_secret_match_preserves_existing_behavior() -> None:
    lines = [f"key{i}: v{i}" for i in range(15)]
    lines.append("kind: Secret")
    lines.extend(f"key{i}: v{i}" for i in range(15, 30))
    text = "\n".join(lines)
    r = compress_context(text, "secret", ccr=False, citations=False)
    assert "kind: Secret" in r.compressed_text
