from tameru.agent_formats import detect_test_runner, _classify_kubectl_pods
from tameru.compress_context import compress_context

HEADER = "NAME                         READY   STATUS             RESTARTS   AGE"


def _sample_lines():
    lines = [HEADER]
    for i in range(25):
        lines.append(f"api-{i}-x                    1/1     Running            0          3d")
    lines.append("payments-6f9-zz               0/1     CrashLoopBackOff   14         3d")
    lines.append("worker-2                      1/2     Running            0          1d")
    lines.append("job-7                         0/1     Completed          0          5h")
    return lines


def _sample_text():
    return "\n".join(_sample_lines())


def test_detect_kubectl_pods():
    assert detect_test_runner(_sample_text()) == "kubectl_pods"


def test_classify_kubectl_pods_keeps_problem_rows_and_context():
    lines = _sample_lines()
    keep = _classify_kubectl_pods(lines)[0]
    by_name = {line.split()[0]: i for i, line in enumerate(lines) if line.strip()}

    assert keep[0]
    assert keep[by_name["payments-6f9-zz"]]
    assert keep[by_name["worker-2"]]
    assert not keep[by_name["job-7"]]
    assert not keep[by_name["api-5-x"]]


def test_classify_kubectl_pods_keeps_running_with_restarts():
    lines = [
        HEADER,
        "pod-a                      1/1     Running            3 (2m ago)   3d",
    ]
    keep = _classify_kubectl_pods(lines)[0]
    assert keep[1]


def test_detect_kubectl_pods_with_namespace_header():
    lines = [
        "NAMESPACE   NAME                         READY   STATUS             RESTARTS   AGE",
        "api-0-x                    1/1     Running            0          3d",
        "api-1-x                    1/1     Running            0          3d",
    ]
    text = "\n".join(lines)
    assert detect_test_runner(text) == "kubectl_pods"
    keep = _classify_kubectl_pods(lines)[0]
    assert keep[0]
    assert keep[1]
    assert keep[2]


def test_compress_context_kubectl_pods():
    text = _sample_text()
    result = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "payments-6f9-zz" in result.compressed_text
    assert "CrashLoopBackOff" in result.compressed_text
    assert not result.fail_open
    assert len(result.compressed_text) < 0.4 * len(text)


def test_not_detected_header_only():
    assert detect_test_runner(HEADER) is None


def test_not_detected_name_age_table():
    text = "NAME   AGE\napi-0-x   3d\napi-1-x   3d"
    assert detect_test_runner(text) is None
