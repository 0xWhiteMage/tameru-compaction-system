from tameru.agent_formats import preprocess_test_output, detect_test_runner


def _kubectl_node_text_with_pod_rows():
    lines = [
        "Name:               ip-10-0-7-21",
        "Roles:              worker",
    ]
    lines.extend(f"                    label{i}=value{i}" for i in range(30))
    lines.extend(
        [
            "Conditions:",
            "  Type             Status  Reason                       Message",
            "  MemoryPressure   True    KubeletHasInsufficientMemory kubelet has insufficient memory available",
            "  DiskPressure     False   KubeletHasNoDiskPressure     kubelet has no disk pressure",
        ]
    )
    lines.extend(
        f"  pod-{i}-x{i}   100m (2%)   0 (0%)   128Mi (1%)   256Mi (3%)   {i}d"
        for i in range(40)
    )
    lines.extend(
        [
            "Events:",
            "  Type     Reason                Age   From     Message",
            "  Warning  EvictionThresholdMet  4m    kubelet  Attempting to reclaim memory",
            "  Normal   NodeReady             2d    kubelet  Node status is now: NodeReady",
        ]
    )
    return "\n".join(lines) + "\n"


def _kubectl_node_text_with_real_conditions():
    lines = [
        "Name:               ip-10-0-7-21",
        "Roles:              worker",
    ]
    lines.extend(f"                    label{i}=value{i}" for i in range(30))
    lines.extend(
        [
            "Conditions:",
            "  Type             Status  Reason                       Message",
            "  MemoryPressure   False   KubeletHasNoMemoryPressure   kubelet has no memory pressure",
            "  DiskPressure     False   KubeletHasNoDiskPressure     kubelet has no disk pressure",
            "  PIDPressure      False   KubeletHasNoPIDPressure      kubelet has no PID pressure",
            "  NetworkUnavailable False KubeletReady                 kubelet is ready",
            "  Ready            True    KubeletReady                 kubelet is ready",
            "  Foo              False   SomeReason                   some message",
            "  Foo              False   SomeReason                   some message",
        ]
    )
    lines.extend(
        [
            "Events:",
            "  Type     Reason                Age   From     Message",
            "  Warning  EvictionThresholdMet  4m    kubelet  Attempting to reclaim memory",
            "  Normal   NodeReady             2d    kubelet  Node status is now: NodeReady",
        ]
    )
    return "\n".join(lines) + "\n"


def test_kubectl_conditions_drops_pod_resource_rows():
    text = _kubectl_node_text_with_pod_rows()
    assert detect_test_runner(text) == "kubectl"

    out = preprocess_test_output(text, "")
    assert "MemoryPressure   True" in out
    assert "EvictionThresholdMet" in out
    assert len(out) < 0.35 * len(text)
    assert "pod-20-x20" not in out


def test_kubectl_conditions_keeps_ready_condition():
    text = _kubectl_node_text_with_real_conditions()
    assert detect_test_runner(text) == "kubectl"

    out = preprocess_test_output(text, "")
    assert any(line.strip().startswith("Ready") for line in out.splitlines())
