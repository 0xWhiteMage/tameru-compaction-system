from tameru.compress_context import classify_line, compress_context


def test_klog_lines_classify_as_log():
    assert classify_line(
        "W1021 10:03:00.512   1234 warnings.go:70] "
        "spec.template.spec.containers[0].env[3]: hides previous definition"
    ) == "log"
    assert classify_line(
        "I1021 09:00:01.000001       1 leaderelection.go:250] "
        "attempting to acquire leader lease"
    ) == "log"
    assert classify_line("Waiting 1021 seconds") == "text"


def test_helm_klog_context_compression():
    text = (
        'Release "shop" does not exist. Installing it now.\n'
        + "\n".join(
            f"W1021 10:0{i}:00.{100 + i}   1234 warnings.go:70] "
            f"spec.template.spec.containers[0].env[{i}]: hides previous definition"
            for i in range(9)
        )
        + '\nError: INSTALLATION FAILED: Deployment.apps "shop-api" is invalid: '
        "spec.template.spec.containers[0].image: Required value\n"
    )
    r = compress_context(
        text,
        "why did helm fail",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "INSTALLATION FAILED" in r.compressed_text
    assert "image: Required value" in r.compressed_text
    assert len(r.compressed_text) < len(text) * 0.6
