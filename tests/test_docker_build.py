from tameru.agent_formats import detect_test_runner, preprocess_test_output
from tameru.compress_context import compress_context


def test_classic_docker_build_keeps_failing_step():
    lines = ["Sending build context to Docker daemon  48.2MB"]
    for i in range(1, 12):
        lines.append(f"Step {i}/14 : RUN echo layer{i}")
        lines.append(" ---> Using cache")
        lines.append(f" ---> {i:012x}")
    lines.extend([
        "Step 12/14 : RUN pip install -r requirements.txt",
        " ---> Running in 4f2a9c1d7e3b",
        "ERROR: Could not find a version that satisfies the requirement numpy==9.0",
        "The command '/bin/sh -c pip install -r requirements.txt' returned a non-zero code: 1",
    ])
    text = "\n".join(lines)
    assert detect_test_runner(text) == "docker_build"
    out = preprocess_test_output(text)
    assert "Step 12/14" in out
    assert "numpy==9.0" in out
    assert "non-zero code: 1" in out
    assert "Step 5/14" not in out
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert r is not None
    assert "Step 12/14" in r.compressed_text
    assert "numpy==9.0" in r.compressed_text
    assert "non-zero code: 1" in r.compressed_text
    assert len(r.compressed_text) < len(text) / 2


def test_buildkit_success_keeps_image_digest():
    lines = []
    for i in range(1, 21):
        lines.append(f"#{i} [stage-1 {i}/20] COPY src/mod{i} /app/mod{i}")
        lines.append(f"#{i} CACHED")
    lines.extend([
        "#21 exporting to image",
        "#21 exporting layers 2.1s done",
        "#21 writing image sha256:9f3c2e7a1b4d done",
        "#21 naming to docker.io/acme/api:1.4.2 done",
        "#21 DONE 2.3s",
    ])
    text = "\n".join(lines)
    assert detect_test_runner(text) == "docker_build"
    out = preprocess_test_output(text)
    assert "acme/api:1.4.2" in out
    assert "sha256:9f3c2e7a" in out
    assert "mod7" not in out
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert r is not None
    assert "acme/api:1.4.2" in r.compressed_text
    assert "sha256:9f3c2e7a" in r.compressed_text
    assert len(r.compressed_text) < len(text) / 2


def test_buildkit_failure_keeps_error():
    lines = []
    for i in range(1, 19):
        lines.append(f"#{i} [internal] load metadata for docker.io/library/node:20")
        lines.append(f"#{i} DONE 0.{i}s")
    lines.extend([
        "#40 [build 6/9] RUN npm ci",
        '#40 ERROR: process "/bin/sh -c npm ci" did not complete successfully: exit code: 1',
    ])
    text = "\n".join(lines)
    assert detect_test_runner(text) == "docker_build"
    out = preprocess_test_output(text)
    assert "npm ci" in out
    assert "exit code: 1" in out


def test_kubectl_pods_and_prose_detection():
    text = "\n".join([
        "NAME   READY   STATUS   RESTARTS   AGE",
        "api-0  1/1     Running  0          5m",
        "api-1  1/1     Running  0          5m",
        "web-0  1/1     Running  0          5m",
        "web-1  0/1     CrashLoopBackOff  3          5m",
        "job-0  0/1     Completed  0          1h",
    ])
    assert detect_test_runner(text) == "kubectl_pods"
    assert detect_test_runner("The build failed because the test suite timed out.") is None
