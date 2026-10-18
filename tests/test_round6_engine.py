from tameru.agent_formats import is_kubectl_status_line
from tameru.compress_context import _dup_fp, error_fingerprints
from tameru.folding import mask_template
def test_status_rows_flag():
    text = ("api-7c9-x2k4q   0/1   CrashLoopBackOff   9 (2m ago)   20m\n"
            "  Warning  BackOff  1m  kubelet  Back-off restarting failed container\n"
            "ERROR db: connection refused\n")
    full = error_fingerprints(text)
    lean = error_fingerprints(text, status_rows=False)
    assert len(full) == 3 and len(lean) == 1
    assert "ERROR db: connection refused" in lean.values()
    assert is_kubectl_status_line("api-1   0/1   OOMKilled   3   1m")
    assert not is_kubectl_status_line("ERROR db: connection refused")
def test_dup_fp_unchanged():
    def old(text):
        return " ".join(mask_template(line.lower()) for line in text[:4000].split("\n"))[:240]
    samples = ["", "a", "x\n" * 300, "2026-10-17 10:00:00 INFO id=12345 path=/a/b/3\n" * 50, "'1' \"2\" 1.2.3.4\n" * 40, "a" * 5000]
    for s in samples:
        assert _dup_fp(s) == old(s)
