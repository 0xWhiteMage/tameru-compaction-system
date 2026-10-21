from tameru.agent_formats import preprocess_test_output


def test_kubectl_separator_markers():
    env_lines = [f"      OPT_{i}:  value{i}" for i in range(25)]
    text = "\n".join(
        [
            "Name:               redis",
            "Namespace:          cache",
            "Selector:           app=redis",
            "Labels:             app=redis",
            "Replicas:           3 desired | 1 total",
            "Update Strategy:    RollingUpdate",
            "Pods Status:        1 Running / 0 Waiting / 0 Succeeded / 0 Failed",
            "Pod Template:",
            "  Labels:  app=redis",
            "  Containers:",
            "   redis:",
            "    Image:      redis:7.2",
            "    Environment:",
            *env_lines,
            "Events:",
            "  Type     Reason        Age   From                    Message",
            "  ----     ------        ----  ----                    -------",
            '  Warning  FailedCreate  2m    statefulset-controller  create Pod redis-1 in StatefulSet redis failed error: pods "redis-1" is forbidden: exceeded quota: cache-quota',
        ]
    )

    out = preprocess_test_output(text)

    assert "----" not in out
    assert "exceeded quota" in out
    assert "3 desired | 1 total" in out
    assert "OPT_7" not in out

    out_lines = out.split("\n")
    warning_idx = next(
        i for i, line in enumerate(out_lines) if "exceeded quota" in line
    )
    assert out_lines[warning_idx - 1] == (
        "  Type     Reason        Age   From                    Message"
    )
