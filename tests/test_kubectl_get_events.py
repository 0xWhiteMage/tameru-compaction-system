from tameru.compress_context import compress_context
from tameru.agent_formats import (
    detect_test_runner,
    preprocess_test_output,
)


def _text_a():
    header = "LAST SEEN   TYPE      REASON      OBJECT              MESSAGE"
    rows = [
        f"{10+i}s         Normal    Pulled      pod/web-{i}-x        Container image already present"
        for i in range(40)
    ]
    rows.append(
        '30s         Warning   FailedMount pod/db-0           MountVolume.SetUp failed for volume "data" : rpc error: code = DeadlineExceeded'
    )
    return "\n".join([header] + rows)


def test_detect_and_preprocess_kubectl_get_events():
    text = _text_a()
    assert detect_test_runner(text) == "kubectl_events"
    out = preprocess_test_output(text, "")
    assert out is not None
    assert "LAST SEEN   TYPE      REASON      OBJECT              MESSAGE" in out
    warning = '30s         Warning   FailedMount pod/db-0           MountVolume.SetUp failed for volume "data" : rpc error: code = DeadlineExceeded'
    assert warning in out
    assert len(out) < 0.4 * len(text)


def test_namespace_backoff_keeps_first_and_last():
    header = "NAMESPACE   LAST SEEN   TYPE      REASON      OBJECT              MESSAGE"
    rows = [
        "ns1         10s         Warning   BackOff     pod/app-0           Back-off restarting failed container",
        "ns1         20s         Warning   BackOff     pod/app-0           Back-off restarting failed container",
        "ns1         30s         Warning   BackOff     pod/app-0           Back-off restarting failed container",
    ]
    text = "\n".join([header] + rows)
    assert detect_test_runner(text) == "kubectl_events"
    out = preprocess_test_output(text, "")
    assert out is not None
    assert rows[0] in out
    assert rows[2] in out
    assert rows[1] not in out


def test_only_normal_rows_keep_last_two():
    header = "LAST SEEN   TYPE      REASON      OBJECT              MESSAGE"
    rows = [
        f"{i}s         Normal    Started     pod/app-{i}           Started container app"
        for i in range(12)
    ]
    text = "\n".join([header] + rows)
    out = preprocess_test_output(text, "")
    assert out is not None
    assert header in out
    assert rows[-2] in out
    assert rows[-1] in out
    assert rows[0] not in out


def test_describe_pod_still_detected_as_kubectl():
    text = (
        "Name:         app\n"
        "Namespace:    default\n"
        "Node:         node-1/10.0.0.1\n"
        "Start Time:   Mon, 01 Jan 2024 00:00:00 +0000\n"
        "Events:\n"
        "  Type    Reason     Age   From               Message\n"
        "  ----    ------     ----  ----               -------\n"
        "  Normal  Scheduled  10s   default-scheduler  Successfully assigned default/app to node-1\n"
    )
    assert detect_test_runner(text) == "kubectl"


def test_compress_context_keeps_failed_mount():
    text = _text_a()
    out = compress_context(
        text,
        "",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )
    assert not out.fail_open
    assert out.compressed_text != text
    assert "FailedMount" in out.compressed_text
