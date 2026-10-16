import json
import time
from pathlib import Path

from tameru import compress_context as cc


def _write_record(path: Path, *, stored_at: float, ttl: int) -> None:
    path.write_text(
        json.dumps({"stored_at": stored_at, "ttl": ttl, "original": "record"}),
        encoding="utf-8",
    )


def test_sweep_cursor_is_per_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_CCR_SWEEP_CURSOR", {})

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    now = time.time()
    for index in range(4):
        _write_record(dir_a / f"{index:024x}.json", stored_at=now, ttl=3600)
        if index == 0:
            _write_record(dir_b / f"{index:024x}.json", stored_at=0, ttl=1)
        else:
            _write_record(dir_b / f"{index:024x}.json", stored_at=now, ttl=3600)

    cc.sweep_ccr_cache(dir_a, now=now, max_records=2)
    target = dir_b / "000000000000000000000000.json"
    assert target.exists()

    removed = cc.sweep_ccr_cache(dir_b, now=now, max_records=2)
    assert removed == 1
    assert not target.exists()


def test_sweep_cursor_accepts_legacy_int_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_CCR_SWEEP_CURSOR", 0)

    root = tmp_path / "root"
    root.mkdir()
    now = time.time()
    for index in range(4):
        _write_record(root / f"{index:024x}.json", stored_at=0, ttl=1)

    removed = cc.sweep_ccr_cache(root, now=now, max_records=2)
    assert removed == 2
    assert isinstance(cc._CCR_SWEEP_CURSOR, dict)
