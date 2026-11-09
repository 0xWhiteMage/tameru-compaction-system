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


def _pod_documents():
    documents = []
    for i in range(20):
        status = ("  phase: Failed\n  containerStatuses:\n  - lastState:\n"
                  "      terminated:\n        reason: OOMKilled\n        exitCode: 137"
                  if i == 7 else "  phase: Running")
        documents.append(
            f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: worker-{i}\n"
            f"spec:\n  containers:\n  - name: app\n    image: shop/app:1.{i}\nstatus:\n{status}"
        )
    return documents


def test_failure_selection_keeps_the_entire_pod_document():
    documents = _pod_documents()
    source = "---\n" + "\n---\n".join(documents)
    result = compress_context(source, "which pod failed and why", ccr=False, citations=False)
    assert documents[7] in result.compressed_text
    assert "worker-3" not in result.compressed_text
    assert result.receipt["adapter"]["name"] == "yaml_documents"


def test_named_pod_selection_keeps_its_complete_status():
    documents = _pod_documents()
    source = "---\n" + "\n---\n".join(documents)
    result = compress_context(source, "show worker-7", ccr=False, citations=False)
    assert documents[7] in result.compressed_text
    assert "worker-3" not in result.compressed_text


def test_absent_pod_query_keeps_original_stream():
    source = "---\n" + "\n---\n".join(_pod_documents())
    result = compress_context(source, "missing-pod-999", ccr=False, citations=False)
    assert result.fail_open
    assert result.compressed_text == source
