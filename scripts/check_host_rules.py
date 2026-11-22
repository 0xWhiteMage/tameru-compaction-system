#!/usr/bin/env python3
"""Check the engine against the known host restrictions (docs/HOST-RESTRICTIONS.md).

    python scripts/check_host_rules.py            # CI: fail on anything not in the baseline
    python scripts/check_host_rules.py --list     # show every finding, allowed or not
    python scripts/check_host_rules.py --write-baseline   # maintainers only: record the current findings

The engine runs inside other people's agent harnesses, and those harnesses review what a plugin may do. This script reads
``src/tameru/*.py`` with the ``ast`` module (no regular expressions over source text) and records, per file, the things a host
reviewer asks about: network, child processes, dynamic code, file writes, home-directory paths, environment reads, imports that are
not the standard library, and monkey-patching. Findings that already exist are listed with a reason in
``scripts/host_rules_baseline.json``; **any finding not in that file fails the check.** Adding to the baseline needs a maintainer's
sign-off (the file is covered by CODEOWNERS) and a reason that a host reviewer would accept.

It also checks that every module imports under ``python -I -S`` (no site-packages, no user site, no PYTHON* variables), which is how a
host may start the engine, and that no compiled or unreviewable payload is tracked under ``src/``.

Standard library only; it must keep working with the same interpreter the engine supports (Python 3.10+).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "tameru"
BASELINE = Path(__file__).resolve().parent / "host_rules_baseline.json"

NETWORK_MODULES = {
    "socket", "ssl", "http", "http.client", "http.server", "urllib.request", "urllib.error", "ftplib", "smtplib", "poplib", "imaplib",
    "telnetlib", "xmlrpc", "xmlrpc.client", "socketserver", "asyncio.streams", "requests", "httpx", "aiohttp", "websockets", "urllib3",
}
PROCESS_MODULES = {"subprocess", "multiprocessing", "pty", "pexpect", "sh"}
NATIVE_AND_SERIALISED_MODULES = {"ctypes", "cffi", "pickle", "cPickle", "marshal", "shelve", "dill", "cloudpickle"}
DYNAMIC_CALLS = {"eval", "exec", "__import__"}
PROCESS_CALLS = {"os.system", "os.popen", "os.execv", "os.execl", "os.execvp", "os.execlp", "os.spawnv", "os.spawnl", "os.startfile"}
WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename", "replace", "symlink_to", "hardlink_to"}
WRITE_FUNCTIONS = {
    "os.replace", "os.rename", "os.remove", "os.unlink", "os.makedirs", "os.mkdir", "os.rmdir", "os.removedirs", "os.symlink", "os.link",
    "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.rmtree", "tempfile.mkstemp",
    "tempfile.mkdtemp", "tempfile.NamedTemporaryFile", "tempfile.TemporaryFile", "tempfile.TemporaryDirectory",
}
HOME_CALLS = {"Path.home", "pathlib.Path.home", "os.path.expanduser", "os.path.expandvars", "tempfile.gettempdir"}
CREDENTIAL_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.IGNORECASE)
# environment variables the engine may read, and why (the summary route is opt-in and a host never
# enables it; TAMERU_CACHE_MAX_BYTES sizes the process-wide content cache, default 64 MB)
ALLOWED_ENV = {"TAMERU_SUMMARY_ENDPOINT", "TAMERU_SUMMARY_ALLOW_REMOTE", "TAMERU_SUMMARY_MODELS", "TAMERU_SUMMARY_TIMEOUT", "TAMERU_CACHE_MAX_BYTES"}
BINARY_SUFFIXES = {".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib", ".exe", ".wasm", ".a", ".o", ".zip", ".whl", ".egg", ".jar", ".7z", ".rar"}
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
MAGIC = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\x00asm")

RULES = {
    "network": "imports a network module (hosts review every network call; the engine is local-only unless a caller opts in)",
    "process": "starts or imports a child-process facility (hosts forbid unapproved child processes)",
    "dynamic-code": "evaluates or imports code dynamically, or loads native code or pickled data",
    "file-write": "writes, creates or removes files or directories (the engine must write nowhere a caller did not name)",
    "home-path": "builds a path from the home or temp directory (a host decides where its data lives, not the engine)",
    "env-read": "reads an environment variable that is not on the allowed list",
    "credential": "reads something that looks like a credential",
    "host-import": "imports something that is not the standard library, the engine itself or a declared optional extra",
    "monkey-patch": "rebinds attributes or module tables of other code at runtime",
    "binary": "a compiled, archived or otherwise unreadable payload is tracked under src/",
    "isolated-import": "does not import under python -I -S",
}


def dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def stdlib_names() -> set[str]:
    return set(sys.stdlib_module_names)  # Python 3.10 and later


STDLIB = stdlib_names()


class Scan(ast.NodeVisitor):
    def __init__(self, path: Path, optional: set[str]) -> None:
        self.path = path
        self.optional = optional
        self.found: list[tuple[str, str, int]] = []  # (rule, detail, line)

    def add(self, rule: str, detail: str, node: ast.AST) -> None:
        self.found.append((rule, detail, getattr(node, "lineno", 0)))

    def module(self, name: str, node: ast.AST) -> None:
        top = name.split(".")[0]
        if name in NETWORK_MODULES or top in NETWORK_MODULES or any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES if "." in m):
            self.add("network", name, node)
        if top in PROCESS_MODULES:
            self.add("process", name, node)
        if top in NATIVE_AND_SERIALISED_MODULES or top == "importlib":
            self.add("dynamic-code", name, node)
        if top == "tameru" or top in STDLIB or top in {"__future__"}:
            return
        if top in self.optional:
            return
        self.add("host-import", name, node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.module(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:  # relative: the engine itself
            return
        if node.module:
            self.module(node.module, node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted(node.func)
        if isinstance(node.func, ast.Name) and node.func.id in DYNAMIC_CALLS:
            self.add("dynamic-code", node.func.id + "()", node)
        if name in PROCESS_CALLS:
            self.add("process", name + "()", node)
        if name in WRITE_FUNCTIONS:
            self.add("file-write", name + "()", node)
        if name in HOME_CALLS:
            self.add("home-path", name + "()", node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_METHODS and name not in {"str.replace"}:
            # str.replace is everywhere: only count the pathlib-style call shapes, by arity and by receiver
            receiver = dotted(node.func.value) or ""
            if node.func.attr == "replace" and not (len(node.args) == 1 and not node.keywords) :
                pass
            elif node.func.attr == "replace" and not re.search(r"(path|dir|file|tmp|temp|target|dest|root)", receiver, re.IGNORECASE):
                pass
            else:
                self.add("file-write", "." + node.func.attr + "()", node)
        is_method_open = isinstance(node.func, ast.Attribute) and node.func.attr == "open" and name not in {"webbrowser.open"}
        if (isinstance(node.func, ast.Name) and node.func.id == "open") or name in {"io.open", "codecs.open", "gzip.open", "bz2.open", "lzma.open", "os.fdopen"} or is_method_open:
            mode = None
            position = 0 if is_method_open else 1
            if len(node.args) > position and isinstance(node.args[position], ast.Constant):
                mode = node.args[position].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if isinstance(mode, str) and set(mode) & set("wax+"):
                self.add("file-write", f"open(mode={mode!r})", node)
        if name in {"os.environ.get", "os.getenv", "os.environ.pop", "os.environ.setdefault"}:
            self.env(node.args[0] if node.args else None, node)
        if name in {"setattr", "delattr"} or (isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}):
            target = node.args[0] if node.args else None
            if not (isinstance(target, ast.Name) and target.id in {"self", "cls", "obj", "instance", "result", "report", "row"}):
                self.add("monkey-patch", "setattr/delattr on " + (dotted(target) or "an expression") if target else "setattr", node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if dotted(node.value) == "os.environ":
            key = node.slice
            self.env(key, node)
        if dotted(node.value) == "sys.modules" and isinstance(node.ctx, (ast.Store, ast.Del)):
            self.add("monkey-patch", "sys.modules write", node)
        self.generic_visit(node)

    def env(self, key: ast.AST | None, node: ast.AST) -> None:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            name = key.value
            if CREDENTIAL_NAME.search(name) and name not in ALLOWED_ENV:
                self.add("credential", f"environment variable {name}", node)
            elif name not in ALLOWED_ENV:
                self.add("env-read", name, node)
        else:
            self.add("env-read", "(a name computed at run time)", node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                base = dotted(target.value)
                # assigning to an attribute of another module, e.g. os.environ.x = ... or module.attr = ...
                if base and base.split(".")[0] in STDLIB and base.split(".")[0] not in {"self"}:
                    self.add("monkey-patch", f"assignment to {dotted(target)}", node)
        self.generic_visit(node)


def optional_extras() -> set[str]:
    """Imports allowed only because pyproject declares them as optional extras (and the engine imports them lazily)."""
    return {"sentence_transformers", "numpy", "torch"}


def scan_sources() -> list[tuple[str, str, str, int]]:
    out: list[tuple[str, str, str, int]] = []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scan = Scan(path, optional_extras())
        scan.visit(tree)
        for rule, detail, line in scan.found:
            out.append((path.name, rule, detail, line))
    return out


def scan_binaries() -> list[tuple[str, str, str, int]]:
    out: list[tuple[str, str, str, int]] = []
    try:
        tracked = subprocess.run(["git", "ls-files", "src"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        tracked = [str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*") if p.is_file()]
    for name in tracked:
        path = ROOT / name
        if not path.is_file():
            continue
        lowered = name.lower()
        if Path(lowered).suffix in BINARY_SUFFIXES or lowered.endswith(ARCHIVE_SUFFIXES) or "__pycache__" in lowered:
            out.append((name, "binary", "compiled or archived file", 0))
            continue
        head = path.read_bytes()[:8]
        if any(head.startswith(magic) for magic in MAGIC):
            out.append((name, "binary", "executable or native-library header", 0))
    return out


def scan_isolated_import() -> list[tuple[str, str, str, int]]:
    """Every module must import with no site-packages and no user site: `python -I -S`."""
    out: list[tuple[str, str, str, int]] = []
    code = "import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module('tameru.' + sys.argv[2])"
    for path in sorted(SRC.glob("*.py")):
        if path.stem == "__init__":
            continue
        result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(SRC.parent), path.stem], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            last = (result.stderr.strip().splitlines() or ["failed"])[-1]
            out.append((path.name, "isolated-import", last[:160], 0))
    return out


def key_of(file: str, rule: str, detail: str) -> str:
    return f"{file}::{rule}::{detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="print every finding, allowed or not")
    parser.add_argument("--write-baseline", action="store_true", help="record the current findings as the baseline (maintainers only)")
    parser.add_argument("--no-isolated-import", action="store_true", help="skip the python -I -S import check (faster)")
    args = parser.parse_args()

    findings = scan_sources() + scan_binaries() + ([] if args.no_isolated_import else scan_isolated_import())
    counts: Counter[str] = Counter(key_of(f, r, d) for f, r, d, _ in findings)

    if args.write_baseline:
        previous = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {"reasons": {}, "allowed": {}}
        data = {"reasons": previous.get("reasons", {}), "allowed": dict(sorted(counts.items()))}
        BASELINE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {len(counts)} baseline entries to {BASELINE.relative_to(ROOT)}; every rule needs a reason under 'reasons'")
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {"reasons": {}, "allowed": {}}
    allowed: dict[str, int] = baseline.get("allowed", {})
    violations: list[str] = []
    for key, count in sorted(counts.items()):
        if count > allowed.get(key, 0):
            file, rule, detail = key.split("::", 2)
            lines = sorted({line for f, r, d, line in findings if key_of(f, r, d) == key and line})
            where = f" (line {', '.join(map(str, lines[:4]))})" if lines else ""
            extra = f" [baseline allows {allowed.get(key, 0)}, found {count}]" if key in allowed else ""
            violations.append(f"  {file}{where}: {rule}: {detail}{extra}\n      {RULES[rule]}")
    stale = sorted(key for key in allowed if counts.get(key, 0) < allowed[key] and key.split('::')[1] != 'isolated-import')

    if args.list:
        for file, rule, detail, line in sorted(findings):
            status = "allowed" if counts[key_of(file, rule, detail)] <= allowed.get(key_of(file, rule, detail), 0) else "NOT ALLOWED"
            print(f"{status:11} {file}:{line}: {rule}: {detail}")

    if stale:
        print("note: these baseline entries no longer occur; remove them so the baseline only shrinks:")
        for key in stale:
            print("  " + key)
    if violations:
        print("Host restriction check FAILED. These findings are not in scripts/host_rules_baseline.json:\n")
        print("\n".join(violations))
        print("\nRead docs/HOST-RESTRICTIONS.md. If the change is genuinely needed, say why in the PR and ask a maintainer to extend the baseline.")
        return 1
    print(f"Host restriction check passed: {len(findings)} findings, all in the baseline ({len(allowed)} entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
