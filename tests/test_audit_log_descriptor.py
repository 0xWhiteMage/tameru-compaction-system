import os

import pytest

from tameru.compress_context import compress_context


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="requires descriptor-based chmod")
def test_audit_log_closes_descriptor_when_chmod_fails(tmp_path, monkeypatch):
    opened = []

    def refuse_chmod(fd, mode):
        opened.append(fd)
        raise PermissionError("chmod refused")

    monkeypatch.setattr(os, "fchmod", refuse_chmod)
    compress_context(
        "INFO background sync complete\n" * 40 + "ERROR artifact-release failed",
        "artifact-release",
        ccr=False,
        log_dir=tmp_path,
    )

    assert len(opened) == 1
    fd = opened[0]
    try:
        with pytest.raises(OSError):
            os.fstat(fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
