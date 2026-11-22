import importlib
import os
import stat

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_sidecar_does_not_chmod_existing_parent(tmp_path):
    tmp_path.chmod(0o750)
    target = tmp_path / "sidecar"
    c._write_private_atomic(target, "hello")
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o750
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == "hello"
    fresh = tmp_path / "new" / "sidecar"
    c._write_private_atomic(fresh, "")
    assert stat.S_IMODE(fresh.parent.stat().st_mode) == 0o700
