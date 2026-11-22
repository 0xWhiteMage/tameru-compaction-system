"""Shared immutable patterns for private fingerprint normalizers."""
import re

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEXRUN_RE = re.compile(r"[0-9a-f]{6,}")
_DIGITS_RE = re.compile(r"\d+")
