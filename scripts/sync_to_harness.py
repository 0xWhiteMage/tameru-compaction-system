#!/usr/bin/env python3
"""Sync vendored Tameru modules into a harness plugin directory.

Vendored integrations (Hermes `plugins/context_engine/tameru/`, Pi/OpenCode
extensions, etc.) track this repo by copying `src/tameru/*.py` wholesale.
This script makes that a single command:

    python scripts/sync_to_harness.py <target_plugin_dir> [--manifest plugin.yaml]

Ownership contract:
  * Upstream (this repo) owns every `src/tameru/*.py` EXCEPT `__init__.py`.
  * The harness owns its registration glue (`__init__.py`, engine class,
    hook entry point) and its manifest (`plugin.yaml`, package.json, ...).
    This script never touches those — except for stamping `version:` /
    `description` in the manifest when --manifest is given.

It refuses to run if the target dir does not already exist (create the
harness-owned files first), copies all upstream modules, then verifies the
result byte-compiles.
"""
from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "tameru"

# Files upstream deliberately does NOT ship into vendored dirs.
_SKIP = {"__init__.py", "__main__.py"}


def _upstream_version() -> str:
    init = (SRC / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    return m.group(1) if m else "0.0.0"


def _stamp_manifest(manifest: Path, version: str) -> bool:
    """Bump `version:` and any 'Tameru X.Y.Z' in `description:`. Returns True if changed."""
    if not manifest.is_file():
        return False
    text = manifest.read_text(encoding="utf-8")
    out = re.sub(r"^version:\s*\S+", f"version: {version}", text, flags=re.M)
    out = re.sub(r"Tameru \d+\.\d+\.\d+", f"Tameru {version}", out)
    if out != text:
        manifest.write_text(out, encoding="utf-8")
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("target", help="vendored plugin directory (must exist)")
    p.add_argument(
        "--manifest",
        default=None,
        help="manifest file(s) to version-stamp, comma-separated or repeated",
        action="append",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    target = Path(args.target)
    if not target.is_dir():
        print(f"error: target dir does not exist: {target}", file=sys.stderr)
        print("create it plus the harness-owned __init__.py/manifest first", file=sys.stderr)
        return 2

    version = _upstream_version()
    sources = sorted(
        f for f in SRC.glob("*.py") if f.name not in _SKIP and not f.name.startswith(".")
    )
    changed = []
    for src in sources:
        dst = target / src.name
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            continue
        changed.append(src.name)
        if not args.dry_run:
            shutil.copyfile(src, dst)

    # Remove stale vendored modules that no longer exist upstream.
    stale = [
        f.name
        for f in target.glob("*.py")
        if f.name not in _SKIP and not (SRC / f.name).exists()
    ]
    for name in stale:
        if not args.dry_run:
            (target / name).unlink()

    manifests: list[Path] = []
    for entry in args.manifest or []:
        manifests.extend(target / m.strip() for m in entry.split(",") if m.strip())
    stamped = [
        m.name for m in manifests if args.dry_run or _stamp_manifest(m, version)
    ]

    if not args.dry_run:
        for src in sources:
            py_compile.compile(str(target / src.name), doraise=True)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}tameru {version} -> {target}")
    print(f"  updated: {changed or 'none'}")
    print(f"  removed: {stale or 'none'}")
    if manifests:
        print(f"  manifests stamped: {stamped or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
