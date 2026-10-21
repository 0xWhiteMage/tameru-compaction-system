from tameru.agent_formats import detect_test_runner
from tameru.compress_context import compress_context


def test_kubectl_deployment_replicas_are_kept():
    lines = [
        "Name:               deployment-1",
        "Namespace:          default",
        "CreationTimestamp:  Mon, 01 Jan 2024 00:00:00 +0000",
        "Labels:             app=web",
        "Selector:           app=web",
        "Replicas:               6 desired | 6 updated | 6 total | 4 available | 2 unavailable",
        "StrategyType:         RollingUpdate",
        "Pod Template:",
        "  Containers:",
        "   app:",
        "    Image: x",
        "    Environment:",
    ]
    lines.extend(f"      FEATURE_FLAG_{i}:  true" for i in range(25))
    lines.extend([
        "Conditions:",
        "  Type             Status  Reason",
        "  ----  ------  ------",
        "  Available      False   MinimumReplicasUnavailable",
        "  Progressing    True    NewReplicaSetAvailable",
        "Events:",
        "  Type    Reason     Age   From             Message",
        "  ----  --------  ----  -------------  -------",
        "  Normal  Created   1m    replicaset   Created pod app-1",
    ])
    text = "\n".join(lines)

    assert detect_test_runner(text) == "kubectl"

    r = compress_context(text, "", ccr=False, citations=False)
    out = r.compressed_text
    assert "2 unavailable" in out
    assert "MinimumReplicasUnavailable" in out
    assert "FEATURE_FLAG_7" not in out
