import pytest

from tameru.agent_formats import is_diagnostic_line

POSITIVES = [
    "  42:7  error  'res' is assigned a value but never used  no-unused-vars",
    "10:01:00.001 [error] GenServer Cart.Worker terminating",
    "** (KeyError) key :sku not found in: %{qty: 2}",
    "npm ERR! code ERESOLVE",
    "npm error code ENOENT",
    "pod/worker-1   0/1   CrashLoopBackOff   12   40m",
    "  Warning  BackOff  2m  kubelet  Back-off restarting failed container",
    "  Failed Shop.Tests.CartTests.AppliesCoupon [12 ms]",
    "Failed!  - Failed:     1, Passed:    80, Skipped:     0, Total:    81",
    "  Warning  Unhealthy  1m  kubelet  Readiness probe failed",
    "  Warning  Evicted  1m  kubelet  The node was low on resource: memory",
]

NEGATIVES = [
    "  12:3  warning  Unexpected console statement  no-console",
    "10:00:01.123 [info] GET /health",
    "npm http fetch GET 200 https://registry.npmjs.org/x 30ms",
    "pod/web-1   1/1   Running   0   3h",
    "  Passed Shop.Tests.CartTests.Case1 [3 ms]",
    "Passed!  - Failed:     0, Passed:    81",
]

@pytest.mark.parametrize("line", POSITIVES)
def test_is_diagnostic_line_positive(line):
    assert is_diagnostic_line(line) is True

@pytest.mark.parametrize("line", NEGATIVES)
def test_is_diagnostic_line_negative(line):
    assert is_diagnostic_line(line) is False
