import importlib
from unittest.mock import patch

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("content", ["hello\nworld", "", b"hello\x00world", b""])
def test_atomic_writer_preserves_content(tmp_path, content):
    target = tmp_path / "record"
    c._write_private_atomic(target, content)
    assert target.read_bytes() == (content if isinstance(content, bytes) else content.replace("\n", c.os.linesep).encode())
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_failure_cleans_up_and_preserves_old_file(tmp_path):
    target = tmp_path / "record"
    target.write_bytes(b"old")
    with patch.object(c.os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            c._write_private_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


def test_ccr_roundtrip_uses_atomic_writer(tmp_path):
    info = c._ccr_store("hello\nworld", tmp_path)
    assert c.retrieve(info["hash"], tmp_path) == "hello\nworld"
