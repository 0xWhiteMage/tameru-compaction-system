from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_gradle():
    text = "\n".join(f"> Task :m{i}:compileJava UP-TO-DATE" for i in range(30)) + (
        "\n> Task :m1:test\n\nPayTest > refundsTwice() FAILED\n"
        "    java.lang.AssertionError: expected:<1> but was:<2>\n"
        "        at PayTest.refundsTwice(PayTest.java:40)\n\n"
        "20 tests completed, 1 failed\n\nFAILURE: Build failed with an exception."
    )
    assert detect_test_runner(text) == "gradle"
    out = preprocess_test_output(text)
    assert out
    assert "refundsTwice() FAILED" in out
    assert "PayTest.java:40" in out
    assert "UP-TO-DATE" not in out


def test_rspec():
    text = "\n".join(f"  Widget#{i}\n    renders" for i in range(30)) + (
        "\n\nFailures:\n\n  1) Widget saves\n"
        "     Failure/Error: expect(x).to eq(1)\n\n"
        "       expected: 1\n            got: 2\n\n"
        "     # ./spec/widget_spec.rb:9:in `block (2 levels)'\n\n"
        "Finished in 1.1 seconds\n61 examples, 1 failure"
    )
    assert detect_test_runner(text) == "rspec"
    out = preprocess_test_output(text)
    assert out
    assert "got: 2" in out
    assert "widget_spec.rb:9" in out
    assert "61 examples, 1 failure" in out
    assert "renders" not in out


def test_phpunit():
    text = (
        "PHPUnit 11.0.0 by Sebastian Bergmann and contributors.\n\n"
        + "\n".join("." * 63 + f" {63 * (i + 1)} / 400 ({15 * (i + 1)}%)" for i in range(6))
        + "\n..F.\n\nThere was 1 failure:\n\n1) Tests\\FooTest::testBar\n"
        "Failed asserting that false is true.\n\n/app/tests/FooTest.php:12\n\n"
        "FAILURES!\nTests: 400, Assertions: 900, Failures: 1."
    )
    assert detect_test_runner(text) == "phpunit"
    out = preprocess_test_output(text)
    assert out
    assert "testBar" in out
    assert "FooTest.php:12" in out
    assert "..F." in out
    assert "." * 63 not in out


def test_dotnet():
    text = "\n".join(f"  Passed Lib.Tests.T{i} [1 ms]" for i in range(40)) + (
        "\n  Failed Lib.Tests.Breaks [2 ms]\n  Error Message:\n"
        "   Assert.True() Failure\n  Stack Trace:\n"
        "     at Lib.Tests.Breaks() in /src/T.cs:line 9\n\n"
        "Failed!  - Failed:     1, Passed:    40, Skipped:     0, Total:    41"
    )
    assert detect_test_runner(text) == "dotnet"
    out = preprocess_test_output(text)
    assert out
    assert "Breaks" in out
    assert "T.cs:line 9" in out
    assert "Failed!" in out
    assert "Lib.Tests.T5 " not in out


def test_pytest_q():
    text = (
        "".join(f"tests/test_{i}.py " + "." * 50 + f" [{i}%]\n" for i in range(1, 20))
        + "tests/test_x.py ..F [100%]\n\n___ test_x ___\n\n"
        ">   assert 1 == 2\nE   assert 1 == 2\n\n"
        "tests/test_x.py:3: AssertionError\n1 failed, 950 passed in 3.00s"
    )
    assert detect_test_runner(text) == "pytest"
    out = preprocess_test_output(text)
    assert out
    assert "assert 1 == 2" in out
    assert "tests/test_x.py:3" in out
    assert "1 failed, 950 passed" in out
    assert "tests/test_5.py" not in out


def test_kubectl():
    text = (
        "Name:         api-7c9-abcde\nNamespace:    prod\nLabels:       app=api\n"
        "              tier=web\nAnnotations:  a/b: c\nStatus:       Running\n"
        "Containers:\n  api:\n    Image:          api:v2\n    State:          Waiting\n"
        "      Reason:       CrashLoopBackOff\n    Last State:     Terminated\n"
        "      Reason:       OOMKilled\n      Exit Code:    137\n    Ready:          False\n"
        "    Restart Count:  12\n    Environment:\n      A:  1\n      B:  2\n"
        "    Mounts:\n      /x from y (rw)\nConditions:\n  Type    Status\n  Ready   False\n"
        "Volumes:\n  y:\n    Type:  EmptyDir\n"
        "Tolerations:  node.kubernetes.io/not-ready:NoExecute op=Exists for 300s\n"
        "Events:\n  Type     Reason     Age   From     Message\n"
        "  Normal   Pulled     5m    kubelet  pulled\n"
        "  Normal   Created    5m    kubelet  created\n"
        "  Normal   Started    5m    kubelet  started\n"
        "  Warning  BackOff    1m    kubelet  Back-off restarting failed container"
    )
    assert detect_test_runner(text) == "kubectl"
    out = preprocess_test_output(text)
    assert out
    assert "OOMKilled" in out
    assert "Exit Code:    137" in out
    assert "Ready   False" in out
    assert "Back-off restarting" in out
    assert "Tolerations" not in out
    assert "tier=web" not in out
    assert "describe lines omitted" in out
    assert "Normal   Pulled" not in out

def test_kubectl_describe_node_keeps_pressure_and_events():
    text = (
        "Name:               worker-3\nRoles:              <none>\nLabels:             kubernetes.io/arch=amd64\n"
        "                    kubernetes.io/hostname=worker-3\nAnnotations:        node.alpha.kubernetes.io/ttl: 0\n"
        "Taints:             node.kubernetes.io/disk-pressure:NoSchedule\nUnschedulable:      false\n"
        "Conditions:\n  Type             Status  Reason                  Message\n"
        "  MemoryPressure   False   KubeletHasSufficientMemory  ok\n  DiskPressure     True    KubeletHasDiskPressure  kubelet has disk pressure\n"
        "Addresses:\n  InternalIP:  10.0.3.17\nCapacity:\n  ephemeral-storage:  101445540Ki\n"
        "System Info:\n" + "".join(f"  Field{i}:  value{i}\n" for i in range(12)) +
        "Non-terminated Pods:          (14 in total)\n" + "".join(f"  shop  worker-{i:02}-6d8f9c  100m (1%)  0 (0%)  3d\n" for i in range(14)) +
        "Events:\n  Type     Reason                 Age   From     Message\n"
        "  Normal   NodeHasNoDiskPressure  20d   kubelet  no disk pressure\n"
        "  Warning  EvictionThresholdMet   20m   kubelet  Attempting to reclaim ephemeral-storage\n"
        "  Normal   NodeHasDiskPressure    20m   kubelet  status is now: NodeHasDiskPressure"
    )
    assert detect_test_runner(text) == "kubectl"
    out = preprocess_test_output(text)
    assert out
    for want in ("disk-pressure:NoSchedule", "KubeletHasDiskPressure", "10.0.3.17", "101445540Ki", "(14 in total)", "EvictionThresholdMet", "NodeHasDiskPressure    20m"):
        assert want in out
    assert "Field3" not in out and "worker-05-6d8f9c" not in out and "kubernetes.io/hostname" not in out


def test_kubectl_events_at_indent_zero_and_name_terms():
    text = ("Name:         checkout-api-7d9f-x2k4q\nNamespace:    shop\nLabels:       app=checkout-api\n"
            "              pod-template-hash=7d9f\nStatus:       Running\nIPs:\n  IP:  10.42.3.17\nContainers:\n  checkout-api:\n"
            "    Image:          registry/checkout-api:v1\n    Image ID:       registry/checkout-api@sha256:" + "a" * 64 + "\n"
            "    State:          Waiting\n      Reason:       CrashLoopBackOff\n    Restart Count:  9\n"
            "Volumes:\n  kube-api-access:\n    Type:  Projected\nEvents:\n"
            "Type      Reason      Age                   From      Message\n"
            "Warning   Unhealthy   4m (x59 over 29m)     kubelet   Liveness probe failed: HTTP probe failed with statuscode: 503\n"
            "Normal    Pulled      7m (x9 over 31m)      kubelet   Container image \"registry/checkout-api:v1\" already present\n"
            "Normal    Created     7m (x9 over 31m)      kubelet   Created container checkout-api\n"
            "Normal    Started     8m (x9 over 31m)      kubelet   Started container checkout-api\n"
            "Warning   BackOff     1m (x93 over 28m)     kubelet   Back-off restarting failed container checkout-api")
    out = preprocess_test_output(text, "why is checkout-api crashing")
    assert out
    for want in ("CrashLoopBackOff", "Restart Count:  9", "Liveness probe failed", "Back-off restarting", "Started container"):
        assert want in out
    for gone in ("sha256", "Pulled", "IPs:", "Volumes:", "pod-template-hash"):
        assert gone not in out


def test_kubectl_separator_rows_dropped():
    text = ("Name:  n1\n"
            "Labels:  a=1\n" + "".join(f"         l{i}=v{i}\n" for i in range(12)) +
            "Conditions:\n  Type    Status\n  ----    ------\n  Ready   False\nEvents:\n"
            "  Type     Reason  Age  From     Message\n  ----     ------  ---  ----     -------\n  Warning  Evicted  1m   kubelet  evicted")
    out = preprocess_test_output(text)
    assert out and "----" not in out and "Ready   False" in out and "Evicted" in out and "l7=v7" not in out


def test_phpunit_diff_context_shortened():
    ctx = "\n".join(f"     'k{i}' => {i}" for i in range(30))
    text = ("PHPUnit 10.5.0 by Sebastian Bergmann and contributors.\n\n" + "." * 60 + " 60 / 61 (98%)\nF\n\nThere was 1 failure:\n\n"
            "1) Tests\\CartTest::testDiscount\nFailed asserting that two arrays are equal.\n--- Expected\n+++ Actual\n@@ @@\n Array (\n"
            + ctx + "\n-    'total' => 90\n+    'total' => 100\n )\n\n/app/tests/CartTest.php:77\n\nFAILURES!\nTests: 61, Assertions: 70, Failures: 1.")
    out = preprocess_test_output(text)
    assert out
    for want in ("testDiscount", "'total' => 90", "'total' => 100", "'k29' => 29", "CartTest.php:77", "Failures: 1", "unchanged diff lines omitted"):
        assert want in out
    assert "'k5' => 5" not in out


def _spec55_node_text(label_count, event_count=20, condition_count=2):
    reasons = [
        "FailedMount",
        "FailedAttachVolume",
        "EvictionThresholdMet",
        "ImageGCFailed",
        "FreeDiskSpaceFailed",
        "SystemOOM",
        "ContainerGCFailed",
        "Rebooted",
        "NodeNotReady",
        "InvalidDiskCapacity",
        "FailedCreatePodSandBox",
        "NetworkNotReady",
    ]
    s = "Name:               w-100\nRoles:              worker\nLabels:             os=linux\n"
    s += "".join(f"                    label{i}=value{100 + i}\n" for i in range(label_count))
    s += (
        "Conditions:\n"
        "  Type             Status  LastHeartbeatTime                 Reason                       Message\n"
    )
    for c in ["MemoryPressure", "DiskPressure", "PIDPressure", "Ready"][:condition_count]:
        s += (
            f"  {c:16} False   Sun, 18 Oct 2026 04:00:00 +0000   "
            f"KubeletHasSufficient{c}   kubelet has sufficient {c.lower()} available\n"
        )
    s += "Events:\n  Type     Reason                 Age   From     Message\n"
    for i in range(event_count):
        reason = reasons[i % len(reasons)]
        s += (
            f"  Warning  {reason:22} {i + 1}m    kubelet  "
            f"{reason} on volume vol-{1000 + i} attempt {i}: rpc error code {1 + i}\n"
        )
    return s.rstrip()


def test_kubectl_describe_node_adapter_uses_char_savings_for_min_savings():
    from tameru.compress_context import compress_context, _estimate_tokens
    from tameru.agent_formats import preprocess_test_output

    label_count = 20
    while True:
        text = _spec55_node_text(label_count, 20, 2)
        preprocessed = preprocess_test_output(text, "")
        char_ratio = len(preprocessed) / max(1, len(text))
        token_ratio = _estimate_tokens(preprocessed) / max(1, _estimate_tokens(text))
        if char_ratio < 0.9 and token_ratio > 0.9:
            break
        label_count += 1
        assert label_count <= 60, "could not build sample with required savings profile"

    result = compress_context(
        text,
        "why is the node unhealthy",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )
    assert not result.fail_open
    assert len(result.compressed_text) < 0.95 * len(text)
    assert not any("savings below min_savings_ratio" in str(reason) for reason in result.reasons)
    assert "FailedMount on volume vol-1000 attempt 0" in result.compressed_text
    assert "Rebooted on volume vol-1019 attempt 19" in result.compressed_text


def test_non_adapter_low_savings_still_fails_open():
    from tameru.compress_context import compress_context

    text = " ".join(
        f"word{i} is a plain prose token used to pad the context"
        for i in range(50)
    )
    result = compress_context(
        text,
        "word is plain prose token used pad context",
        ccr=False,
        citations=False,
        min_savings_ratio=0.99,
    )
    assert result.compressed_text == text or any(
        "savings below min_savings_ratio" in str(reason) for reason in result.reasons
    )


def test_pytest_output_survives_empty_query_guard():
    from tameru.agent_formats import detect_test_runner
    from tameru.compress_context import compress_context

    lines = [
        "============================= test session starts ==============================",
        "platform linux -- Python 3.12.1, pytest-8.2.0",
        "collected 301 items",
    ]
    for i in range(300):
        pct = round((i + 1) / 301 * 100)
        lines.append(f"tests/test_x.py::test_{i} PASSED      [ {pct:3d}%]")
    lines.extend(
        [
            "",
            "FAILURES",
            "_____ test_fail _____",
            ">       assert 1 == 2",
            "E       assert 1 == 2",
            "tests/test_x.py:3: AssertionError",
            "",
            "short test summary info",
            "FAILED tests/test_x.py::test_fail - assert 1 == 2",
            "========================= 1 failed, 300 passed in 0.12s =========================",
        ]
    )
    text = "\n".join(lines)

    assert detect_test_runner(text) == "pytest"

    result = compress_context(text, "", ccr=False, citations=False)
    assert result.fail_open is False
    assert "FAILED tests/test_x.py::test_fail" in result.compressed_text
    assert "1 failed, 300 passed" in result.compressed_text


def test_plain_prose_empty_query_still_returns_input():
    from tameru.compress_context import compress_context

    prose = " ".join(["lorem"] * 300)
    result = compress_context(prose, "", ccr=False, citations=False)
    assert result.compressed_text == prose
