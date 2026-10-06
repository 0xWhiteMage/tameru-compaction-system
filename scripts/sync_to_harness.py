#!/usr/bin/env python3
"""Sync vendored Tameru modules into a harness plugin directory.

Vendored integrations (the Hermes plugin repo's `hermes_tameru_plugin/tameru/`,
Pi/OpenCode extensions, etc.) track this repo by copying `src/tameru/*.py` wholesale.
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

--manifest paths are resolved relative to the TARGET directory, not the current
directory (absolute paths are used as given). With the manifest next to a
vendored subpackage, e.g. `hermes_tameru_plugin/plugin.yaml` for the target
`hermes_tameru_plugin/tameru`, pass `--manifest ../plugin.yaml`:

    python scripts/sync_to_harness.py hermes_tameru_plugin/tameru --manifest ../plugin.yaml

--check is a read-only drift check for CI. It reports what a sync would change
(modules whose content differs, upstream modules missing from the target, stale
vendored modules a sync would remove, manifest version/description stamps that
would change, manifest files that cannot be found) and exits 1 with that list
if anything differs, 0 if the target is in sync. It never writes anything.
"""
from __future__ import annotations

import argparse
import py_compile
import re
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


def _stamped(text: str, version: str) -> str:
    out = re.sub(r"^version:\s*\S+", f"version: {version}", text, flags=re.M)
    return re.sub(r"Tameru \d+\.\d+\.\d+", f"Tameru {version}", out)


def _stamp_manifest(manifest: Path, version: str, *, write: bool = True) -> bool:
    """Bump `version:` and any 'Tameru X.Y.Z' in `description:`. Returns True if changed.

    With ``write=False`` nothing is written; the return value says whether a
    write would have changed the file.
    """
    if not manifest.is_file():
        return False
    text = manifest.read_text(encoding="utf-8")
    out = _stamped(text, version)
    if out != text:
        if write:
            manifest.write_text(out, encoding="utf-8")
        return True
    return False


def _read_lf(path: Path) -> bytes:
    # Normalize to LF so vendored files match git blobs regardless of the
    # platform checkout's line-ending convention.
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sources(stamp_only: bool) -> list[Path]:
    if stamp_only:
        return []
    return sorted(
        f
        for f in SRC.glob("*.py")
        if f.name not in _SKIP and not f.name.startswith(".")
    )


def _stale(target: Path, stamp_only: bool) -> list[str]:
    """Vendored modules in the target that no longer exist upstream."""
    if stamp_only:
        return []
    return [
        f.name
        for f in target.glob("*.py")
        if f.name not in _SKIP and not (SRC / f.name).exists()
    ]


def _manifest_paths(target: Path, entries: list[str] | None) -> list[Path]:
    manifests: list[Path] = []
    for entry in entries or []:
        manifests.extend(target / m.strip() for m in entry.split(",") if m.strip())
    return manifests


def _check(target: Path, entries: list[str] | None, stamp_only: bool) -> int:
    """Read-only drift check. Prints a list of differences, returns 0 or 1."""
    version = _upstream_version()
    problems: list[str] = []
    for src in _sources(stamp_only):
        dst = target / src.name
        if not dst.is_file():
            problems.append(f"missing:  {src.name} (upstream file absent from target)")
        elif _read_lf(dst) != _read_lf(src):
            problems.append(f"differs:  {src.name} (content differs from upstream)")
    for name in _stale(target, stamp_only):
        problems.append(f"stale:    {name} (no longer upstream; a sync would remove it)")
    for manifest in _manifest_paths(target, entries):
        if not manifest.is_file():
            problems.append(
                f"manifest: {manifest} not found "
                "(--manifest is resolved relative to the target dir)"
            )
        elif _stamp_manifest(manifest, version, write=False):
            problems.append(f"manifest: {manifest} would be re-stamped to {version}")
    if problems:
        print(f"tameru {version} -> {target}: OUT OF SYNC")
        for line in problems:
            print(f"  {line}")
        print("run without --check to apply")
        return 1
    print(f"tameru {version} -> {target}: in sync")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("target", help="vendored plugin directory (must exist)")
    p.add_argument(
        "--manifest",
        default=None,
        help=(
            "manifest file(s) to version-stamp, comma-separated or repeated. "
            "Resolved relative to the TARGET dir, not the cwd "
            "(e.g. --manifest ../plugin.yaml)"
        ),
        action="append",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--stamp-only",
        action="store_true",
        help="glue-only target: stamp the manifest version, copy no modules",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help=(
            "read-only drift check: list what a sync would change (differing, "
            "missing and stale modules, manifest stamps) and exit 1 if anything "
            "differs, else 0. Never writes"
        ),
    )
    args = p.parse_args(argv)

    target = Path(args.target)
    if not target.is_dir():
        print(f"error: target dir does not exist: {target}", file=sys.stderr)
        print("create it plus the harness-owned __init__.py/manifest first", file=sys.stderr)
        return 2

    if args.check:
        return _check(target, args.manifest, args.stamp_only)

    version = _upstream_version()
    sources = _sources(args.stamp_only)
    changed = []
    for src in sources:
        dst = target / src.name
        payload = _read_lf(src)
        if dst.is_file() and _read_lf(dst) == payload:
            continue
        changed.append(src.name)
        if not args.dry_run:
            dst.write_bytes(payload)

    # Remove stale vendored modules that no longer exist upstream.
    stale = _stale(target, args.stamp_only)
    for name in stale:
        if not args.dry_run:
            (target / name).unlink()

    manifests = _manifest_paths(target, args.manifest)
    for m in manifests:
        if not m.is_file():
            print(
                f"warning: manifest not found: {m} "
                "(--manifest is resolved relative to the target dir)",
                file=sys.stderr,
            )
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
