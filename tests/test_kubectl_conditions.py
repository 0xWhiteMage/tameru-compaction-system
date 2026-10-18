from tameru.agent_formats import detect_test_runner, preprocess_test_output

NODE_DESCRIBE = """\
Name: node-1
Roles: worker
Labels:
  label1=value1
  label2=value2
  label3=value3
  label4=value4
  label5=value5
Conditions:
  Type  Status  LastHeartbeatTime  LastTransitionTime  Reason  Message
  ----  ------  -----------------  ------------------  ------  -------
  Ready True 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletReady kubelet is ready
  MemoryPressure False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasSufficientMemory kubelet has sufficient memory
  DiskPressure True 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasDiskPressure kubelet has disk pressure
  PIDPressure False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasSufficientPID kubelet has sufficient PIDs
  KernelDeadlock False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasNoKernelDeadlock no kernel deadlock
  NetworkUnavailable False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z NetworkReady network is ready
  RootInodesPressure False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasSufficientInodes kubelet has sufficient inodes
  SwapPressure False 2026-01-01T00:00:00Z 2026-01-01T00:00:00Z KubeletHasNoSwapPressure no swap pressure
Events:
  Type    Reason            Age   From             Message
  ----    ------            ---   ----             -------
  Normal  Scheduled         1m    default-scheduler Successfully assigned default/pod-1 to node-1
"""

POD_DESCRIBE = """\
Name: pod-1
Namespace: default
Node: node-1/10.0.0.1
Conditions:
  Type  Status  LastTransitionTime  Reason  Message
  ----  ------  ------------------  ------  -------
  Initialized True 2026-01-01T00:00:00Z ContainersReady all containers have started
  Ready False 2026-01-01T00:00:00Z ContainersNotReady containers with unready status: app
  ContainersReady False 2026-01-01T00:00:00Z ContainersNotReady containers with unready status: app
  PodScheduled True 2026-01-01T00:00:00Z DefaultSchedulingGated scheduled
Events:
  Type    Reason   Age   From     Message
  ----    ------   ---   ----     -------
  Normal  Pulled   1m    kubelet  Container image "app:1" already present on machine
"""


def test_node_conditions_keep_abnormal_and_ready():
    assert detect_test_runner(NODE_DESCRIBE) == "kubectl"
    out = preprocess_test_output(NODE_DESCRIBE, "")
    assert "LastHeartbeatTime" in out
    assert "DiskPressure True" in out
    assert "Ready True" in out
    assert "MemoryPressure False" not in out
    assert "KernelDeadlock False" not in out


def test_node_conditions_query_rekeeps_memory_pressure():
    assert detect_test_runner(NODE_DESCRIBE) == "kubectl"
    out = preprocess_test_output(NODE_DESCRIBE, "is MemoryPressure ok")
    assert "MemoryPressure False" in out


def test_pod_conditions_small_table_kept():
    assert detect_test_runner(POD_DESCRIBE) == "kubectl"
    out = preprocess_test_output(POD_DESCRIBE, "")
    for token in ("Initialized True", "Ready False", "ContainersReady False", "PodScheduled True"):
        assert token in out
