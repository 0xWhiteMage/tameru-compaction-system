from tameru.compress_context import compress_context


def _manifest():
    return (
        "\n---\n".join(
            f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg-{i}\ndata:\n  LOG_LEVEL: info"
            for i in range(20)
        )
        + "\n---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: db-creds\nstringData:\n  DB_PASSWORD: hunter2-plaintext\n"
    )


def test_yaml_documents_outliers_keeps_secret_and_first_configmap():
    text = _manifest()
    r = compress_context(text, "", ccr=False, citations=False)
    assert "db-creds" in r.compressed_text
    assert "DB_PASSWORD" in r.compressed_text
    assert "cfg-0" in r.compressed_text
    assert "cfg-7" not in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(text)


def test_yaml_documents_outliers_keeps_value_outlier():
    docs = []
    for i in range(20):
        level = "debug" if i == 13 else "info"
        docs.append(
            f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg-{i}\ndata:\n  LOG_LEVEL: {level}"
        )
    text = "\n---\n".join(docs)
    r = compress_context(text, "", ccr=False, citations=False)
    assert "cfg-13" in r.compressed_text
    assert "LOG_LEVEL: debug" in r.compressed_text
    assert "cfg-7" not in r.compressed_text


def test_yaml_documents_outliers_declines_few_documents():
    text = "\n---\n".join(
        f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg-{i}\ndata:\n  LOG_LEVEL: info"
        for i in range(3)
    )
    r = compress_context(text, "", ccr=False, citations=False)
    assert r.compressed_text.strip() == text.strip()
