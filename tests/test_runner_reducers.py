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
