"""Local extractive, query-aware context compression.

Independent implementation. No Baseline RAG API, no their weights, no
off-box calls. Keep original wording; drop whole blocks; fail open when
the query signal is too weak to justify a cut.
"""

from __future__ import annotations

import array
import bisect
import collections
import contextvars
import functools
import hashlib
import itertools
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
import unicodedata
import warnings
import dataclasses
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ._fingerprint_patterns import _DIGITS_RE
from ._protect_patterns import compile_pin_patterns
from .agent_formats import (
    GUTTER_RE as _AGENT_GUTTER_RE,
    apply_agent_adapters,
    detect_grep_lines,
    detect_test_runner,
    detect_unified_diff,
    is_numbered_code,
    is_diagnostic_line,
    is_kubectl_status_line,
    preprocess_test_output,
    rejects_table,
    _env_is_sensitive,
    _env_match,
)
from .contract_gates import (
    GENERIC_WORDS,
    distinctive_query_terms,
    han_units,
    query_has_distinctive_selectors,
    query_profile,
)
from .folding import fold_lossless, json_brief, mask_template
from .format_adapters import FILLER_WORDS
from .gap_kind import call_gap_marker, gap_accepts_kind
from .markers import REDACTED_MARKER, marker_name as _marker_name
from .industrial import IndustrialLimits, IndustrialResult, industrial_preprocess
from .structured_reports import REPORT_FORMATS, loads_for_rewrite, report_format
from .supersession import (
    apply_supersession,
    _append_scoped,
    _document_headers,
    _document_scopes,
    _end_scope,
    _supersedes,
)
from .unicode_profile import (
    count_token_units,
    script_of,
    search_units,
    token_units,
    unicode_safety_counts,
)

try:  # optional semantic tier — never required
    from .semantic import resolve_tier
except ImportError:  # direct-script use without package context
    def resolve_tier(tier):
        return tier

# Public re-export (``from tameru.compress_context import fold_lossless``); naming it here
# keeps the import from looking unused.
_REEXPORTED = (fold_lossless,)

try:
    DEFAULT_CCR_DIR = Path.home() / ".tameru" / "cache" / "context-compress-ccr"
except Exception:
    DEFAULT_CCR_DIR = Path(tempfile.gettempdir()) / ".tameru" / "cache" / "context-compress-ccr"
# Engine release this module ships in; the release bump keeps it in step with
# pyproject.toml and src/tameru/__init__.py.
ENGINE_VERSION = "1.10.0"

from .content_cache import CACHE as _CONTENT, ContentCache, _MISS, content_key, content_memo

# S7: the scored-blocks memo is byte-capped too, under its own budget.
_SCORED = ContentCache(max_bytes=16 << 20)

# S7: inputs past ``_HUGE_CHARS`` take a streaming head/error-sampler/tail path
# (``confidence_basis="partial"``); past ``_HUGE_MAX_CHARS`` the call fails open with
# the closed reason ``too_large`` and no analysis.
_HUGE_CHARS = 2_000_000
_HUGE_MAX_CHARS = 8_000_000
_HUGE_EDGE_CHARS = 393_216
_HUGE_ERR_CHARS = 262_144
_HUGE_ERR_MARKERS = (
    "error", "traceback", "exception", "errno", "denied",
    "failed", "fatal", "panic", "stderr", "assert",
)

# Shape of CompressResult for hosts: 4 since 1.10.0 (query_specific; schema 3 added
# fact_lines_dropped; schema 2 added confidence_basis, stable_key, dropped, result_schema, preset).
RESULT_SCHEMA = 4
CCR_TTL_SECONDS = 6 * 60 * 60
CCR_MAX_CLOCK_SKEW_SECONDS = 5 * 60
FREEZE_MAX_DECISIONS = 4096
MAX_QUERY_TEMPLATE_MATCHES = 64
CCR_SWEEP_MAX_RECORDS = 256
_CCR_TEMP_GRACE_SECONDS = 600
MAX_SUMMARY_RESPONSE_BYTES = 1_000_000
DEFAULT_SUMMARY_ENDPOINT = "http://127.0.0.1:18000/v1/chat/completions"
DEFAULT_SUMMARY_MODELS = (
    "Qwen3.8-27B-NVFP4",
    "Qwen3.6 APEX MTP Compact",
    "DeepSeek V4 Flash 0713",
)
DEFAULT_SUMMARY_TIMEOUT = 30.0
_CCR_HASH_RE = re.compile(r"^[0-9a-f]{24}$")
_CCR_SWEEP_CURSOR: dict[str, int] = {}
_CCR_SWEEP_LOCK = threading.Lock()

# Degraded scoring view (opt-in, JEV-inspired): on input size-limit breaches,
# score a bounded head+tail view per block while emitted output stays
# byte-exact. The oversize factor bounds total work when limits are bypassed.
_DEGRADED_VIEW_HEAD = 400
_DEGRADED_VIEW_TAIL = 200
_DEGRADED_OVERSIZE_FACTOR = 4

# Secrets screen (dsh-jev-pre-compaction inspired): never persist probable
# credentials to the CCR store. Conservative patterns only — private key
# blocks, well-known token prefixes, JWTs, and long quoted assignments.
_SECRETS_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
    r"|\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|(?i:\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
    r"\s*[:=]\s*[\"'][^\"'\s]{16,}[\"'])"
    r"|\bAIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"
    r"|\b(?:sk|rk)_live_[A-Za-z0-9]{16,}"
    r"|(?i:\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{20,})"
    r"|(?i:\b(?:[A-Za-z0-9_]+_)?(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
    r"\s*[:=]\s*"
    # 1.4.1 red-team: an unquoted value that is code (a call, an index, a
    # ``${...}`` / ``<...>`` placeholder, an attribute chain, a snake_case
    # variable such as ``api_key=fallback_api_key,``) names no credential.
    # The exclusions are bounded, as in ``_SECRET_NOT_CODE``.
    r"(?![^\s\"']{0,256}[(\[{<$])(?!(?:[A-Za-z_]\w{0,63}\.){1,8}[A-Za-z_]\w{0,63}(?![^\s,;)\]}]))"
    r"(?![a-z_](?=[a-z0-9_]{0,63}_)[a-z0-9_]{0,63}(?![^\s,;)\]}]))"
    r"[^\s\"']{16,})"
    # 1.4.1 fix-all: the code exclusions above also let through unquoted
    # snake_case passphrases and dotted passwords. A whole-line ``.env`` /
    # shell assignment (``DB_PASSWORD=correct_horse_battery_staple``, no
    # spaces around ``=``) or a YAML ``key: value`` line still names one: the
    # value runs to the end of the line and does not end in ``,`` ``;`` ``)``
    # (a keyword argument on its own line). YAML keeps the attribute-chain
    # exclusion (``api_key: pydantic.types.SecretStr`` is an annotation).
    r"|(?im:^[ \t]*(?:export[ \t]+)?(?:[A-Za-z0-9_]+_)?"
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
    r"=(?![^\s\"']*[(\[{<$])[^\s\"']{15,}[^\s\"',;)][ \t]*\r?$)"
    r"|(?im:^[ \t]*(?:[A-Za-z0-9_]+_)?"
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
    r":[ \t]+(?![^\s\"']*[(\[{<$])(?!(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*[ \t]*$)"
    r"[^\s\"']{15,}[^\s\"',;)][ \t]*\r?$)"
)

# Recursion guard markers: output Tameru itself produced. Both wrapper tags
# are listed: ``</compressed_context`` is not a substring of the open tag.
_RECURSION_MARKERS = ("<compressed_context", "</compressed_context", "[CC-Retrieve:", "[tameru:report ")

# Already-elided standalone marker lines ([…] or the counted omitted form): a
# conservative no-op check so previously compressed text short-circuits instead
# of being reprocessed. This does NOT prove the marker was authored by Tameru;
# inline mentions inside normal lines deliberately do not match.
_DEFAULT_ELISION_LINE = re.compile(r'^[ \t]*\[…(?: [0-9]{1,12} [^\]\r\n]{1,120} omitted …)?\][ \t]*\r?$', re.MULTILINE)


# Perf (v1.5.0): the pure text-level analyses below are memoized for texts of
# a few KB or more, newest few entries only. A host that compresses the same
# output again (a retry with another budget, a brief after an extract, an
# error check on the original) pays for the scan once. Results are immutable
# or copied on the way out, so a caller can never alter a cached value.
_MEMO_MIN_CHARS = 2048
# Texts above this are not remembered: six entries of an 8 MB input across a dozen
# caches would pin hundreds of MB in a long-lived server process. Ordinary tool
# output is far below it.
_MEMO_MAX_CHARS = 1_000_000
_MEMO_MAX_QUERY_CHARS = 32_768
_MEMO_ENTRIES = 6


# v1.5.0 red-team: credential shapes ``_SECRETS_RE`` did not know. A false
# negative here means a host's recovery store, ledger or CCR archive keeps a
# live credential, so every addition is anchored on a literal prefix or a
# credential keyword (and bounded, so it stays linear on hostile text):
# AWS temporary keys, Google OAuth / refresh tokens, Slack app tokens and
# webhooks, Stripe test / webhook secrets, Hugging Face, npm, PyPI, SendGrid,
# GitLab, Docker, DigitalOcean, Shopify, Square and Twilio tokens, Telegram bot
# tokens, Azure storage keys and SAS signatures, ``scheme://user:password@host``
# connection strings, HTTP Basic credentials, ``sshpass -p`` / ``curl -u``, and
# quoted-key JSON / YAML assignments (``"SecretAccessKey": "..."``) plus the
# keywords ``secret_access_key``, ``secret_key``, ``client_secret``,
# ``session_token``, ``refresh_token``, ``private_key``, ``signing_key``
# and upper-case ``*_TOKEN=`` variables.
_SECRET_KEYWORD = (
    r"(?:[A-Za-z0-9_]{1,64}[_-])?(?:password|passwd|secret|api[_-]?key|access[_-]?token"
    r"|auth[_-]?token|secret[_-]?(?:access[_-]?)?key|client[_-]?secret"
    r"|(?:session|refresh|bearer|id|security)[_-]?token|private[_-]?key|signing[_-]?key"
    r"|db[_-]?pass|mysql[_-]?pwd|pgpassword|rediscli[_-]?auth)"
)
_SECRET_NEW_KEYWORD = (
    r"(?:[A-Za-z0-9_]{1,64}[_-])?(?:secret[_-]?(?:access[_-]?)?key|client[_-]?secret"
    r"|(?:session|refresh|bearer|id|security)[_-]?token|private[_-]?key|signing[_-]?key"
    r"|db[_-]?pass|mysql[_-]?pwd|pgpassword|rediscli[_-]?auth)"
)
# The three exclusions are bounded: an unbounded ``[^\s\"']*`` / ``\w*``
# rescans the remainder of a run from every candidate position (quadratic on
# crafted input). A chain or name longer than the bound escapes the
# exclusion and is screened — over-flagging a credential is the safe side.
_SECRET_NOT_CODE = (
    r"(?![^\s\"']{0,256}[(\[{<$])(?!(?:[A-Za-z_]\w{0,63}\.){1,8}[A-Za-z_]\w{0,63}(?![^\s,;)\]}]))"
    r"(?![a-z_](?=[a-z0-9_]{0,63}_)[a-z0-9_]{0,63}(?![^\s,;)\]}]))"
)
_SECRETS_EXTRA_RE = re.compile(
    r"\bASIA[0-9A-Z]{16}\b"
    r"|\bya29\.[A-Za-z0-9_-]{20,}"
    r"|\b1//0[A-Za-z0-9_-]{40,}"
    r"|\bhf_[A-Za-z0-9]{30,}"
    r"|\bnpm_[A-Za-z0-9]{30,}"
    r"|\bpypi-AgE[A-Za-z0-9_-]{40,}"
    r"|\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"
    r"|\bglpat-[A-Za-z0-9_-]{20,}"
    r"|\bdckr_pat_[A-Za-z0-9_-]{20,}"
    r"|\bxapp-\d-[A-Z0-9]{6,}-\d{6,}-[A-Za-z0-9]{16,}"
    r"|hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{16,}"
    r"|discord(?:app)?\.com/api/webhooks/\d{6,}/[A-Za-z0-9_-]{20,}"
    r"|\b(?:sk|rk)_test_[A-Za-z0-9]{16,}"
    r"|\bwhsec_[A-Za-z0-9]{24,}"
    r"|\bdop_v1_[a-f0-9]{40,}"
    r"|\bshp(?:at|ca|pa|ss)_[a-f0-9]{32}"
    r"|\bsq0(?:atp|csp)-[A-Za-z0-9_-]{22,}"
    r"|\bSK[0-9a-f]{32}\b"
    r"|\bkey-[0-9a-f]{32}\b"
    r"|(?i:(?<![A-Za-z0-9])_auth_?token\s*=\s*[^\s\"']{12,})"
    r"|\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"
    r"|(?:AccountKey|SharedAccessKey)=[A-Za-z0-9+/]{30,}"
    r"|[?&]sig=[A-Za-z0-9%+/]{30,}"
    # scheme://[user]:password@host (the password holds no "/", "@" or space)
    r"|\b[A-Za-z][A-Za-z0-9+.-]{1,20}://[^\s:/@]{0,64}:"
    r"(?![<${%*{]|(?i:pass(?:word|wd)?|secret|token|xxx+|changeme|example|user(?:name)?)@)"
    r"[^\s/@]{4,128}@[A-Za-z0-9._\[-]"
    r"|(?i:\bauthorization\s*:\s*basic\s+[A-Za-z0-9+/]{12,})"
    r"|\bsshpass\s+-p\s*\S{6,}"
    r"|\bcurl\b[^\n]{0,200}?\s(?:-u|--user)[ =]\S{1,64}:\S{6,}"
    # quoted key or value: ``"SecretAccessKey": "..."``, ``api_key = '...'``
    r"|(?i:\b" + _SECRET_KEYWORD + r"[\"']?\s*[:=]\s*"
    r"(?:\"(?=[^\"\s]*\d)[^\"\s]{16,}\"|'(?=[^'\s]*\d)[^'\s]{16,}'))"
    # unquoted value of the keywords the original rule does not list
    r"|(?i:\b" + _SECRET_NEW_KEYWORD + r"[\"']?\s*[:=]\s*" + _SECRET_NOT_CODE
    + r"(?=[^\s\"']{0,256}\d)[^\s\"']{16,}(?<![,;)\]}])(?![^\s\"']))"
    # ``GITHUB_TOKEN=ghx...``: upper-case variable names are environment
    # variables, not code
    r"|\b(?:[A-Z][A-Z0-9_]{0,60}_)?(?:TOKEN|ACCESS_KEY)\s*[:=]\s*[\"']?" + _SECRET_NOT_CODE
    # The lookahead and the value are both bounded: an unbounded ``*\d``
    # lookahead rescans the remainder of a digit-free run from every keyword
    # hit, which is quadratic on crafted input such as ``TOKEN=`` repeated.
    + r"(?=[A-Za-z0-9_./+=-]{0,512}\d)[A-Za-z0-9_./+=-]{19,512}[A-Za-z0-9_/+=](?![^\s\"'])"
    # Short literal credentials with both digits and punctuation; code references stay excluded.
    r"|(?i:\b" + _SECRET_KEYWORD + r"[\"']?\s*[:=]\s*[\"']?" + _SECRET_NOT_CODE
    + r"(?=[^\s\"']{0,15}\d)(?=[^\s\"']{0,15}[!@#%&*+=?/~])"
    r"[A-Za-z0-9!@#%&*+=?/~._-]{4,15}(?=[\"'\s,;}\]]|$))"
    # A complete .pgpass record: host:port:database:user:password. Escaped colons are field data.
    r"|(?m:^[ \t]*(?:\\[^\r\n]|[^:\\\s#]){1,256}:(?:\*|[0-9]{1,5}):"
    r"(?:\\[^\r\n]|[^:\\\s]){1,256}:(?:\\[^\r\n]|[^:\\\s]){1,256}:"
    r"(?:\\[^\r\n]|[^:\\\r\n]){1,1024}\r?$)"
)

# Every alternative of ``_SECRETS_RE`` / ``_SECRETS_EXTRA_RE`` contains one of
# these literals: the first group exactly (case-sensitive), the second group
# case-insensitively (the credential keywords). On ASCII text a plain substring
# test can therefore rule a text out without running the regexes, which have to
# try every alternative at every position (~0.2 s on 650 KB of ordinary log).
# Non-ASCII text keeps the regexes alone: Unicode case folding (Kelvin sign,
# long s) makes the case-insensitive groups match letters that ``lower()`` does
# not map. Keep the lists in step with the patterns: a test compares the
# prefiltered scan with the bare regexes.
_SECRET_LITERALS = (
    "-----BEGIN ", "AKIA", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_",
    "xox", "sk-", "eyJ", "AIza", "_live_",
    "ASIA", "ya29.", "1//0", "hf_", "npm_", "pypi-AgE", "SG.", "glpat-", "dckr_pat_",
    "xapp-", "hooks.slack.com", "/api/webhooks/", "_test_", "whsec_", "dop_v1_", "shp",
    "sq0", "SK", ":AA", "Key=", "sig=", "://", "sshpass", "curl", "TOKEN", "ACCESS_KEY", "key-",
)
# The one alternative that has no literal: a ``.pgpass`` record ``host:port:database:user:password`` at the start of a
# line. A bare ":" used to stand for it, which every timestamp satisfies, so no log was ever ruled out. This hint is the
# record's first three fields and their colons (a superset of the full pattern): an ordinary log line has a space where
# the third field must end, so it does not match and the two long patterns are skipped.
_PGPASS_HINT_RE = re.compile(
    r"(?m:^[ \t]*(?:\\[^\r\n]|[^:\\\s#]){1,256}:(?:\*|[0-9]{1,5}):(?:\\[^\r\n]|[^:\\\s]){1,256}:)"
)
_SECRET_FOLDED_LITERALS = (
    "password", "passwd", "secret", "api_key", "api-key", "apikey", "access_token",
    "access-token", "accesstoken", "auth_token", "auth-token", "authtoken", "bearer",
    "token", "private", "signing", "basic",
    "dbpass", "db_pass", "db-pass", "mysqlpwd", "mysql_pwd", "mysql-pwd",
    "pgpassword", "rediscliauth", "rediscli_auth", "rediscli-auth",
)


def _secret_scan(text: str) -> bool:
    if text.isascii() and not any(lit in text for lit in _SECRET_LITERALS):
        folded = text.lower()
        if not any(lit in folded for lit in _SECRET_FOLDED_LITERALS) and _PGPASS_HINT_RE.search(text) is None:
            return False
    return _SECRETS_RE.search(text) is not None or _SECRETS_EXTRA_RE.search(text) is not None


@content_memo("contains_secret", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _contains_secret_cached(text: str) -> bool:
    return _secret_scan(text)


def _contains_secret(text: str) -> bool:
    if not text:
        return False
    if type(text) is str and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS:
        return _contains_secret_cached(text)
    return _secret_scan(text)


def contains_secret(text: str) -> bool:
    """Public alias of :func:`_contains_secret` (v1.4.0).

    True when ``text`` carries probable credential material (private-key
    headers, well-known token prefixes, JWTs, long quoted assignments).
    Callers that persist or forward text — the CCR store, a host plugin's
    recovery store — use it to refuse to keep secrets. Conservative and
    deterministic; never raises on non-string input.
    """
    return _contains_secret(text if isinstance(text, str) else str(text or ""))

_STOP = {
    "what", "how", "does", "do", "the", "is", "are", "was", "were", "why",
    "when", "where", "which", "who", "whom", "whose", "this", "that", "with",
    "into", "about", "for", "and", "or", "of", "to", "a", "an", "in", "on",
    "it", "be", "as", "by", "from", "at", "if", "not", "can", "you", "we",
    "they", "them", "their", "our", "your", "please", "tell", "give", "show",
    "explain", "summarize", "summary", "function", "return", "class", "def",
    "import", "hmm",
} | {
    # es / pt / fr / it / de / id / ms / tr / pl question and function words
    "qué", "que", "cuál", "cuándo", "dónde", "cómo", "por", "porqué", "el",
    "los", "las", "una", "del", "con", "hubo", "qual", "quando", "onde",
    "porque", "como", "uma", "com", "foi", "les", "une", "des", "quoi",
    "quand", "où", "pourquoi", "comment", "che", "cosa", "dove", "perché",
    "gli", "der", "das", "was", "wann", "warum", "wie", "und", "apa",
    "kapan", "bila", "mengapa", "kenapa", "bagaimana", "yang", "ini", "itu",
    "dengan", "untuk", "pada", "neden", "nasıl", "kiedy", "gdzie",
    "dlaczego", "jak"
}
_KANA_STOP = frozenset("のはがをにでともへやかなねよわさぞぜしてただす")

_TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|"
    r"[\u4e00-\u9fff]|"
    r"[\u3040-\u30ff]{2,}|[\uac00-\ud7a3]{2,}|"
    r"[\u0600-\u06ff]{2,}|[\u0e00-\u0e7f]{2,}"
)

# Query-term tokens: like _TOKEN_RE, but a Latin word also takes letters with
# diacritics (Latin-1 Supplement letters, Latin Extended-A/B, Latin Extended
# Additional for Vietnamese) and combining marks, so "réplica" stays one term.
_TERM_TOKEN_RE = re.compile(
    r"[A-Za-z_\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\u1E00-\u1EFF]"
    r"[A-Za-z_\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\u1E00-\u1EFF0-9\u0300-\u036F]*"
    r"|\d+(?:\.\d+)?|"
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]|"
    r"[\u3040-\u30ff]{2,}|[\uac00-\ud7a3]{2,}|"
    r"[\u0600-\u06ff]{2,}|[\u0e00-\u0e7f]{2,}"
)
# Long punctuation runs (progress dots, rulers) cost real tokens: ~1 per 4
# chars. Only runs of 16+ so ordinary code/prose estimates do not move.
_ASCII_SYMBOL_RUN_RE = re.compile(r"[!-/:-@\[-`{-~]{16,}")
# A long unbroken word (base64 blobs, minified code, padding runs) is NOT one
# token — real tokenizers split it at a few chars per token, the same way the
# symbol-run term above treats punctuation runs. Counting it as a single
# _TOKEN_RE match undercounts a 1 MB line to ~4 tokens, which broke every
# savings gate downstream (the compressed render looked "longer" than an
# input that was estimated at 4 tokens, forcing a false fail-open).
_ASCII_WORD_RUN_RE = re.compile(r"[A-Za-z0-9_]{32,}")
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
# Slash is required between segments. `(?:/?[\w.-]+){2,}` is catastrophic
# on long hyphenated ids (acmecorp-genesis-v14-focused-node22-raw).
# v1.4.0 (E2): segments are bounded and a match may only start at the start of
# a run, so a 20k-char run without separators is linear instead of quadratic.
# Segments over 255 chars are not paths (hash blobs); normal inputs match as
# before.
_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]{1,255}/){2,}[\w.-]{1,255}")
_DOTTED_RE = re.compile(r"\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+\b")
_QUOTED_RE = re.compile(r"[\"']([^\"']{2,64})[\"']")
_CAPS_RE = re.compile(r"\b[A-Z]{2,24}\b")
_URI_RE = re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://\S+")
_FAST_ACCOUNTING_PUNCT = frozenset("§…×–—“”‘’")


_REUSE_PROBE_RESULT = True


def _finalize_reused_probe(res, query_as_given, anchor_lines) -> "CompressResult":
    receipt = dict(res.receipt) if res.receipt else res.receipt
    if receipt is not None:
        receipt["query_hash"] = hashlib.sha256(
            (query_as_given or "").encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:12]
        if anchor_lines:
            receipt["query_source"] = "error-anchored"
            receipt["anchor_lines"] = list(anchor_lines)
            if res.compression_risk == "low":
                receipt["risk"] = "medium"
    new_risk = "medium" if (anchor_lines and res.compression_risk == "low") else res.compression_risk
    return dataclasses.replace(res, receipt=receipt, compression_risk=new_risk)


def _rebase_anchored(res, caller_text, caller_query):
    """A reused probe ran with the anchors as its query"""
    extra: dict[str, Any] = {}
    if not res.fail_open:
        # The probe ran with the anchors as its query, so it rated itself on recall of terms taken from the text.
        # The result's confidence rests on the anchors, i.e. on the error fingerprints it kept.
        source = strip_ansi(_norm_newlines(caller_text))
        basis = _query_basis(caller_query, source, anchored=True)
        extra = {
            "confidence_basis": basis,
            "confidence": round(
                _compute_confidence(basis=basis, compressed=res.compressed_text, fail_open=False, original=source,
                                    recall=float(res.confidence or 0.0)), 3),
        }
    return dataclasses.replace(res, **extra)


@dataclass
class CompressResult:
    compressed_text: str
    original_tokens: int = 0
    kept_tokens: int = 0
    tokens_saved_pct: float = 0.0
    policy_name: str = "local-extractive"
    mode: str = "adaptive"
    keep_ratio: float = 1.0
    tokens_saved: int = 0
    kept_line_ratio: float = 1.0
    cache_prefix_applied: bool = False
    compression_risk: Optional[str] = None
    confidence: Optional[float] = None
    ccr: Optional[dict[str, Any]] = None
    content_type: str = "text"
    fail_open: bool = False
    frozen_blocks: int = 0
    reasons: list[str] = field(default_factory=list)
    verifier: Optional[dict[str, Any]] = None
    receipt: Optional[dict[str, Any]] = None
    # 1.10.0 (result schema 2), all additive:
    confidence_basis: str = "none"  # what the confidence rests on: see contract_gates.QUERY_BASES
    stable_key: str = ""  # sha256(engine version, text, query)[:16]: the same call has the same key
    dropped: tuple = ()  # up to 3 (category, line_count, first_locator) of what the output left out, largest first
    result_schema: int = RESULT_SCHEMA
    preset: Optional[str] = None  # the named option set the call used, when the host says so
    # 1.10.0 (result schema 3), additive:
    fact_lines_dropped: int = 0  # protected fact lines of the original absent from the output
    # 1.10.0 (result schema 4), additive:
    query_specific: Optional[bool] = None  # the caller query names distinctive selectors (S6 calibrator input)

    def __post_init__(self) -> None:
        self.tokens_saved = max(0, self.original_tokens - self.kept_tokens)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8", errors="surrogatepass")).hexdigest()


def _bounded_id_manifest(ids: Iterable[int], limit: int) -> list[int] | dict[str, Any]:
    ordered = sorted(int(item) for item in ids)
    resolved = max(0, int(limit))
    if len(ordered) <= resolved:
        return ordered
    head_count = (resolved + 1) // 2
    tail_count = resolved - head_count
    encoded = json.dumps(ordered, separators=(",", ":")).encode("ascii")
    return {
        "count": len(ordered),
        "head": ordered[:head_count],
        "tail": ordered[-tail_count:] if tail_count else [],
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _receipt_hashes(
    source: str,
    output: str,
    industrial: IndustrialResult,
    *,
    mode: str,
    strategy: str,
    budget_ratio: Optional[float],
    citations: bool,
) -> dict[str, str]:
    config = {
        "budget_ratio": budget_ratio,
        "citations": bool(citations),
        "limits": asdict(industrial.limits),
        "mode": mode,
        "strategy": strategy,
    }
    config_bytes = json.dumps(
        config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "source_sha256": _sha256_text(source),
        "output_sha256": _sha256_text(output),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    }


# v1.4.0 (E2): deleting the accounting punctuation and testing isascii() is the
# same predicate as the old per-character generator, but runs at C speed — the
# generator cost ~0.6 s per call on a 650 KB output that contains one "[…]".
_FAST_ACCOUNTING_DELETE = {ord(ch): None for ch in _FAST_ACCOUNTING_PUNCT}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    if type(text) is str and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS:
        return _estimate_tokens_cached(text)
    return _estimate_tokens(text)


@content_memo("estimate_tokens", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _estimate_tokens_cached(text: str) -> int:
    return _estimate_tokens(text)


_COUNT_CHUNK_CHARS = 262_144  # bounded match lists (~4 MiB) while counting a huge text's tokens


def _count_re_matches(pattern, text: str) -> int:
    """``len(pattern.findall(text))`` without the whole-text match list (S7): ``findall`` runs
    per ~256K slice cut at ``\\n`` — neither token pattern matches a newline, so the count is
    identical — and each slice's list is bounded."""
    n = pos = 0
    end = len(text)
    while pos < end:
        stop = text.find("\n", pos + _COUNT_CHUNK_CHARS)
        if stop < 0:
            stop = end
        n += len(pattern.findall(text, pos, stop))
        pos = stop
    return n


def _estimate_tokens(text: str) -> int:
    # S7: count matches instead of materializing them — the 8M ``too_large`` estimate's findall
    # lists were ~73 MiB. The ``translate`` copy runs only once the text is known non-ASCII.
    runs = sum((m.end() - m.start()) // 4 for m in _ASCII_SYMBOL_RUN_RE.finditer(text)) if len(text) >= 16 else 0
    if len(text) >= 32:
        runs += sum(
            (m.end() - m.start()) // 4 - 1  # the run already counted one _TOKEN_RE word
            for m in _ASCII_WORD_RUN_RE.finditer(text)
        )
    if text.isascii() or text.translate(_FAST_ACCOUNTING_DELETE).isascii():
        return max(1, _count_re_matches(_TOKEN_RE, text) + runs)
    return max(1, count_token_units(text) + runs)


def _norm_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


_CL_HEADING_RE = re.compile(r"^#{1,6}\s+")
_CL_FENCE_RE = re.compile(r"^(```|~~~)")
_CL_TRACE_RE = re.compile(
    r"^(Traceback|Caused by:|Error:|Exception:|[A-Za-z]+Error\b|at\s+\S+\(|\s*File\s+\".+\", line \d+"
    # 1.10.0 (structure): per-language chain heads and frames. Packaged Java/.NET exception types,
    # "Exception in thread", .NET "Unhandled exception." and "---> inner", Python chaining sentences,
    # Go goroutines and panics, JS "at fn (file:line:col)" frames and "[cause]".
    r"|Exception in thread\b|Unhandled exception\.|--->\s|Suppressed:|During handling of the above"
    r"|The above exception was|goroutine \d+ \[|panic:|\[cause\]"
    r"|from\s+\S+:\d+:in\s|[\w./-]+:\d+:in\s+[`']"
    r"|#\d+\s+\S+\(\d+\):|#\d+\s+\{main\}|Stack trace:$"
    r"|(?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*(?:Exception|Error)\b(?::|\s|$)"
    r"|at\s+(?:async\s+)?(?:new\s+)?[^\s(]+\s\([^()\s]*:\d+:\d+\)|at\s+(?:async\s+)?\S+:\d+:\d+$)"
)
_CL_LOG_RE = re.compile(
    r"^\[?(20\d\d-\d\d-\d\d|20\d\d/\d\d/\d\d[ T]\d\d:\d\d:\d\d|\d\d:\d\d:\d\d|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d|INFO|WARN|WARNING|ERROR|DEBUG|TRACE|ERR|FAIL|FATAL|OK|(?:info|warn|fail|crit|dbug|trce):)\]?"
)
_CL_LOGFMT_RE = re.compile(
    r"^(?:ts|time|timestamp|t)=[^\s]+(?:\s+level=[A-Za-z0-9_.]+|\s+.*\slevel=[A-Za-z0-9_.]+)"
    r"|^level=[A-Za-z0-9_.]+(?:\s+(?:msg=|message=)|\s+.*\s(?:msg=|message=))"
)

def _cl_logfmt_pairs(t: str) -> int:
    return len(re.findall(r"(?:^|\s)[A-Za-z_][A-Za-z0-9_.]*=", t))
_CL_IMPORT_RE = re.compile(r"^(import|from)\s+|^#include\s+|^using\s+")
_CL_DEFINITION_RE = re.compile(
    r"^(def|class|async\s+def|function|const|let|var|public|private|protected|static|fn|func)\b"
)
_CL_LIST_RE = re.compile(r"^[-*+]\s+|\d+\.\s+")
_CL_TABLE_RE = re.compile(r"^\|.*\|$")
_CL_CHAT_RE = re.compile(r"^(User|Assistant|System|Tool|Developer):")
_CL_CHAT_TAG_RE = re.compile(r"^\[(user|assistant|system|tool|developer)\]", re.IGNORECASE)
# Perf: the two chat probes merge into one scan; the tag alternative keeps
# its own (?i:) scope so the name alternative stays case-sensitive.
_CL_CHAT_ANY_RE = re.compile("(?:" + _CL_CHAT_RE.pattern + ")|(?i:" + _CL_CHAT_TAG_RE.pattern + ")")
_CL_JSON_KEY_RE = re.compile(r'^"[A-Za-z0-9_]+"\s*:')
_CL_COMMENT_RE = re.compile(r"^(\/\/|#|\/\*|\*)")


def _is_trace_line(line: str) -> bool:
    """``classify_line(line) == "trace"`` without the checks that cannot win:
    a heading starts with ``#`` and a fence with a backtick or tilde, which no
    trace pattern can start with."""
    t = line.strip()
    return bool(t) and _CL_TRACE_RE.match(t) is not None


_SYSLOG_PREFIX_RE = re.compile(
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d\d:\d\d:\d\d \S+ [\w.@/()-]+(?:\[\d+\])?: "
    r"|^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d) \S+ [\w.@/()-]+(?:\[\d+\])?: "
    r"|^\[\s*\d+\.\d{3,}\] "
)


_KLOG_LINE_RE = re.compile(r"^[IWEF]\d{4} \d\d:\d\d:\d\d\.\d+\s+\d+ [\w.-]+:\d+\] ")
_ACCESS_LOG_LINE_RE = re.compile(
    r'^\S+ \S+ \S+ \[\d{1,2}/[A-Z][a-z]{2}/\d{4}:\d\d:\d\d:\d\d [+-]\d{4}\] "([A-Z]+) \S+ HTTP/[\d.]+" (\d)\d\d '
)
_REDIS_LINE_RE = re.compile(r"^\d+:[XCSM] \d{1,2} [A-Z][a-z]{2}(?: \d{4})? \d\d:\d\d:\d\d\.\d{3} ([.*#-]) ")
# Perf: the five log-line probes all mean "log" — one compiled alternation
# runs them in a single pass. Boolean use only; the capture groups of
# _REDIS_LINE_RE / _ACCESS_LOG_LINE_RE are read through their own patterns.
_CL_LOG_ANY_RE = re.compile(
    "(?:" + ")|(?:".join(
        p.pattern
        for p in (_CL_LOG_RE, _SYSLOG_PREFIX_RE, _REDIS_LINE_RE, _KLOG_LINE_RE, _ACCESS_LOG_LINE_RE)
    ) + ")"
)


def classify_line(line: str) -> str:
    t = _nfkc(line.strip())  # 1.10.0: full-width text classifies as the ASCII it looks like
    if not t:
        return "blank"
    if _CL_HEADING_RE.match(t):
        return "heading"
    if _CL_FENCE_RE.match(t):
        return "fence"
    if _CL_TRACE_RE.match(t):
        return "trace"
    if _CL_LOG_ANY_RE.match(t):
        return "log"
    if _CL_LOGFMT_RE.match(t) and _cl_logfmt_pairs(t) >= 3:
        return "log"
    if _CL_IMPORT_RE.match(t):
        return "import"
    if _CL_DEFINITION_RE.match(t):
        return "definition"
    if _CL_LIST_RE.match(t):
        return "list"
    if _CL_TABLE_RE.match(t):
        return "table"
    if _CL_CHAT_ANY_RE.match(t):
        return "chat"
    if t[:1] in "{[" or _CL_JSON_KEY_RE.match(t):
        return "json"
    if _CL_COMMENT_RE.match(t):
        return "comment"
    return "text"


def _json_lines_parse(lines: list[str]) -> bool:
    """True when the text is JSON: the whole text parses, or at least half of the first 50 non-blank lines
    parse on their own as JSON objects/arrays (NDJSON)."""
    text = "\n".join(lines).strip()
    if not text or text[:1] not in "{[":
        sample = [ln.strip() for ln in lines if ln.strip()][:50]
    else:
        try:
            json.loads(text)
            return True
        except (ValueError, RecursionError):
            sample = [ln.strip() for ln in lines if ln.strip()][:50]
    ok = 0
    for ln in sample:
        if ln[:1] in "{[":
            try:
                json.loads(ln)
                ok += 1
            except (ValueError, RecursionError):
                pass
    return bool(sample) and ok * 2 >= len(sample)


def route_content_type(lines: list[str]) -> str:
    counts: dict[str, int] = {}
    sample = lines[:50]
    for line in sample:
        t = classify_line(line)
        counts[t] = counts.get(t, 0) + 1
    nonblank = [(k, v) for k, v in counts.items() if k != "blank"]
    if not nonblank:
        return "text"
    top = max(nonblank, key=lambda kv: kv[1])[0]
    importish = counts.get("import", 0) + counts.get("definition", 0) + counts.get("fence", 0)
    if top in {"import", "definition", "fence", "comment"} or importish >= 3:
        return "code"
    if top in {"log", "trace"} or counts.get("log", 0) + counts.get("trace", 0) > 3:
        return "log"
    if top == "chat":
        return "chat"
    joined = "\n".join(sample).strip()
    if (
        joined[:1] in "{["
        and re.search(r'"[A-Za-z0-9_]+"\s*:', joined)
        and importish == 0
        and _json_lines_parse(lines)
    ):
        return "json"
    if top in {"json", "table"} and importish == 0 and (top == "table" or _json_lines_parse(lines)):
        return "json"
    return "text"


def _collapse_blanks(lines: list[str]) -> list[str]:
    out: list[str] = []
    blanks = 0
    for line in lines:
        if not line.strip():
            blanks += 1
            if blanks <= 1:
                out.append(line)
        else:
            blanks = 0
            out.append(line)
    return out


_PROGRESS_RE = re.compile(
    r"^\[?[=#_>\-*\s]{3,}\d{1,3}%[^\n]*$"
    r"|^Compiling [\w-]+ v[\d.]+"
    r"|^Downloading\b"
    r"|^Downloading crates"
    r"|^Pulling fs layer"
    r"|^Step \d+/\d+",
)

_ERROR_RE = re.compile(
    r"error|ERROR|panic:|Caused by|Traceback|Exception|FAILED|fatal|FATAL"
    r"|warning:|WARN|E\d{4}:",
)


def _log_fingerprint(line: str) -> str | None:
    """Template form of a log line: volatile fields -> placeholders.

    Returns None for marker lines ([\u00d7N] ...) so re-running preprocessing
    never re-collapses its own output markers (NTK idempotency invariant).
    """
    if line.lstrip().startswith(("[\u00d7", "[last] ")):
        return None
    stripped = _PROGRESS_RE.match(line.strip())
    if stripped:
        return None
    # v1.4.0 (E10): volatile fields (ids, ips, timestamps, durations, quoted
    # strings, paths) are masked before the digits, by the same function the
    # error fingerprint uses.
    # Access-log 2xx/3xx fold by method/status class; 4xx/5xx stay verbatim.
    access = _ACCESS_LOG_LINE_RE.match(line.strip())
    if access and access.group(2) in "45":
        return None
    s = mask_template(line[:_RX_LINE_CAP].lower())
    if access:
        s = f"{s[:220]} <{access.group(1)} {access.group(2)}xx>"
    return s[:240] or None


def _template_long_enough(line: str) -> bool:
    """A line is worth collapsing only if its digit-masked form is >12 chars.

    Measured on the digit mask, not on the E10 template (``<ts> info ok`` is
    short only because its timestamp became one token).
    """
    return len(_DIGITS_RE.sub("#", " ".join(line[:_RX_LINE_CAP].lower().split()))) > 12


_PROGRESS_BAR_RE = re.compile(r"(\[[=#>\-. ]*\]\s*)?\d{1,3}\s*(%|/\s*\d+)")
_COMPILING_RE = re.compile(r"^Compiling [\w-]+ ")
_PROGRESS_WORD_RE = re.compile(
    r"\b(downloading|uploading|fetching|extracting|receiving|resolving|"
    r"writing|counting|compressing|copying|processing|progress|"
    r"pulling|installing|unpacking)\b",
    re.IGNORECASE,
)
_LETTERS_RE = re.compile(r"[A-Za-z]")


def _is_progress_bar(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    # (the pattern needs a literal "%" or "/": most lines have neither)
    if ("%" in t or "/" in t) and _PROGRESS_BAR_RE.search(t):
        has_progress_word = _PROGRESS_WORD_RE.search(t) is not None
        for m in _PROGRESS_BAR_RE.finditer(t):
            if "%" in m.group(0) or m.group(1) is not None:
                return True
            if has_progress_word:
                return True
            if not _LETTERS_RE.search(t.replace(m.group(0), "", 1)):
                return True
    return bool(_COMPILING_RE.match(t))


# ---------------------------------------------------------------------------
# v1.4.0 shared line helpers (E1/E3): leading timestamps and error lines.
# ---------------------------------------------------------------------------

# Regex scans of a single line look at its first 2000 chars only: a 20k-char
# run (base64 blob, minified bundle) must not make backtracking regexes
# quadratic. The full line is still kept/emitted by callers.
_RX_LINE_CAP = 2000

# A leading log timestamp is a prefix, not a fact: ISO / RFC3339, syslog
# ("Mar 14 12:00:03") and bare "HH:MM:SS[.mmm]", optionally bracketed. It
# must not by itself make a line "critical" (E1) or a "critical line" for the
# verifier (E3).
_LEAD_TS_RE = re.compile(
    r"^\s*[\[(]?(?:"
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
    r"|\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r")[\])]?[ \t]*"
)


# Critical-line pre-computation (Baseline RAG-style): lines that carry
# operational facts — errors, config assignments, key-value pairs, dates,
# versions. Blocks holding them get a floor boost in score_blocks.
#
# The date alternative does not match a date that opens the line (optionally
# after up to two blanks and a "[" or "("): a line-leading timestamp is a log
# prefix, not a fact. _is_critical_line() widens that to every leading
# timestamp form and chat role labels.
_CRIT_LINE_RE = re.compile(
    r"\b(?:error|exception|traceback|fatal|critical)\b"   # error keywords
    r"|\bconfig(?:uration)?\s*[=:]"                       # config assignments
    r"|\b(?:port|host|user|password|url|token|key)\s*[=:]"  # key-value pairs
    r"|(?<!^)(?<!^[ \t])(?<!^[ \t][ \t])(?<!^[\[(])(?<!^[ \t][\[(])"
    r"\b20[2-3]\d-\d{2}-\d{2}\b"                          # dates (not line-leading)
    r"|\b\d+\.\d+\.\d+(?:\.\d+)?\b",                      # version numbers
    re.IGNORECASE,
)


# A leading chat role label ("User: ...", "Tool: ...") is a speaker tag, not a
# `user:` key-value fact. The old buggy call (pos=2, case-sensitive) never
# matched it either; IGNORECASE would, and boost every user turn.
_LEAD_ROLE_RE = re.compile(r"[ \t]*(?:User|Assistant|System|Tool|Developer)[ \t]*:[ \t]*")


def _lead_ts_end(line: str) -> int:
    """Index just past a leading timestamp prefix (0 when there is none)."""
    m = _LEAD_TS_RE.match(line)
    return m.end() if m else 0


def _crit_scan_start(line: str) -> int:
    """Where a critical-line scan starts: after a leading timestamp and/or
    chat role label, which are line prefixes rather than facts."""
    pos = _lead_ts_end(line)
    m = _LEAD_ROLE_RE.match(line, pos)
    return m.end() if m else pos


def _is_critical_line(line: str) -> bool:
    """Does ``line`` carry an operational fact (error keyword, config or
    key-value assignment, date, version)? A bare leading timestamp or chat
    role label does not count (E1)."""
    return _CRIT_LINE_RE.search(line, _crit_scan_start(line)) is not None


# Level-tagged error lines. Case-sensitive on purpose: "error" in prose is not
# a log level, ERROR is.
_ERR_LEVEL_RE = re.compile(r"\b(?:ERROR|FATAL|CRITICAL|PANIC|FAIL(?:ED|URE)?)\b")
_ERR_LEVEL_TAG_RE = re.compile(r"\[(?:ERROR|FATAL|CRITICAL|PANIC|FAIL(?:ED|URE)?)\]")
_ERR_STRUCT_LEVEL_RE = re.compile(
    r"(?:^|[\s{,])\"?(?:level|lvl|severity|log\.level)\"?\s*[=:]\s*\"?(?:error|err|fatal|critical|crit|panic|emerg|alert)\b",
    re.IGNORECASE,
)
_ERR_BRACKET_LEVEL_RE = re.compile(r"\[(?:[A-Za-z_]+:)?(?:error|crit|alert|emerg)\]")
_ERR_EXC_RE = re.compile(r"^\s*(?:\w+\.)*\w*(?:Error|Exception):")
_ERR_PANIC_RE = re.compile(r"\bpanic:")
_ERR_TRACEBACK = "Traceback (most recent call last)"
# "0 errors", "errors: 0", "failed=0" report success; they are not errors. Only
# a literal zero count negates: "no error body" / "no error handler" are the
# TEXT of a real ERROR line, and a decimal ("ERROR: 0.5 exceeds ...") is not a
# count.
_ERR_NEGATED_RE = re.compile(
    r"\b0\s+(?:errors?|failures?|failed|fatals?)\b"
    r"|\b(?:errors?|failures?|failed|fatals?|critical)\s*[=:]\s*0(?!\w|\.\d)",
    re.IGNORECASE,
)
_COUNT_PREFIX_RE = re.compile(r"^\s*\[(?:\u00d7\d+|last)\]\s*")
_FINGERPRINT_CAP = 160


def _without_zero_counts(s: str) -> str:
    """``s`` with its literal-zero count phrases ("0 errors", "errors: 0",
    "failed=0") removed. A line is negated only when nothing else in it signals
    a failure: Maven's ``[ERROR] Tests run: 5, Failures: 2, Errors: 0`` reports
    a failure *and* a zero count, and must stay an error line."""
    return _ERR_NEGATED_RE.sub(" ", s)


def _is_level_error_line(line: str) -> bool:
    """A level-tagged ERROR/FATAL/CRITICAL/PANIC/FAIL* log line."""
    return _ERR_LEVEL_RE.search(_without_zero_counts(_nfkc(line[:_RX_LINE_CAP]))) is not None


# Every way a line can be an error line contains one of these literals (the
# zero-count removal below only deletes text), so a line without any is not
# one. Perf (v1.5.0): one scan replaces four regexes on the ~99% of log lines
# that are not errors.
_ERROR_LINE_HINT_RE = re.compile(
    r"ERROR|FATAL|CRITICAL|PANIC|FAIL|Error:|Exception:|Traceback \(most recent call last\)|panic:|level|lvl|severity|Level|LEVEL|Severity|SEVERITY|error\]|crit\]|alert\]|emerg\]"
)


_DIAG_EXEMPLAR_CAP = 32
# An indented "at <callee> (<file>:<line>)" / "at <callee> in <file>:line N" frame (Java, .NET, JS).
_STACK_FRAME_LINE_RE = re.compile(
    r"^[ \t]+at\s+\S[^\n]*?(?:\([^()\n]*:\d+(?::\d+)?\)|\bin\s+\S+:line\s+\d+|:\d+:\d+$)"
    r"|^#\d+\s+(?:\S+\(\d+\):|\{main\})"
)


def _is_error_line(line: str) -> bool:
    """Level-tagged error, structured level field (``level=error``, JSON
    ``"level": "error"``), ``XxxError:``/``Exception:`` head, traceback head or
    Go panic, or a multi-language compiler/test/runtime diagnostic
    (agent_formats.DIAGNOSTIC_LINE_RE) — the lines :func:`error_fingerprints` keys on."""
    capped = _nfkc(line[:_RX_LINE_CAP])
    if _STACK_FRAME_LINE_RE.match(capped) is not None:
        # 1.10.0: an indented stack FRAME ("    at pkg.Cls.m(File.java:12)") is a location, not an error: the
        # exception head above it is the error. Frames fold; the heads they hang from are what must survive.
        return False
    if is_diagnostic_line(capped) and _ERR_NEGATED_RE.search(capped) is None:
        return True
    if _ERROR_LINE_HINT_RE.search(capped) is None:
        return False
    s = _without_zero_counts(capped)
    # The exception head is anchored at the line start: look past a "[×N] "
    # collapse prefix so the same failure keeps its key after a fold.
    head = s
    prefix = _COUNT_PREFIX_RE.match(s)
    if prefix:
        head = s[prefix.end():]
    return bool(
        _ERR_LEVEL_RE.search(s)
        or _ERR_EXC_RE.match(head)
        or _ERR_STRUCT_LEVEL_RE.search(s)
        or _ERR_BRACKET_LEVEL_RE.search(s)
        or _ERR_TRACEBACK in s
        or _ERR_PANIC_RE.search(s)
    )


def _error_fp(line: str) -> str:
    """Stable fingerprint of an error line: volatile fields are masked.

    A leading ``[×N] `` collapse marker is stripped, the line lowercased,
    UUIDs -> ``<uuid>``, hex runs of 6+ -> ``<hex>`` (before digits, so ids
    that differ only in digit placement still collide), digits -> ``#``,
    whitespace collapsed, capped at 160 chars.
    """
    s = _COUNT_PREFIX_RE.sub("", _nfkc(line[:_RX_LINE_CAP]), count=1).lower()
    return mask_template(s)[:_FINGERPRINT_CAP]


def error_fingerprints(text: str, *, status_rows: bool = True) -> dict[str, str]:
    """Map error fingerprint -> first exemplar line, in original order (v1.4.0).

    An error line is a level-tagged ``ERROR``/``FATAL``/``CRITICAL``/``PANIC``/
    ``FAIL``/``FAILED``/``FAILURE`` line (uppercase tokens, case-sensitive), an
    ``XxxError:`` / ``Exception:`` head line, a ``Traceback (most recent call
    last)`` line or a Go ``panic:`` line. Lines that report zero errors
    ("0 errors", "errors: 0", "failed=0") are not errors.

    The fingerprint masks everything volatile (see :func:`_error_fp`), so 500
    repeats of one failure share a key and the first one is the exemplar.
    Deterministic and stable under compaction: for compressed text ``c`` that
    kept an exemplar of every failure, ``error_fingerprints(x).keys() <=
    error_fingerprints(c).keys()`` — a host can use that as a retention check.

    ``status_rows=False`` leaves out kubectl pod status rows and Warning event
    rows (``agent_formats.is_kubectl_status_line``): hosts that size summaries
    or briefs by error count use it so per-pod state does not crowd out
    distinct failures.
    """
    if not text:
        return {}
    if type(text) is str and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS:
        result = dict(_error_fingerprints_cached(text))
    else:
        result = _error_fingerprints_scan(text)
    if not status_rows:
        result = {k: v for k, v in result.items() if not is_kubectl_status_line(v)}
    return result


def _error_fingerprints_scan(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    if not text:
        return found
    for line in _norm_newlines(text).split("\n"):
        if not _is_error_line(line):
            continue
        fp = _error_fp(line)
        if fp and fp not in found:
            found[fp] = line
    return found


@content_memo("error_fingerprints", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _error_fingerprints_cached(text: str) -> dict[str, str]:
    return _error_fingerprints_scan(text)


_TRACE_KEEP_HEAD = 3  # exception head + outermost frames (Java/Go/JS put the head first)
_TRACE_KEEP_TAIL = 3  # innermost frame + source line + exception (Python), or the Caused-by root (Java)

# ---------------------------------------------------------------------------
# 1.10.0 (structure): per-cause chain folding. A stack trace run is a sequence
# of "other" lines (exception heads, "Caused by:", "---> inner", "During
# handling...", "goroutine N [...]", "... N more", messages) and FRAME groups
# (a frame line plus the more-indented lines that belong to it: a Python source
# line, a Go file:line). Heads, messages and "... N more" are never dropped. A
# run of at least _FRAME_FOLD_MIN consecutive frame groups keeps its first
# frame, its first frame outside the framework, its last frame (and up to the
# remaining slots of query-matching frames) and one counted marker for the rest.
# A folded run keeps at most _FRAME_FOLD_MIN - 1 frames, so folding is idempotent.
# ---------------------------------------------------------------------------
_FRAME_FOLD_MIN = 5
# Lines of the blocks a caller pinned (pin_patterns / pin_recent) for the call in progress. While a call has pins the
# structural pass, build-noise counting, built-in anchors and the early exit are OFF: the pinned ORIGINAL blocks must come
# back verbatim (the pinned-source cost gate), and folding moves block boundaries. Never read inside memoised functions.
_PINNED_LINES: "contextvars.ContextVar[frozenset]" = contextvars.ContextVar("tameru_pinned_lines", default=frozenset())
# 1.10.0 (S5, E4): set to the CALL's fact-density by ``_compress_context_impl`` and restored by
# ``compress_context``. A fact-dense original keeps the S5 machinery off for the whole call, so
# no stage may re-enable it on a sparser intermediate text. Read by ``_fact_protected_set`` and
# ``_restore_fact_lines``; ``preprocess`` carries it into ``_preprocess_cached``'s memo key so a
# dense call can never poison (or reuse) a sparse call's cached preprocess output.
_FACT_OFF: "contextvars.ContextVar[bool]" = contextvars.ContextVar("tameru_fact_off", default=False)

_ERROR_EXEMPLAR_MAX = 16
# 1.10.0 (S5, E6): the protected error exemplars of the caller's original text — the first line
# per ``error_fingerprints`` fingerprint, at most ``_ERROR_EXEMPLAR_MAX`` in position order. An
# error line is the engine's core evidence, so a destructive selector pre-filter or adapter must
# not delete an exemplar just because it matches neither user nor call terms: the same
# exemption-and-restore treatment as S5 facts, but independent of fact-density rule B and with
# no floor. Set once per compress call; read by ``_error_protected_set`` and the restores. The
# engine stores a position-ordered tuple: the restores append in original line order, never in
# hash order (a frozenset of the same lines remains valid membership input for tests).
_ERR_PROTECTED: "contextvars.ContextVar" = contextvars.ContextVar(
    "tameru_err_protected", default=()
)


def _protected_error_exemplars(text: str) -> tuple[str, ...]:
    """The first line per error fingerprint of ``text``, at most ``_ERROR_EXEMPLAR_MAX`` in
    position order. Secret-bearing lines are never protected — the same predicates as the
    S5 fact rule (``_secret_scan`` + the env-dump reducer's key/value sensitivity test), so
    protection can never resurrect a credentials strip."""
    out: list[str] = []
    for ln in error_fingerprints(text).values():
        probe = ln if ln.isascii() else unicodedata.normalize("NFKC", ln)
        if _secret_scan(probe):
            continue
        em = _env_match(probe)
        if em is not None and _env_is_sensitive(em.group(1), em.group(2)):
            continue
        out.append(ln)
        if len(out) >= _ERROR_EXEMPLAR_MAX:
            break
    return tuple(out)


def _error_protected_set(lines: list[str]) -> set[int]:
    """Indices of ``lines`` that are protected error exemplars (``_ERR_PROTECTED``)."""
    prot = _ERR_PROTECTED.get()
    return {i for i, ln in enumerate(lines) if ln in frozenset(prot)} if prot else set()


# 1.10.0 (E12): the protected outcome/landmark lines of the caller's original text —
# the same exemption contract as ``_ERR_PROTECTED`` (a destructive selector
# pre-filter or adapter must not delete outcome evidence), populated from
# ``_outcome_lines`` once per call and consulted through ``_outcome_protected_set``.
_OUTCOME_PROTECTED: "contextvars.ContextVar" = contextvars.ContextVar(
    "tameru_outcome_protected", default=frozenset()
)


def _outcome_protected_set(lines: list[str]) -> set[int]:
    """Indices of ``lines`` that are protected outcome/landmark lines.

    E13: only a text unique in ``lines`` gets the verbatim exemption. A
    repeated protected text is carried by the fold's ``[×N]`` / ``[last]``
    marker (same bytes, so substring retention holds) and a stage that
    deletes every copy still restores it through ``_OUTCOME_PROTECTED`` —
    exempting all 20 identical table headers was pure cost.
    """
    prot = _OUTCOME_PROTECTED.get()
    if not prot:
        return set()
    counts: dict[str, int] = {}
    for ln in lines:
        if ln in prot:
            counts[ln] = counts.get(ln, 0) + 1
    return {i for i, ln in enumerate(lines) if ln in prot and counts[ln] == 1}
_FRAME_HIT_SLOTS = 1
_STRUCT_COLLAPSE_MIN = 12  # structural (query-less) pass: templates seen fewer times stay verbatim
_FRAME_START_RE = re.compile(r"^\s*(?:at\s+\S|File\s+\"|from\s+\S+:\d+|#\d+\s+\S+\(\d+\):|#\d+\s+\{main\})")
_GO_FRAME_FUNC_RE = re.compile(r"^[\w./*()\[\]{}-]+\(.*\)$")
_FRAME_TAIL_RE = re.compile(r"^\s*(?:\.\.\.\s+\d+\s+(?:more|common frames omitted)\b|---\s*End of inner exception)")
_FRAMEWORK_RE = re.compile(
    r"org\.springframework"
    r"|(?<![\w.])(?:java|javax|jdk|sun|System|Microsoft|scala|kotlin|kotlinx|akka|jakarta)\."
    r"|node_modules|site-packages|/gems/|/lib/ruby/|/vendor/"
    r"|(?<![\w.-])(?:runtime|internal)/"
)
_FRAMES_FOLDED_RE = re.compile(r"^\s*\.\.\. \d+ frames omitted$")


def _is_framework_frame(frame: str) -> bool:
    """A frame inside the language runtime or a framework (so not the caller's own code)."""
    return _FRAMEWORK_RE.search(frame[:_RX_LINE_CAP]) is not None


_CALL_FRAME_RE = re.compile(r"^\s+[\w./$*()\[\]-]+\([^()\n]*:\d+\)")


def _is_frame_line(line: str) -> bool:
    """A stack-frame line (Java/.NET/JS ``at ...``, Python ``File "..."``, Ruby ``from f:1``, indented ``fn(file:line)``); not an exception head or a ``... N more`` tail."""
    capped = line[:_RX_LINE_CAP]
    return _FRAME_START_RE.match(capped) is not None or _CALL_FRAME_RE.match(capped) is not None


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


# An indented line that starts a new cause, not a frame: "---> inner", "Caused by:", "[cause]: ...", an exception
# type with a message, "Suppressed:". Any other indented line of a trace run is a frame of a format the pass does
# not know (Swift, Haskell, Dart ...) and folds like one.
_INDENTED_HEAD_RE = re.compile(
    r"(?:--->|Caused by:|Suppressed:|\[cause\]|Unhandled exception|Exception in thread|Traceback|During handling|The above exception)"
    r"|(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*(?:Exception|Error)\b(?::|\s|$)"
)


def _starts_frame(line: str) -> bool:
    """A frame the pass may fold: a known frame shape, or any other indented line that is not a head or tail marker."""
    if _is_frame_line(line):
        return not _FRAME_TAIL_RE.match(line)
    return (
        line[:1] in (" ", "\t") and bool(line.strip()) and _FRAME_TAIL_RE.match(line) is None
        and _FRAMES_FOLDED_RE.match(line) is None
        and _INDENTED_HEAD_RE.match(line.lstrip()[:_RX_LINE_CAP]) is None
    )


def _frames_folded_marker(count: int, indent: str) -> str:
    return f"{indent}... {count} frames omitted"


def _fold_trace_run(
    run: list[str], src: list[int], idx: list[int], hits: set[int]
) -> tuple[list[str], list[int]]:
    """Fold the frame runs of one stack-trace run. ``hits`` holds the source indices a query selects (kept first)."""
    n = len(run)
    groups: list[tuple[int, int]] = []  # (start, end) of a frame group; other lines are not in any group
    owner = [-1] * n
    k = 0
    while k < n:
        line = run[k]
        is_frame = _starts_frame(line)
        if not is_frame and _GO_FRAME_FUNC_RE.match(line) and k + 1 < n and _indent_of(run[k + 1]) > _indent_of(line) \
                and not run[k + 1].lstrip().startswith(("at ", "...")):
            is_frame = True
        if not is_frame:
            k += 1
            continue
        end = k + 1
        base = _indent_of(line)
        while end < n and _indent_of(run[end]) > base and not _is_frame_line(run[end]) \
                and not _FRAME_TAIL_RE.match(run[end]) and run[end].strip():
            end += 1
        for j in range(k, end):
            owner[j] = len(groups)
        groups.append((k, end))
        k = end
    out: list[str] = []
    out_src: list[int] = []
    pos = 0
    g = 0
    while pos < n:
        if owner[pos] < 0:
            out.append(run[pos])
            out_src.append(src[pos])
            pos += 1
            continue
        # a maximal run of consecutive frame groups
        first = g
        last = g
        while last + 1 < len(groups) and groups[last + 1][0] == groups[last][1]:
            last += 1
        span = groups[first : last + 1]
        total = len(span)
        if total < _FRAME_FOLD_MIN:
            keep = set(range(total))
        else:
            keep = {0, total - 1}
            for j, (a, _b) in enumerate(span):
                if not _is_framework_frame(run[a]):
                    keep.add(j)  # the first frame outside the framework (the caller's own code)
                    break
            room = min(_FRAME_FOLD_MIN - 1 - len(keep), _FRAME_HIT_SLOTS)  # query-matching frames kept
            if room > 0:
                for j, (a, _b) in enumerate(span):
                    if room <= 0:
                        break
                    if j not in keep and idx[a] in hits:
                        keep.add(j)
                        room -= 1
        dropped = 0
        drop_start = 0
        for j, (a, b) in enumerate(span):
            if j in keep:
                if dropped:
                    if dropped == 1:
                        a0, b0 = span[j - 1]
                        out.extend(run[a0:b0])
                        out_src.extend(src[a0:b0])
                    else:
                        a0 = span[drop_start][0]
                        out.append(_frames_folded_marker(dropped, run[a0][: _indent_of(run[a0])]))
                        out_src.append(src[a0])
                    dropped = 0
                out.extend(run[a:b])
                out_src.extend(src[a:b])
            else:
                if dropped == 0:
                    drop_start = j
                dropped += 1
        if dropped:  # cannot happen (the last frame is always kept); kept for safety
            a0 = span[drop_start][0]
            out.append(_frames_folded_marker(dropped, run[a0][: _indent_of(run[a0])]))
            out_src.append(src[a0])
        pos = span[-1][1]
        g = last + 1
    return out, out_src


# 1.10.0 (build output): lines that only say "still working" -- compile / link / resolve / download / install
# steps and passing-test rows. A run of them becomes "[×N] <first line>"; failures, diagnostics, resolver
# conflicts ("npm ERR!", "ERROR: Cannot install") and summary lines are never noise.
_BUILD_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"(?:Compiling|Building|Restoring|Linking|Generating|Copying|Resolving|Fetching|Unpacking|Preparing|Scanning|Packaging|Transpiling|Bundling)\s+\S"
    r"|\[\s*\d+%\]\s+(?:Building|Linking|Scanning|Generating)\b"
    r"|\[\d+/\d+\]\s+(?:Building|Linking|Scanning|Generating|Compiling|CXX|CC|AR|LINK)\b"
    r"|[\w./\\-]+\.(?:cpp|cc|cxx|c|cs|java|kt|go|rs|ts)\s*$"
    r"|(?:clang|clang\+\+|gcc|g\+\+|cc|c\+\+|javac|cl)\S*\s+(?:-c|/c)\s"
    r"|(?:Collecting|Downloading|Downloaded|Using cached|Requirement already satisfied|Obtaining|Building wheel|Created wheel|Stored in directory|Looking in indexes)\b"
    r"|npm (?:WARN deprecated|http fetch|timing|notice)\b"
    r"|\[INFO\]\s+(?:Downloading|Downloaded)\s+from\b"
    r"|(?:PASS|PASSED|Passed|ok)\s+\S"
    r"|(?:✓|✔|√)\s*\S"
    r"|---\s+PASS:\s"
    r"|test\s+\S+\s+\.\.\.\s+ok$"
    r")"
)
_BUILD_NOISE_RUN_MIN = 4


def _is_build_noise_line(line: str) -> bool:
    if _BUILD_NOISE_RE.match(line[:_RX_LINE_CAP]) is None:
        return False
    low = line.casefold()
    return not ("error" in low or "fail" in low or "warn" in low and "deprecated" not in low)


def _fold_build_noise(lines: list[str]) -> list[str]:
    """Replace each run of at least ``_BUILD_NOISE_RUN_MIN`` consecutive build-noise lines by ``[×N] <first line>``.
    Idempotent (a marker line is not noise) and lossless for everything that is not noise."""
    out: list[str] = []
    n = len(lines)
    i = 0
    while i < n:
        if _is_build_noise_line(lines[i]):
            j = i + 1
            while j < n and _is_build_noise_line(lines[j]):
                j += 1
            if j - i >= _BUILD_NOISE_RUN_MIN:
                out.append(f"[\u00d7{j - i}] {lines[i].strip()}")
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out


# ----------------------------------------------------------------------- 1.10.0 S5: fact lines
# A "fact-shaped" line holds one assignment after any leading timestamp/log prefix (_lead_ts_end)
# and an optional comment marker (#, ;, //, --): "key=value", "key: value", "key -> value",
# "key => value", or a JSON/log/CSV line with an embedded "k=v". The key is 1-60 chars of word
# chars, '.', '-' and space or CJK; the value has at least one alphanumeric or CJK character.
# Linear passes, bounded quantifiers.
_FACT_KEY_HEAD = r"[\w.\-一-鿿]"
_FACT_KEY = rf"{_FACT_KEY_HEAD}(?:[\w.\- 一-鿿]{{0,58}}{_FACT_KEY_HEAD})?"
_FACT_ASSIGN_RE = re.compile(
    rf"^[ \t]*(?:#|;|//|--)?[ \t]*"
    rf"(?P<key>{_FACT_KEY})[ \t]*(?:=>|->|=|:)[ \t]*"
    rf"(?P<value>\S[^\n]{{0,399}}?)[ \t]*$"
)
_FACT_INLINE_EQ_RE = re.compile(
    rf"(?P<key>{_FACT_KEY_HEAD}(?:[\w.\-一-鿿]{{0,58}}{_FACT_KEY_HEAD})?)"
    r"=(?P<value>[^\s\"',}\])]{1,120})"
)
_FACT_VALUE_ALNUM_RE = re.compile(r"[^\W_]")
_FACT_PROTECT_FP_MAX = 2  # rarity: a fingerprint seen more times is filler, not a fact
_FACT_FLOOR_MAX_LINES = 8
_FACT_FLOOR_RATIO = 0.15
_FLOOR_MIN_CHARS = 256


def _fact_parts(line: str) -> tuple[str, str] | None:
    """``(key, value)`` when ``line`` is fact-shaped, else ``None``. Shape is judged on the
    NFKC view (full-width ``：``/``＝`` count as ``:``/``=``); callers keep the raw line, so the
    output bytes are never normalised."""
    probe = line if line.isascii() else unicodedata.normalize("NFKC", line)
    if "=" not in probe and ":" not in probe and "->" not in probe:
        return None
    rest = probe[_lead_ts_end(probe):]
    m = _FACT_ASSIGN_RE.match(rest)
    if m is not None:
        key, value = m.group("key"), m.group("value")
    else:
        m = _FACT_INLINE_EQ_RE.search(rest)
        if m is None:
            return None
        key, value = m.group("key"), m.group("value")
    if _FACT_VALUE_ALNUM_RE.search(value) is None:
        return None
    return key.strip(), value


def _protected_fact_lines(
    lines: list[str], fingerprint=_log_fingerprint
) -> list[tuple[int, str, str, str]]:
    """``(index, key, value, line)`` of the lines the S5 rule protects: fact-shaped, not an error
    line (errors are covered by error anchoring), and rare — its ``_log_fingerprint`` occurs at most
    ``_FACT_PROTECT_FP_MAX`` times in the text, so repeated filler is not a fact. A pure CSV row
    without an assignment is not fact-shaped. When the same normalised key appears on several
    fact-shaped lines, only the LAST one is protected (newest wins). ``fingerprint`` lets callers
    share a memoised ``_log_fingerprint`` (every line is fingerprinted once)."""
    # Perf: shape/error detection is memoised per distinct CANDIDATE line (a repeated
    # non-candidate only re-runs the cheap shape test); the rarity (fingerprint) pass
    # only runs when a candidate exists and fingerprints each distinct line once. S7: the
    # memos hold candidates only — memoising every distinct line pinned ~2 MiB at 1M.
    eval_memo: dict[str, tuple[tuple[str, str], bool]] = {}
    fp_memo: dict[str, object] = {}
    cands: list[tuple[int, str, str, object, str]] = []
    cand_fps: set[object] = set()
    for i, ln in enumerate(lines):
        try:
            parts, is_err = eval_memo[ln]
        except KeyError:
            parts = _fact_parts(ln)
            if parts is None:
                continue
            # 1.10.0 (S5, E5): a secret-bearing line is never protected — a credentials strip is
            # a safety deletion the floor/restore must not resurrect. Covers both env-keyed
            # assignments (``DB_PASSWORD=…``) the env-dump reducer removes and secret-shaped
            # values inside fact-shaped prose (``config note: key AKIA… stored``).
            probe = ln if ln.isascii() else unicodedata.normalize("NFKC", ln)
            em = _env_match(probe)
            is_err = (
                _is_error_line(ln)
                or _secret_scan(probe)
                or (em is not None and _env_is_sensitive(em.group(1), em.group(2)))
            )
            eval_memo[ln] = (parts, is_err)
        if is_err:
            continue
        try:
            fp = fp_memo[ln]
        except KeyError:
            fp = fp_memo[ln] = fingerprint(ln)
        cand_fps.add(fp)
        cands.append((i, parts[0], parts[1], fp, ln))
    if not cands:
        return []
    counts: dict[object, int] = {}
    for ln in lines:
        try:
            fp = fp_memo[ln]
        except KeyError:
            fp = fingerprint(ln)   # non-candidates are counted, not memoised
        if fp is not None and fp in cand_fps:
            counts[fp] = counts.get(fp, 0) + 1
    kept = [c for c in cands if c[3] is None or counts.get(c[3], 0) <= _FACT_PROTECT_FP_MAX]
    last_at_key: dict[str, int] = {}
    for pos, c in enumerate(kept):
        last_at_key[" ".join(c[1].casefold().split())] = pos
    protected = set(last_at_key.values())
    return [(i, k, v, ln) for pos, (i, k, v, _fp, ln) in enumerate(kept) if pos in protected]


def _fact_dense(facts, nonblank: int) -> bool:
    """1.10.0 (S5, E4): the text is fact-DENSE — more than ``_FACT_FLOOR_MAX_LINES`` fact
    candidates, or facts on more than a tenth of the non-blank lines — when the S5 machinery
    (exemptions, the selection floor, ``fact_lines_dropped``, its confidence caps) stays off:
    S5 protects buried facts, not config/git-log dumps that are facts throughout."""
    return bool(facts) and (len(facts) > _FACT_FLOOR_MAX_LINES or 10 * len(facts) > nonblank)


def _fact_protected_set(lines: list[str], fingerprint=_log_fingerprint) -> set[int]:
    """Indices into ``lines`` of the protected fact lines — empty on a fact-dense text. Larger
    inputs go through the ``_fact_summary`` memo so every stage that sees the same text
    shares one detection."""
    if _FACT_OFF.get():
        return set()
    if len(lines) >= 16:
        return {i for i, _k, _v, _ln in _protected_facts_lines(lines)}
    facts = _protected_fact_lines(lines, fingerprint)
    nonblank = sum(1 for ln in lines if ln.strip())
    if _fact_dense(facts, nonblank):
        return set()
    return {i for i, _k, _v, _ln in facts}


def _fact_lines_uncached(lines: list[str]) -> tuple[tuple[tuple[int, str, str, str], ...], bool]:
    facts = _protected_fact_lines(lines)
    nonblank = sum(1 for ln in lines if ln.strip())
    dense = _fact_dense(facts, nonblank)
    return (() if dense else tuple(facts)), dense


def _lines_digest_key(lines: list[str], name: str) -> str:
    """``content_key``-style digest over pre-split lines under analysis ``name`` (S7):
    digested in 4096-line slices — C-speed joins, no full-size copy — where a text-keyed
    memo's ``"\\n".join(lines)`` was a second 2 MiB copy at 1M. ``\\n`` never occurs inside
    a line and each slice is length-prefixed, so the digest is unambiguous."""
    digest = hashlib.sha256()
    for part in (ENGINE_VERSION, name):
        digest.update(part.encode("utf-8", "surrogatepass"))
        digest.update(b"\x00")
    digest.update(len(lines).to_bytes(8, "little"))
    for i in range(0, len(lines), 4096):
        encoded = "\n".join(lines[i : i + 4096]).encode("utf-8", "surrogatepass")
        digest.update(len(encoded).to_bytes(4, "little"))
        digest.update(encoded)
    return digest.hexdigest()[:32]


def _fact_lines_key(lines: list[str]) -> str:
    return _lines_digest_key(lines, "fact_summary")


def _fact_summary_lines(lines: list[str]) -> tuple[tuple[tuple[int, str, str, str], ...], bool]:
    """The ``_fact_summary`` memo keyed on the caller's own ``lines`` — same records, no join."""
    key = _fact_lines_key(lines)
    hit = _CONTENT.get(key)
    if hit is _MISS:
        hit = _fact_lines_uncached(lines)
        _CONTENT.set(key, hit)
    return hit


def _protected_facts_lines(lines: list[str]) -> tuple[tuple[int, str, str, str], ...]:
    """``_protected_facts`` for an already-split text (the join length gates the memo)."""
    if sum(map(len, lines)) + len(lines) - 1 <= _MEMO_MAX_CHARS:
        return _fact_summary_lines(lines)[0]
    return _fact_lines_uncached(lines)[0]


def _fact_summary_uncached(text: str) -> tuple[tuple[tuple[int, str, str, str], ...], bool]:
    return _fact_lines_uncached(text.split("\n"))


def _fact_summary(text: str) -> tuple[tuple[tuple[int, str, str, str], ...], bool]:
    """``(protected fact lines, fact_dense)`` for ``text``; a dense text reports no protected lines."""
    if type(text) is str and len(text) <= _MEMO_MAX_CHARS:
        return _fact_summary_lines(text.split("\n"))
    return _fact_summary_uncached(text)


def _protected_facts(text: str) -> tuple[tuple[int, str, str, str], ...]:
    return _fact_summary(text)[0]


def _bounded_orig_index(
    kept_lines: list[str], orig_index: dict[str, int] | None
) -> dict[str, int]:
    """Map kept bounded/windowed variants back to their original line's
    index: the render emits ``line[:head] + omission markers`` for oversized
    lines (``_fact_variant_present`` matching), so a variant is absent from
    ``orig_index`` yet still IS that original line for ordering. Without
    this a kept bounded stale value counts as later than every candidate
    and vetoes restoring its own replacement."""
    out: dict[str, int] = {}
    if not orig_index:
        return out
    head = max(64, _MAX_KEPT_LINE_CHARS // 4)
    oversized = [
        (ln, i) for ln, i in orig_index.items() if len(ln) > _MAX_KEPT_LINE_CHARS
    ]
    if not oversized:
        return out
    for o in kept_lines:
        if o in orig_index:
            continue
        match = None
        for ln, i in oversized:
            if o != ln and o.startswith(ln[:head]):
                if match is not None and match != i:
                    match = None
                    break  # shared-prefix originals: no position beats a wrong one
                match = i
        if match is not None:
            out.setdefault(o, match)
    return out


def _fact_superseded_in(
    line: str,
    kept_lines: list[str],
    orig_index: dict[str, int] | None = None,
    bounded_index: dict[str, int] | None = None,
    scope_of: dict | None = None,
) -> bool:
    """``True`` when a line surviving in the output explicitly marks ``line`` stale
    (``supersession._supersedes``: an is-now/obsolete/override marker plus shared distinctive
    terms). A supersession deletion is deliberate — the floor and stage restores never put
    the stale line back, the same way they never put back a safety deletion.
    Reassignment supersession is directionless on its own (``k = v1`` vs ``k = v2`` are
    symmetric), so ``orig_index`` — each line's position in the original text — gates it:
    only a surviving line that stands LATER in the input may veto the candidate, otherwise
    a kept stale value would refuse to let the current one back in. A kept bounded variant
    resolves through ``bounded_index`` to its original line's position; other kept lines
    absent from ``orig_index`` (render markers) count as later, matching the pre-gate
    behavior; a candidate with no known position keeps the permissive default too."""
    lp = orig_index.get(line) if orig_index is not None else None
    return any(
        o != line
        and _supersedes(
            o,
            line,
            newer_is_later=(
                True
                if lp is None or orig_index is None
                else (
                    orig_index[o]
                    if o in orig_index
                    else (bounded_index or {}).get(o, 1 << 62)
                )
                > lp
            ),
            scopes=(scope_of.get(o), scope_of.get(line)) if scope_of is not None else None,
        )
        for o in kept_lines
    )


def _fact_variant_present(
    ln: str, kept_lines: list[str], must: tuple[str, ...] = ()
) -> bool:
    """``True`` when a bounded/windowed variant of an oversized original line
    already survived — the render emits ``line[:head] + omission markers`` for
    lines over ``_MAX_KEPT_LINE_CHARS``, so the surviving copy still starts
    with a long prefix of the original. Two tests keep diagnostic lines with
    shared preambles from passing for each other: the kept line must start
    with the full window head (a real variant's prefix is at least
    ``_MAX_KEPT_LINE_CHARS // 4`` chars, not the old 64), and every ``must``
    span the floor exists to protect has to survive inside it. Without this
    check the floors re-append the whole oversized line on top of its bounded
    form; a too-weak check drops the fact entirely."""
    if len(ln) <= _MAX_KEPT_LINE_CHARS:
        return False
    head = max(64, _MAX_KEPT_LINE_CHARS // 4)
    want = tuple(unicodedata.normalize("NFKC", s) for s in must)
    for k in kept_lines:
        if k == ln or not k.startswith(ln[:head]):
            continue
        # ``must`` spans are compared normalized both ways: protected values
        # are stored normalized (full-width → ASCII), so a verbatim search
        # would miss the value inside the raw kept text and re-append the
        # fact. Case is NOT folded: a kept line whose value differs only by
        # case holds a different value — counting it would mask the newer
        # fact.
        folded = unicodedata.normalize("NFKC", k) if want else k
        if all(s in folded for s in want):
            return True
    return False


def _bound_fact_line(
    ln: str,
    hit_terms: tuple[str, ...] = (),
    raw_terms: tuple[str, ...] = (),
) -> str:
    """Bound an oversized protected line the same way the render bounds kept
    lines — a floor restores protection, not the unbounded payload."""
    if len(ln) <= _MAX_KEPT_LINE_CHARS:
        return ln
    return _window_oversized_line(
        ln, _MAX_KEPT_LINE_CHARS, hit_terms, None, len(ln), raw_terms
    )


def _missing_in_original_order(missing: list[tuple[int, int, str]]) -> list[str]:
    """The restored lines, ordered by original index, then exemplar position, then text — never
    by hash order, so the same call appends the same sequence on every run."""
    return [ln for _i, _p, ln in sorted(missing, key=lambda m: (m[0], m[1], m[2]))]


def _restore_facts(protected, after: str, before: str | None = None) -> str:
    """Append whole protected fact lines a stage deleted from ``after`` (the same mechanism
    ``_restore_fact_lines`` uses, taking the pre-computed protected set of the original text
    instead of re-detecting on a stage input). E6: protected error exemplars get the same
    treatment, independent of fact density. Missing lines go back in original line order:
    ``before`` is the text the exemplar indices are read from (the caller's original); without
    it exemplars keep their protection order, still deterministic."""
    err = _ERR_PROTECTED.get()
    out = _OUTCOME_PROTECTED.get()
    if not protected and not err and not out:
        return after
    kept = after.split("\n")
    orig_index = {ln: i for i, ln in enumerate(before.split("\n"))} if before is not None else None
    bounded = _bounded_orig_index(kept, orig_index)
    scope_of = _document_scopes(before) if before is not None else None
    missing = [(i, -1, _bound_fact_line(ln)) for i, _k, _v, ln in protected
               if ln != after and ln not in after
               and not _fact_superseded_in(ln, kept, orig_index, bounded, scope_of)
               and not _fact_variant_present(ln, kept, tuple(s for s in (_k, _v) if s))]
    extra = list(err) + sorted(out.difference(err))
    if extra:
        index = orig_index or {}
        for pos, ln in enumerate(extra):
            if (ln != after and ln not in after
                    and not _fact_superseded_in(ln, kept, orig_index, bounded, scope_of)
                    and not _fact_variant_present(ln, kept)):
                missing.append((index.get(ln, float("inf")), pos, _bound_fact_line(ln)))
    if not missing:
        return after
    headers = _document_headers(before) if before is not None else None
    return _append_scoped(after, _missing_in_original_order(missing), scope_of, headers)


def _restore_fact_lines(before: str, after: str) -> str:
    """A destructive stage may not delete a protected fact line: any it lost goes back, verbatim,
    in original line order. A fact line that IS the whole input (a single-line JSON payload) is
    not restored — putting it back would undo the stage entirely."""
    if after is before or after == before:
        return after
    err = _ERR_PROTECTED.get()
    out = _OUTCOME_PROTECTED.get()
    protected = () if _FACT_OFF.get() else _protected_facts(before)
    if not protected and not err and not out:
        return after
    kept = after.split("\n")
    extra = list(err) + sorted(out.difference(err))
    index = {ln: i for i, ln in enumerate(before.split("\n"))}
    bounded = _bounded_orig_index(kept, index)
    scope_of = _document_scopes(before)
    missing = [(i, -1, _bound_fact_line(ln)) for i, _k, _v, ln in protected
               if ln != before and ln not in after
               and not _fact_superseded_in(ln, kept, index, bounded, scope_of)
               and not _fact_variant_present(ln, kept, tuple(s for s in (_k, _v) if s))]
    # E6: an error exemplar the stage saw in ``before`` and lost goes back too —
    # independent of fact density, same supersession guard, same original order.
    # E12: protected outcome lines get the same treatment.
    for pos, ln in enumerate(extra):
        if (ln in before and ln not in after
                and not _fact_superseded_in(ln, kept, index, bounded, scope_of)
                and not _fact_variant_present(ln, kept)):
            missing.append((index.get(ln, float("inf")), pos, _bound_fact_line(ln)))
    if not missing:
        return after
    return _append_scoped(after, _missing_in_original_order(missing), scope_of, _document_headers(before))


def _apply_fact_floor(*, compressed: str, facts, query: str, budget_chars: int | None,
                      scored=None, kept_ids=None, min_savings_ratio=None,
                      original_text=None, adapter_info=None) -> str:
    """Floor in selection: protected fact lines the render left out are appended as whole original
    lines — at most ``_FACT_FLOOR_MAX_LINES`` lines and ``_FACT_FLOOR_RATIO`` of the extract's
    character budget (of the unprotected extract's length when there is no explicit budget).
    Overflow prefers lines whose key or value occurs in ``query``, then the newest.
    1.10.0 (S5, E5): the highest-priority missing line is kept even when it exceeds the character
    cap — a floor that can fit nothing on a near-empty extract protects nothing; the line and
    character caps still govern every further line.
    E13: when ``scored``/``kept_ids``/``min_savings_ratio``/``original_text`` are provided the floor
    displaces rather than inflates — a grow that would push the extract past the savings bound is
    paid for by evicting the lowest-scored rendered lines first, so a borderline extract keeps its
    verdict instead of amplifying a small restore into a fail-open. Marker/adaptor lines (render
    output that never was an original line) are never eviction candidates; when nothing evictable
    remains the append stands and the cost gate decides, exactly as before."""
    kept = compressed.split("\n")
    orig_index = {ln: i for i, ln in enumerate(original_text.split("\n"))} if original_text else None
    bounded = _bounded_orig_index(kept, orig_index)
    # A line already represented by a surviving exemplar of its template (a
    # "[×N]"/"[last]" marker carries the exemplar text) is not missing — the
    # floor's budget is for templates the extract left unrepresented, like the
    # preprocess restore's own coverage rule. Without it a run of sibling
    # instances each counts as missing and outranks the rare variant that has
    # no exemplar at all. The exception is the instance the outcome scan
    # designated: a line sitting beside a failure IS the evidence (the peer
    # that went stale, the record the error was about) — a generic sibling
    # exemplar does not cover that specific instance.
    kept_fps: set[str] = set()
    for _ln in kept:
        _fp = _log_fingerprint(_COUNT_PREFIX_RE.sub("", _ln, count=1))
        if _fp:
            kept_fps.add(_fp)
    # Error positions in the ORIGINAL line list the fact indices are read from,
    # so an error the render kept still marks its neighbours as context — the
    # last success before a failure is the evidence whether or not the failure
    # itself was dropped.
    orig_err: set[int] = set()
    if original_text is not None:
        orig_lines = original_text.split("\n")
        orig_err = {
            i for i, ln in enumerate(orig_lines)
            if _OUTCOME_ERR_NEAR_RE.search(ln) or _OUTCOME_ANOMALY_RE.search(ln)
        }

    def _ctx(i: int) -> bool:
        return i - 1 in orig_err or i + 1 in orig_err or i + 2 in orig_err

    raw_terms = tuple(t for t in _extract_terms(query or "") if len(t) >= 3)
    hit_terms = tuple(t.casefold() for t in raw_terms)
    scope_of = _document_scopes(original_text) if original_text is not None else None
    missing = [
        f for f in facts
        if f[3] not in compressed and not _fact_superseded_in(f[3], kept, orig_index, bounded, scope_of)
        and not _fact_variant_present(f[3], kept, tuple(s for s in (f[1], f[2]) if s))
        and (not _log_fingerprint(f[3]) or _log_fingerprint(f[3]) not in kept_fps or _ctx(f[0]))
    ]
    if not missing:
        return compressed
    # The ratio budget can fit nothing on a near-empty extract — a floor that
    # protects nothing protects no one. The absolute minimum keeps the budget
    # meaningful on a one-or-two-line extract without unbounding it. The base is
    # the ALLOWED extract size, not the achieved one: sizing the floor off a
    # render that under-filled its bound starves the protection exactly where
    # the extract under-delivered.
    floor_base = budget_chars
    if floor_base is None and original_text is not None and min_savings_ratio:
        floor_base = int(len(original_text) * (1.0 - float(min_savings_ratio)))
    cap = max(
        int(_FACT_FLOOR_RATIO * (floor_base or len(compressed))),
        _FLOOR_MIN_CHARS,
    )
    q = (query or "").casefold()

    mset = {f[0]: f for f in missing}
    # A template with a single missing instance is the rare variant the stream
    # exists to show (the one "{ getattr }" denial amid a hundred "{ write }");
    # siblings of a flooded template inter-change with each other, so they rank
    # behind it. Measured on the missing set, which is what the budget feeds.
    miss_fp_count: dict[str, int] = {}
    for f in missing:
        _fp = _log_fingerprint(f[3])
        if _fp:
            miss_fp_count[_fp] = miss_fp_count.get(_fp, 0) + 1
    def _rank(f) -> tuple:
        i, key, value, ln = f
        # Error-shaped lines and the rows they annotate rank first — an error
        # and the entry it suspends are the evidence pair; a bare summary or
        # tail row is lower priority than the record the error belongs to.
        err = _OUTCOME_ERR_NEAR_RE.search(ln)
        # The context convention is the row BEFORE the failure — a row sitting
        # after an error is just the next stream entry, not its evidence.
        adj_err = err is None and (
            any(
                j in mset and _OUTCOME_ERR_NEAR_RE.search(mset[j][3])
                for j in (i + 1, i + 2)
            )
            or _ctx(i)
        )
        fp = _log_fingerprint(ln)
        rare = bool(fp) and miss_fp_count.get(fp, 0) == 1
        return (key.casefold() in q or value.casefold() in q, bool(err), adj_err, rare, i)

    chosen, used = [], 0
    for f in sorted(missing, key=_rank, reverse=True):
        ln = f[3]
        # One restored exemplar stands for its template: once a sibling is
        # chosen the rest are covered — same rule the preprocess restore uses,
        # so the budget goes to templates that have no exemplar at all. A
        # designated error-adjacent instance is never covered by a sibling.
        fp = _log_fingerprint(ln)
        if fp and fp in kept_fps and not _ctx(f[0]):
            continue
        # Charge the BOUNDED render — the form actually appended — not the
        # original's length: an oversized fact that fits after windowing must
        # not be skipped by a cap it would never have broken.
        bound = _bound_fact_line(ln, hit_terms, raw_terms)
        if chosen and (len(chosen) >= _FACT_FLOOR_MAX_LINES or used + len(bound) + 1 > cap):
            continue
        chosen.append(f)
        used += len(bound) + 1
        if fp:
            kept_fps.add(fp)
    if not chosen:
        return compressed
    # Each restored line's own section header goes back with it when the
    # extract ends in a different scope — a dropped [database] setting must
    # not read as a second value under the [cache] mapping it lands after.
    headers = _document_headers(original_text) if original_text is not None else {}
    cur_scope = _end_scope(compressed)
    emitted: list[str] = []
    for f in sorted(chosen, key=lambda f: f[0]):
        scope = scope_of.get(f[3]) if scope_of else None
        if scope and scope != cur_scope and headers.get(scope):
            emitted.append(headers[scope])
        if scope:
            cur_scope = scope
        emitted.append(_bound_fact_line(f[3], hit_terms, raw_terms))
    appended = "\n".join(emitted)
    out = compressed + "\n" + appended
    if scored is None or kept_ids is None or min_savings_ratio is None or original_text is None:
        return out
    head_tok = estimate_tokens(original_text) * (1.0 - float(min_savings_ratio))
    need_tok = estimate_tokens(out) - head_tok
    need_chr = len(out) - len(original_text) * (1.0 - float(min_savings_ratio)) if adapter_info is not None else 0.0
    # The floor pays for its own growth, never more: eviction covers the
    # appended size whether or not the bound already holds — protected lines
    # occupy the existing budget rather than inflating the extract. An extract
    # that already missed the bound still misses it when the candidates run
    # out: the verdict is unchanged.
    evict_budget = estimate_tokens(appended) + len(chosen)
    line_score: dict[str, float] = {}
    for b in scored:
        # Only lines from pure-score keeps are eviction candidates. A block
        # kept for a non-score reason — query hits, an error exemplar, a pin —
        # holds its lines for that reason regardless of its raw score (a
        # needle-hit block can score low and still be the answer).
        if b["id"] in kept_ids and not (
            b.get("entity_hits") or b.get("term_hits")
            or b.get("error_exemplar") or b.get("pinned")
        ):
            for ln in b["text"].split("\n"):
                prev = line_score.get(ln)
                if prev is None or b["score"] < prev:
                    line_score[ln] = b["score"]
    rendered = compressed.split("\n")
    pool_texts = {f[3] for f in facts}
    cand = sorted(
        (
            i for i, ln in enumerate(rendered)
            if ln in line_score
            and ln not in pool_texts
            and not _OUTCOME_ERR_NEAR_RE.search(ln)
            and not _is_trust_risk_line(ln)
        ),
        key=lambda i: (line_score[rendered[i]], i),
    )
    drop: set[int] = set()
    spent = 0
    for i in cand:
        if spent >= evict_budget:
            break
        ln = rendered[i]
        drop.add(i)
        cost = estimate_tokens(ln) + 1
        spent += cost
        need_tok -= cost
        need_chr -= len(ln) + 1
    if drop:
        compressed = "\n".join(ln for i, ln in enumerate(rendered) if i not in drop)
        out = compressed + "\n" + appended
    return out


def _count_fact_lines_dropped(facts, out_text: str) -> int:
    """``fact_lines_dropped``: protected fact lines of the original whose whole line — or a line
    holding both the key and the value — is not in the output."""
    if not facts:
        return 0
    out_lines = out_text.split("\n")
    dropped = 0
    for _i, key, value, ln in facts:
        if ln in out_text:
            continue
        if any(key in o and value in o for o in out_lines):
            continue
        dropped += 1
    return dropped


_STREAM_BREAK_MIN_LINES = 30
_STREAM_BREAK_MAX_RARE = 2


def _stream_break_lines_scan(lines: list[str]) -> tuple[tuple[int, str, str, str], ...]:
    """Floor extras: the break lines of a largely-templated stream.

    A command dump is mostly repeats — same row shape, same heartbeat, same
    record template — plus a few lines that break the pattern, and the breaks
    are the evidence a scored selection cannot recognise:

    - a trailing status/footer line: the last non-blank line whose template is
      rare (``_FACT_PROTECT_FP_MAX``, the same bound as a fact). ``Processed a
      total of N messages``, ``SMART Health Status: OK``, a table header
      repeated at the end — a bare summary with no error keyword and no
      ``key: value`` shape, so neither error anchoring nor S5 sees it. A last
      line that CONTINUES the dominant template (the stream cut mid-run) is
      not a footer and is not flagged.
    - the unique-template rows (at most ``_STREAM_BREAK_MAX_RARE``) in an
      otherwise uniform run: anomalous records a block score treats as
      ordinary — a RUNNING/``<defunct>`` process among sleeping workers, a
      100%-full mount, a red index row. More than two uniques means the text
      is heterogeneous, not uniform-plus-anomalies.

    Returns ``(index, key, value, line)`` in the fact-line shape so the
    selection floor restores a dropped break line the same way; key and value
    are the line itself, so it ranks as query-relevant only when the whole
    line literally occurs in the query.

    Break lines feed ONLY the selection floor — never the stage restores — so
    one can be re-added only while it sits in the final ``lines`` (``f[3] in
    line_set``): a line an earlier stage deleted (a credentials strip, a
    folded marker) is absent from ``lines`` and stays gone — the floor fixes
    selection losses, never safety deletions. Worthiness guards: the break
    line must be substantive (``_template_long_enough``), not injection-shaped
    (trust-risk) and not ``_is_sink_noise`` filler, and it must not look like
    credential material — a secret-bearing tail is stripped evidence, not a
    status footer. The credential check uses the ``_secret_scan`` literal
    prefilter and the env-dump key/value test only: the once-per-call
    ``_SECRETS_RE`` budget leaves no room for per-line regexes, and a literal
    without a regex match merely under-protects, never over-restores.
    """
    nb_count = sum(1 for ln in lines if ln.strip())
    if nb_count < _STREAM_BREAK_MIN_LINES:
        return ()
    nb_i: list[int] = []
    fps: list[str | None] = []
    counts: dict[str, int] = {}
    # ``cand_uniq`` tracks the running unique candidates — non-templated lines plus
    # fingerprints seen exactly once so far. Each remaining line can move it by at
    # most one, so once ``cand_uniq - remaining`` exceeds a tenth of the non-blank
    # count the text provably fails the 90%-repeated test below and the scan exits
    # before building full-size per-line tables on a heterogeneous stream.
    cand_uniq = 0
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        nb_i.append(i)
        fp = _log_fingerprint(ln)
        fps.append(fp)
        if fp is None:
            cand_uniq += 1
        else:
            c = counts.get(fp, 0)
            counts[fp] = c + 1
            if c == 0:
                cand_uniq += 1
            elif c == 1:
                cand_uniq -= 1
        if (cand_uniq - (nb_count - len(nb_i))) * 10 > nb_count:
            return ()
    repeated = sum(1 for fp in fps if fp is not None and counts[fp] >= 2)
    if repeated * 10 < nb_count * 9:
        return ()

    def _worthy(ln: str) -> bool:
        # A break line must carry enough distinctive content to be evidence —
        # a tiny stub ("shortline1", "#") is noise, not a status footer or an
        # anomalous record — and injection-shaped or boilerplate lines never
        # qualify.
        if not _template_long_enough(ln):
            return False
        if _is_trust_risk_line(ln) or _is_sink_noise(ln):
            return False
        probe = ln if ln.isascii() else unicodedata.normalize("NFKC", ln)
        if any(lit in probe for lit in _SECRET_LITERALS):
            return False
        if any(lit in probe.lower() for lit in _SECRET_FOLDED_LITERALS):
            return False
        em = _env_match(probe)
        return em is None or not _env_is_sensitive(em.group(1), em.group(2))

    out: list[tuple[int, str, str, str]] = []
    i_last = nb_i[-1]
    last = lines[i_last]
    fp_last = fps[-1]
    if (
        fp_last is not None
        and counts.get(fp_last, 0) <= _FACT_PROTECT_FP_MAX
        and _worthy(last)
    ):
        out.append((i_last, last, last, last))
    rare = [
        (i, lines[i])
        for i, fp in zip(nb_i, fps)
        if fp is not None and counts[fp] == 1
    ]
    if 1 <= len(rare) <= _STREAM_BREAK_MAX_RARE:
        seen = {ln for _i, _k, _v, ln in out}
        out.extend(
            (i, ln, ln, ln) for i, ln in rare if ln not in seen and _worthy(ln)
        )
    return tuple(sorted(out))


def _stream_break_lines(lines: list[str], n_chars: int) -> tuple[tuple[int, str, str, str], ...]:
    """``_stream_break_lines_scan`` over the caller's pre-split, newline-normalised
    lines (memoised like ``_fact_summary_lines`` — the impl shares its
    ``protected_source`` split with the fact pass rather than paying a second
    line-objects copy at 1M). Texts over the memo cap skip the cache rather than
    pay a second fingerprint pass on a repeat call."""
    if n_chars <= _MEMO_MAX_CHARS:
        key = _lines_digest_key(lines, "stream_break_lines")
        hit = _CONTENT.get(key)
        if hit is _MISS:
            hit = _stream_break_lines_scan(lines)
            _CONTENT.set(key, hit)
        return hit
    return _stream_break_lines_scan(lines)


# 1.10.0 (E12): outcome/landmark lines for the selection floor. The sealed round-2
# look showed evidence families whose gold lines are neither fact-shaped nor
# error-shaped nor stream-breaks: completion summaries ("Successfully validated
# 798 migrations", "1 scenario passed, 1 failed"), REPL prompt lines
# ("acme_billing> db.x.find()"), table headers, numbered section headers
# ("Event[90]:") and bare key:value status lines sitting next to a kept error.
# A scored selection cannot tell these apart from noise under a miss query, so
# they get the same bounded, floor-only protection as break lines.
_OUTCOME_MAX_LINES = 12
_OUTCOME_SECTION_BODY_MAX = 6
_OUTCOME_FAIL_MAX = 6
_OUTCOME_LONE_KV_MAX = 3

_OUTCOME_SUMMARY_RE = re.compile(
    r"^\s*(?:"
    r"Successfully\s+\w+.*"
    r"|\d[\d,]*\s+(?:scenario|test|check|migration|example|step|spec|assertion)s?\b.*"
    r"\b(?:passed|failed|skipped|undefined|pending|error)\b.*"
    r"|\d[\d,]*\s+requests?\s+in\s+[\d.]+\s*[smh]\b.*"
    r"|Socket errors:.*"
    r"|Verify return code:.*"
    r"|Processed a total of \d.*"
    r"|(?:Stopped|Started|Stopping|Starting)\b.*\b(?:service|daemon|unit|target|scope|slice)\b.*"
    r"|The\s+[\w -]{2,60}\s+was\s+\w+ed\b.*"
    r"|.*\bpromiscuous mode\b.*"
    r"|\w[\w-]*\s+done\b.*"
    r")\s*$",
    re.IGNORECASE,
)
_OUTCOME_PROMPT_RE = re.compile(r"^\s*([A-Za-z_][\w.-]{1,24})[>$#]\s+\S")
_OUTCOME_SECTION_RE = re.compile(r"^\s*(?:[\w.-]+\[\d+\]|(?:Event|Record|Entry|Item|Block|Frame|Packet)\s+#?\d+)\s*:\s*$")
_OUTCOME_KV_RE = re.compile(r"^\s*[a-z][\w.-]{1,39}[:=]\S{1,80}\s*$")
_OUTCOME_ERR_NEAR_RE = re.compile(
    r"(?i)(?:\(error\)|\bERROR\b|\berror[ s:]|fail(?:ed|ure)?"
    r"|\bwarn(?:ing)?[ s:]|\bnot[ _]found\b"
    r"|\b(?:panic|fatal|bug|denied|refused|unreachable|flooding|lockup|corrupt|"
    r"critical|overrun\w*|exceed\w*|dropp\w*|destroy\w*|reject\w*|stale)\b"
    r"|(?-i:\bALARM\b))"
)
_OUTCOME_LONE_KV_RE = re.compile(r"^\s*\S[^:=>]{1,40}\s*(?::|=|->)\s*\S{1,80}\s*$")
# Credential material only when a keyword binds a value ("password=hunter2",
# "Authorization: Bearer x"); prose that merely names it ("Failed password
# for invalid user") is an auth event, not a secret — a bare substring check
# cannot tell them apart and starves the floor.
_OUTCOME_CRED_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[-_]?key|access[-_]?token|auth[-_]?token|"
    r"bearer|token|private|signing|basic|db[-_]?pass|mysqlpwd|mysql[-_]?pwd|"
    r"pgpassword|rediscli[-_]?auth)\s*[:=]"
)
# Lines that hold an actual credential token — not just a word that could be
# one. The _SECRET_LITERALS prefilter is a recall net for the real regexes;
# reused as a worthiness guard it rejects ordinary URLs ("://"), "curl"
# commands and "key-" fields. These shapes are unambiguous tokens, plus URI
# userinfo (scheme://user:pass@host) which is the credential "://" was after.
_OUTCOME_SECRET_LINE_RE = re.compile(
    r"-----BEGIN |\bAKIA[0-9A-Z]{8,}|\bgh[pousr]_\w{8,}|github_pat_\w+|\bxox[baprs]?-\w+"
    r"|\bsk-[\w-]{8,}|\beyJ[\w-]{8,}|\bAIza[\w-]{8,}|\bya29\.\w+|\bhf_[\w-]{8,}"
    r"|\bnpm_\w{8,}|pypi-AgE|SG\.[\w-]{8,}\.[\w-]{8,}|glpat-\w+|dckr_pat_\w+|xapp-\w+"
    r"|hooks\.slack\.com|/api/webhooks/|whsec_\w+|dop_v1_\w+|sshpass\b|1//0[\w-]{6,}"
    r"|[a-z][a-z0-9+.-]*://[^\s/:]{1,64}:[^\s@]{1,256}@",
    re.IGNORECASE,
)
# "???" in a result row is an unresolved/failed record (an mtr hop that never
# answered, a missing field) — failure evidence even without an error word.
# "!<word>!" is the same unresolved-marker idiom ("!missing!").
_OUTCOME_ANOMALY_RE = re.compile(r"\?\?\?|!\w[\w -]{1,30}!")
# A decorated header ("=== warnings summary ===") or a docs pointer line
# ("-- Docs: https://...") is furniture even when its text holds a warning
# word — the failure vocabulary wants events, not framing.
_OUTCOME_FRAME_RE = re.compile(r"^\s*[-=*_+#~]{3,}.*[-=*_+#~]{3,}\s*$")
_OUTCOME_DOC_LINK_RE = re.compile(r"(?i)^\s*-{0,3}\s*(?:docs?|see also|ref(?:erence)?|link)\s*:")
# Perf: the failure-vocabulary probes merge into one scan — ERR_NEAR's
# pattern verbatim, ANOMALY's appended (its `\w`/`[\w -]` classes match
# either case already, so ERR_NEAR's leading `(?i)` changes nothing for it).
# Composed from the source patterns so a vocabulary edit lands in both places.
_OUTCOME_ERR_ANY_RE = re.compile(
    _OUTCOME_ERR_NEAR_RE.pattern + "|" + _OUTCOME_ANOMALY_RE.pattern
)
# FRAME and DOC_LINK both "match" guards on the same lines — one alternation.
_OUTCOME_NOT_ERR_RE = re.compile(
    _OUTCOME_FRAME_RE.pattern + "|" + _OUTCOME_DOC_LINK_RE.pattern.replace("(?i)", "", 1),
    re.IGNORECASE,
)
# A run of 8+ box/block-drawing glyphs at line start is a download/progress
# bar ("   ━━━━ 119.0/119.0 kB"), never failure context — _is_progress_bar
# misses shapes that carry no % or /.
_OUTCOME_BAR_RE = re.compile(r"^\s*[─-╿▀-▟═]{8,}")
_OUTCOME_LONE_KV_COMMENT_RE = re.compile(r"^\s*#\s*\S[^:=]{1,30}:\s*\S{1,80}\s*$")
# A `key: value` line whose value is a failure/state word is an evidence record
# field ("State: DECOMMISSIONED", "Health: DOWN") — it plus its stanza opener
# ("Name: 10.3.1.8:7868") are the record's landmark lines.
_OUTCOME_STATEKV_RE = re.compile(
    r"^\s*[A-Z][\w .-]{1,30}:\s*(?:down|dead|decommission\w*|failed?|error\w*|"
    r"unhealthy|offline|corrupt\w*|fault\w*|stale|lost|broken|partiallyfailed)\b",
    re.IGNORECASE,
)
_OUTCOME_STANZA_OPENER_RE = re.compile(r"^\s*(?:Name|Node|Address|Service|Device|Brick|Member|Peer)\s*:\s*\S")
_OUTCOME_STANZA_FIELD_RE = re.compile(r"^\s*\w[\w .-]{1,30}:")
# A data row carrying money, a port/protocol or an unusual state under a table
# header is the row the error happened on ("{port}/tcp open svc 1.2",
# "aws_db_instance.x 730 hours $868.0") — bounded to one per kept table.
_OUTCOME_DATAROW_RE = re.compile(
    r"(?:\$\d|\d+/(?:tcp|udp|sctp)\b|0(?:\.0+)?\s*(?:[KMG]i?bits|pkts|pps)\b"
    r"|\b(?:down|dead|decommission\w*|failed?|error\w*|unhealthy|offline|weak|"
    r"vulnerab\w*|insecure|non-?complian\w*)\b)",
    re.IGNORECASE,
)
# E14: rows whose evidence is the row itself rather than a money/port/state
# anchor — device rows ("sdc  657G disk"), mtr hops ("  9.|-- host 0.0%"),
# node state rows ("DN 10.2.102.31 497 GB ... rack3"), pipe tables, queue
# states. Collected only when the line also carries a digit, so prose using
# these words stays out.
_OUTCOME_EVIDROW_RE = re.compile(
    r"^\s*\d+\.\|--"
    r"|^\s*[UD]N\s+\d"
    r"|\d+(?:\.\d+)?%"
    r"|\b\d+(?:\.\d+)?\s?[KMGTPE]i?B\b"
    r"|\|\s*\S.*\|"
    r"|\b(?:disk|part|lvm|rom)\b"
    r"|\b[ds]ports?:\d"
    r"|(?-i:\b(?:ACCEPT|DROP|REJECT|DNAT|SNAT|MASQUERADE)\b)"
    r"|^\d+:\d{2}\.\d\s"
    r"|\(\d+ rows?\)"
    r"|-(?:pci|isa|acpi|virt)-\d"
    r"|\bidle\b",
    re.IGNORECASE,
)
# A pure box-drawing run adjacent to a total/summary line is a table border,
# not a progress bar — the bar guard above only excluded it because pip bars
# share the glyph set.
_OUTCOME_BORDER_RE = re.compile(r"^\s*(?:[─═━_]{8,}|(?:\+-+)+\+?)\s*$")
# A result-set row-count footer ("(2 rows)") — the terminal record of a table,
# the same position a run-terminal datarow occupies.
_OUTCOME_ROWSFOOT_RE = re.compile(r"^\s*\(\d+ rows?\)\s*$", re.IGNORECASE)
_OUTCOME_TOTAL_RE = re.compile(r"(?:total|overall|合计|汇总|小计|总计)", re.IGNORECASE)
_OUTCOME_TABLE_HEADS = frozenset(
    "state proto recv-q send-q local peer pid user %cpu %mem vsz rss tty stat start time "
    "command name device filesystem size used avail use% mounted iface mtu rx-ok tx-ok "
    "chain target prot pkts bytes source destination flags options address port".split()
)


def _outcome_worthy(ln: str, *, allow_short: bool = False) -> bool:
    """Same worthiness guards as the stream-break floor: substantive, not
    injection-shaped, not sink filler, never credential material. Landmark
    lines are short by nature — a numbered header ("Event[90]:") or a column
    row is long enough when its class matched, so ``allow_short`` skips the
    length gate for them only."""
    if not allow_short and not _template_long_enough(ln):
        return False
    if _is_trust_risk_line(ln) or _is_sink_noise(ln) or _TEST_FILE_NOISE_RE.search(ln):
        return False
    probe = ln if ln.isascii() else unicodedata.normalize("NFKC", ln)
    if _OUTCOME_SECRET_LINE_RE.search(probe):
        return False
    if _OUTCOME_CRED_RE.search(probe):
        return False
    em = _env_match(probe)
    return em is None or not _env_is_sensitive(em.group(1), em.group(2))


def _outcome_lines_scan(lines: list[str]) -> tuple[tuple[int, str, str, str], ...]:
    """The outcome/landmark candidates of ``lines`` — at most one small set per
    class so the floor's line budget is not spent on a single shape. Returns the
    fact-line ``(index, key, value, line)`` shape; key/value are the line itself.
    """
    nb_i = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(nb_i) < 10:
        return ()
    # Perf: the failure-context probe runs once per line — err_near needs the
    # whole map before the main loop, which then reuses is_err instead of
    # re-running the same four patterns on every line.
    is_err = [False] * len(lines)
    for i in nb_i:
        is_err[i] = bool(
            _OUTCOME_ERR_ANY_RE.search(lines[i]) and not _OUTCOME_NOT_ERR_RE.match(lines[i])
        )
    err_near = [False] * len(lines)
    for i in nb_i:
        if is_err[i]:
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                err_near[j] = True
    summaries: dict[str, tuple[int, str]] = {}
    summary_counts: dict[str, int] = {}
    prompts: dict[str, tuple[int, str]] = {}
    prompt_counts: dict[str, int] = {}
    section_hits: list[tuple[int, str]] = []
    tables: list[tuple[int, str]] = []
    kvs: list[tuple[int, str]] = []
    fail_lines: list[tuple[int, str, str]] = []
    lone_kvs: list[tuple[int, str]] = []
    state_kvs: list[tuple[int, str]] = []
    datarows: list[tuple[int, str]] = []
    borders: list[tuple[int, str]] = []
    for pos, i in enumerate(nb_i):
        ln = lines[i]
        if is_err[i]:
            fp = _log_fingerprint(ln) or ln
            fail_lines.append((i, ln, fp))
            continue
        if _OUTCOME_SUMMARY_RE.match(ln):
            # Repeated progress lines ("Successfully applied N migrations"
            # every step) are a status stream, not an outcome — counted per
            # shape below and dropped; only a shape seen once or twice reports
            # an outcome ("Successfully validated 798 migrations").
            sfp = _log_fingerprint(ln) or ln
            summaries[sfp] = (i, ln)
            summary_counts[sfp] = summary_counts.get(sfp, 0) + 1
            if len(summaries) > 4:
                summaries.pop(next(iter(summaries)))
            continue
        pm = _OUTCOME_PROMPT_RE.match(ln)
        if pm:
            # Prompts dedupe on the COMMAND shape (the part after the prompt
            # marker, digit-bearing tokens masked), so twenty ".stats()" calls
            # are one template and the single ".find()" / "exit" stand out.
            cfp = re.sub(r"\w*\d\w*", "#", ln[pm.end(1):])
            prompts[cfp] = (i, ln)
            prompt_counts[cfp] = prompt_counts.get(cfp, 0) + 1
            continue
        if _OUTCOME_SECTION_RE.match(ln):
            section_hits.append((i, ln))
            continue
        if len(tables) < 2:
            first = ln.strip().split(None, 1)[0].lower().rstrip(":")
            if first in _OUTCOME_TABLE_HEADS and len(ln.split()) >= 3:
                nxt = next((lines[j] for j in nb_i[pos + 1:pos + 3] if j > i), "")
                if len(nxt.split()) >= 3:
                    tables.append((i, ln))
                    continue
        if len(kvs) < 2 and err_near[i] and _OUTCOME_KV_RE.match(ln):
            kvs.append((i, ln))
            continue
        if _OUTCOME_STATEKV_RE.match(ln):
            state_kvs.append((i, ln))
            continue
        if (
            (len(ln.split()) >= 3 or ln.count("|") >= 2 or _OUTCOME_ROWSFOOT_RE.match(ln))
            and not _OUTCOME_BAR_RE.match(ln)
            and (
                _OUTCOME_DATAROW_RE.search(ln)
                or _OUTCOME_ROWSFOOT_RE.match(ln)
                or (any(ch.isdigit() for ch in ln) and _OUTCOME_EVIDROW_RE.search(ln))
            )
        ):
            datarows.append((i, ln))
            continue
        if len(borders) < 3 and _OUTCOME_BORDER_RE.match(ln):
            prev = next((lines[j] for j in reversed(nb_i[:pos])), "")
            nxt = next((lines[j] for j in nb_i[pos + 1:pos + 2]), "")
            # A border earns protection beside a total/summary (the classic
            # score table) or beside a pipe-table row ("+---+" framing the
            # "| peer | id |" grid is the table's landmark edge).
            if (
                _OUTCOME_TOTAL_RE.search(prev) or _OUTCOME_TOTAL_RE.search(nxt)
                or _OUTCOME_SUMMARY_RE.match(prev.strip()) or _OUTCOME_SUMMARY_RE.match(nxt.strip())
                or prev.lstrip().startswith("|") or nxt.lstrip().startswith("|")
            ):
                borders.append((i, ln))
                continue
        if len(lone_kvs) < _OUTCOME_LONE_KV_MAX and (
            _OUTCOME_LONE_KV_RE.match(ln) or _OUTCOME_LONE_KV_COMMENT_RE.match(ln)
        ):
            lone_kvs.append((i, ln))
            continue
    # Rare commands first (the one ".find()" or "exit" among routine ".stats()"
    # calls is the evidence), then the latest of each — the tail is where the
    # session outcome lives.
    prompt_list = [
        v for _cfp, v in sorted(
            prompts.items(), key=lambda kv: (prompt_counts[kv[0]], -kv[1][0])
        )[:3]
    ]
    summary_list = [
        v for fp, v in summaries.items() if summary_counts[fp] <= 2
    ]
    if len(nb_i) and lone_kvs:
        def _kv_delim(ln: str) -> str:
            if _OUTCOME_LONE_KV_COMMENT_RE.match(ln):
                return "#"
            if "->" in ln:
                return "->"
            if "=" in ln:
                return "="
            return ":"

        shares = {"#": 0, "->": 0, "=": 0, ":": 0}
        kv_like = 0
        for i in nb_i:
            ln = lines[i]
            if _OUTCOME_LONE_KV_RE.match(ln) or _OUTCOME_LONE_KV_COMMENT_RE.match(ln):
                kv_like += 1
                shares[_kv_delim(ln)] += 1
        if kv_like / len(nb_i) > 0.30:
            # In a kv-dense stream a singleton matching the dominant delimiter
            # is just another field; a minority-delimiter or comment line still
            # reads as a landmark ("queue_depth=388" amid "key: value" fields).
            dom = max(shares.values())
            lone_kvs = [
                t for t in lone_kvs
                if _kv_delim(t[1]) == "#" or shares[_kv_delim(t[1])] * 2 <= dom
            ]
    # Failure exemplars rank by template rarity — a one-off failure ("invalid
    # user admin" amid routine "for root" rejects) is the evidence. Each
    # surviving template keeps its first and last occurrence: the exemplar
    # plus the most recent instance, which is where buried gold lands.
    fails: list[tuple[int, str]] = []
    if fail_lines:
        fpc: dict[str, int] = {}
        first_per: dict[str, tuple[int, str]] = {}
        last_per: dict[str, tuple[int, str]] = {}
        for i, ln, fp in fail_lines:
            fpc[fp] = fpc.get(fp, 0) + 1
            first_per.setdefault(fp, (i, ln))
            last_per[fp] = (i, ln)
        have: set[int] = set()
        for fp in sorted(first_per, key=lambda f: (fpc[f], -first_per[f][0]))[:_OUTCOME_FAIL_MAX]:
            for cand in (first_per[fp], last_per[fp]):
                if cand[0] not in have and len(fails) < _OUTCOME_FAIL_MAX + 2:
                    fails.append(cand)
                    have.add(cand[0])
    # The line immediately before a failure line is the step whose check
    # produced it ("Then the payment is captured" above "Assertion Failed:") —
    # failure context a score cannot see, protected like the failure itself.
    # A context line whose template IS the stream (more than half the input)
    # is a coincidental neighbour — the failing step a repeated but minority
    # template (a LISTEN row in a socket table) still reads as context.
    errctx: list[tuple[int, str]] = []
    if fails:
        fp_counts: dict[str, int] = {}
        for i in nb_i:
            cfp = _log_fingerprint(lines[i]) or lines[i]
            fp_counts[cfp] = fp_counts.get(cfp, 0) + 1
        for i, _ln in fails:
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if (
                j >= 0 and not is_err[j] and not _is_progress_bar(lines[j])
                and not _OUTCOME_BAR_RE.match(lines[j])
                and fp_counts.get(_log_fingerprint(lines[j]) or lines[j], 0) * 2 <= len(nb_i)
            ):
                errctx.append((j, lines[j]))
                # The failing step's record may be a stanza whose head sits
                # above contiguous indented fields ("peer: HASH" over
                # "  allowed ips:", "  transfer:"): the field row right before
                # the failure is only the stanza's last line — walk back over
                # the indent to the unindented opener, the record's landmark.
                k = j
                while k >= 0 and lines[k][:1].isspace() and lines[k].strip():
                    k -= 1
                if (
                    k >= 0 and k != j and lines[k].strip() and not is_err[k]
                    and _OUTCOME_LONE_KV_RE.match(lines[k])
                    and fp_counts.get(_log_fingerprint(lines[k]) or lines[k], 0) * 2 <= len(nb_i)
                ):
                    errctx.append((k, lines[k]))
            if len(errctx) >= 4:
                break
    # A state-valued kv field ("State: DECOMMISSIONED") belongs to a stanza
    # whose head ("Name: 10.3.1.8:7868") is the record's landmark — walk back
    # through the contiguous non-indented field block and take the LAST head
    # opener (secondary fields like "Hostname:" are skipped by the opener RE).
    stanza_openers: list[tuple[int, str]] = []
    for i, _ln in state_kvs[:2]:
        head = None
        for j in range(i - 1, max(-1, i - 9), -1):
            pj = lines[j]
            if not pj.strip() or pj[:1].isspace() or not _OUTCOME_STANZA_FIELD_RE.match(pj):
                break
            if _OUTCOME_STANZA_OPENER_RE.match(pj):
                head = (j, pj)
                break
        if head is not None:
            stanza_openers.append(head)
    # The last columned line of the input is the report's final record — the
    # tail position is where the outcome lands ("Live datanodes (923):" lists
    # end on their last entry). A last line whose template IS the stream
    # (uniform access logs) is just another request — the structural fold's
    # [last] marker already carries it.
    tail_row: list[tuple[int, str]] = []
    if nb_i:
        lt = lines[nb_i[-1]]
        fp = _log_fingerprint(lt) or lt
        if (
            (len(lt.split()) >= 3 or _OUTCOME_ROWSFOOT_RE.match(lt))
            and (not _is_progress_bar(lt) or _OUTCOME_EVIDROW_RE.search(lt))
            and not _OUTCOME_BAR_RE.match(lt)
            and sum(1 for i in nb_i if (_log_fingerprint(lines[i]) or lines[i]) == fp) * 2 <= len(nb_i)
        ):
            tail_row.append((nb_i[-1], lt))
    # The last datarow of each contiguous run is the run's terminal record —
    # the destination hop a traceroute ended on, the device above the SMART
    # report, the queue row above "not_found". When the run ends at a failure
    # that terminal row is the evidence the failure was about; runs broken by
    # unrelated lines don't earn it (err_near bounds it to ~one per failure).
    terminal_rows: list[tuple[int, str]] = []
    for k, (i, ln) in enumerate(datarows):
        nxt = datarows[k + 1][0] if k + 1 < len(datarows) else len(lines) + 1
        if nxt - i > 1 and err_near[i]:
            terminal_rows.append((i, ln))
    # Datarows rank error-neighbouring rows first — the row the error happened
    # on is the evidence, and it PRECEDES the error line (the device above the
    # SMART report, the port above the warning); at equal distance the row
    # before wins over the row after, which belongs to the next section.
    err_idx = [i for i in nb_i if is_err[i]]

    def _errdist(i: int) -> tuple[int, int]:
        if not err_idx:
            return (10**9, 0)
        e = min(err_idx, key=lambda x: abs(x - i))
        return (abs(i - e), 0 if i < e else 1)

    datarows = sorted(
        datarows, key=lambda t: (not err_near[t[0]], _errdist(t[0]), -t[0])
    )[:2] + terminal_rows
    # Numbered records ("Event[90]:" + indented body) repeat by the dozen, so
    # positional caps pick the wrong ones. A record earns protection from its
    # content: a body carrying an error/status evidence line, or the outcome
    # line itself — and the last record always earns it (the tail is where the
    # final state lives). Inside a kept record only the evidence lines are
    # protected — error/status values, summary lines, and description content
    # indented deeper than the boilerplate fields — never the field rows.
    def _section_record(i: int) -> list[tuple[int, str]]:
        rec: list[tuple[int, str]] = []
        for j in range(i + 1, len(lines)):
            ln = lines[j]
            if _OUTCOME_SECTION_RE.match(ln) or (ln.strip() and not ln[:1].isspace()):
                break
            if ln.strip():
                rec.append((j, ln))
        return rec

    ranked_sections: list[tuple[int, str]] = []
    section_body: list[tuple[int, str]] = []
    recs = [(i, ln, _section_record(i)) for i, ln in section_hits]

    def _record_evidence(rec: list[tuple[int, str]]) -> list[tuple[int, str]]:
        ind = min((len(ln) - len(ln.lstrip()) for _j, ln in rec), default=0)
        return [
            (j, ln) for j, ln in rec
            if _OUTCOME_ERR_NEAR_RE.search(ln)
            or _OUTCOME_SUMMARY_RE.match(ln)
            or len(ln) - len(ln.lstrip()) > ind
        ][:_OUTCOME_SECTION_BODY_MAX]

    err_sections = [(i, ln, rec) for i, ln, rec in recs
                    if any(_OUTCOME_ERR_NEAR_RE.search(b) for _j, b in rec)]
    for i, ln, rec in err_sections[:2]:
        ranked_sections.append((i, ln))
        section_body.extend(_record_evidence(rec))
    if recs and (not ranked_sections or ranked_sections[-1][0] != recs[-1][0]):
        i, ln, rec = recs[-1]
        if len(ranked_sections) < 3:
            ranked_sections.append((i, ln))
            section_body.extend(_record_evidence(rec))

    out = []
    seen = set()
    shorts = (
        {ln for _i, ln in ranked_sections}
        | {ln for _i, ln in tables}
        | {ln for _i, ln in section_body}
        | {ln for _i, ln in fails}
        | {ln for _i, ln in lone_kvs}
        | {ln for _i, ln in borders}
        | {ln for _i, ln in datarows}
        | {ln for _i, ln in tail_row}
        | {ln for _i, ln in errctx}
    )
    merged = (
        summary_list + prompt_list + ranked_sections + tables + kvs
        + section_body + fails + lone_kvs + errctx
        + state_kvs[:3] + stanza_openers + datarows + borders + tail_row
    )
    for i, ln in sorted(merged):
        if ln not in seen and _outcome_worthy(ln, allow_short=ln in shorts):
            out.append((i, ln, ln, ln))
            seen.add(ln)
        if len(out) >= _OUTCOME_MAX_LINES:
            break
    return tuple(out)


def _outcome_lines(lines: list[str], n_chars: int) -> tuple[tuple[int, str, str, str], ...]:
    """Memoised ``_outcome_lines_scan`` over the shared ``protected_source``
    split — same cache contract as ``_stream_break_lines``."""
    if n_chars <= _MEMO_MAX_CHARS:
        key = _lines_digest_key(lines, "outcome_lines")
        hit = _CONTENT.get(key)
        if hit is _MISS:
            hit = _outcome_lines_scan(lines)
            _CONTENT.set(key, hit)
        return hit
    return _outcome_lines_scan(lines)


def structural_log_pass(lines: list[str]) -> list[str]:
    """The always-on STRUCTURAL log pass (1.10.0): progress removal, ``[×N]`` template collapse with the last instance kept, and per-cause stack folding. It is :func:`preprocess_logs` with no query: it never drops a distinct error line, an exception head, a ``Caused by`` / inner-exception message, ``... N more``, or the first frame outside the framework, and it is idempotent."""
    return preprocess_logs(_fold_build_noise(lines), "", structural=True)


def preprocess_logs(lines: list[str], query: str = "", *, structural: bool = False) -> list[str]:
    """v0.9.0 log preprocessing (NTK layer1 filter adoption):

    - progress bars / build spam deleted (N4)
    - consecutive same-template repeats collapse to one exemplar plus a
      count marker "[\u00d7N] ..." — counts are decision-relevant (N1)
    - markers are fingerprint-inert so preprocessing is idempotent (N2)
    - error-signal invariant: if a transform would remove ALL error lines,
      the errors are restored (N6)
    - Go/Java-style indented frame runs collapse like Python traces,
      preserving first user frame (N3)
    """
    out: list[str] = []
    # v1.4.0 (N6): out_src[k] is the index in `lines` that out[k] came from, so
    # restored error lines can go back to their original relative position.
    out_src: list[int] = []
    trace: list[str] = []
    trace_src: list[int] = []
    trace_idx: list[int] = []
    query_match_indices: set[int] = set()
    query_selectors = distinctive_query_terms(query or "")
    # Perf (v1.5.0): a line is fingerprinted up to three times below (collapse,
    # count attach, error restore); the fingerprint is a pure function of it.
    fp_memo: dict[str, str | None] = {}

    def fingerprint(line: str) -> str | None:
        try:
            return fp_memo[line]
        except KeyError:
            fp = _log_fingerprint(line)
            if fp is not None and structural and not query_selectors and _is_error_line(line):
                # 1.10.0: without a query, two error lines are the same line only when their text is
                # identical apart from the leading timestamp (ids, keys and values are the evidence).
                fp = "!" + line[_lead_ts_end(line):].strip()[:_FINGERPRINT_CAP]
            fp_memo[line] = fp
            return fp

    def flush_trace() -> None:
        nonlocal trace, trace_src, trace_idx
        if not trace:
            return
        # 1.10.0: per-cause chain folding (heads, messages and "... N more" are kept; frame runs fold).
        folded, folded_src = _fold_trace_run(trace, trace_src, trace_idx, query_match_source_indices)
        out.extend(folded)
        out_src.extend(folded_src)
        trace = []
        trace_src = []
        trace_idx = []

    # 1.10.0 (S5): indices into `lines` of the protected fact lines — they never fold (below).
    # The memoised fingerprint() is shared so each line is still fingerprinted once.
    fact_protected_src = _fact_protected_set(lines, fingerprint) | _outcome_protected_set(lines)
    # First pass: drop progress bars but remember whether we saw any. A
    # protected line is exempt — a "%" column in a landmark row (nodetool's
    # Owns%, an mtr hop's loss%) reads as a bar to the shape check but is the
    # evidence, not noise.
    kept_src = [i for i, ln in enumerate(lines) if not _is_progress_bar(ln) or i in fact_protected_src]
    kept_lines = [lines[i] for i in kept_src]

    query_match_source_indices: set[int] = set()
    if query_selectors:
        selector_tests = [_term_test(selector) for selector in query_selectors]
        candidates = [
            idx
            for idx, line in enumerate(kept_lines)
            if _any_test(selector_tests, line.casefold())
        ]
        # Drop saturated repeated templates only when another strong query hit remains.
        if candidates:
            fp_total = {}
            fp_hit = {}
            candidate_set = set(candidates)
            for idx, line in enumerate(kept_lines):
                fp = fingerprint(line)
                if fp is None:
                    continue
                fp_total[fp] = fp_total.get(fp, 0) + 1
                if idx in candidate_set:
                    fp_hit[fp] = fp_hit.get(fp, 0) + 1
            saturated = {
                fp
                for fp, total in fp_total.items()
                if total >= 3 and fp_hit.get(fp, 0) == total
            }
            if saturated:
                strong_tests = [
                    _term_test(sel)
                    for sel in query_selectors
                    if not sel.startswith("script:") and len(sel) >= 4
                ]
                if strong_tests:
                    candidate_fps = {
                        idx: fingerprint(kept_lines[idx]) for idx in candidates
                    }
                    if any(
                        candidate_fps[idx] not in saturated
                        and _any_test(strong_tests, kept_lines[idx].casefold())
                        for idx in candidates
                    ):
                        candidates = [
                            idx
                            for idx in candidates
                            if candidate_fps[idx] not in saturated
                        ]
        if len(candidates) <= MAX_QUERY_TEMPLATE_MATCHES:
            query_match_source_indices = set(candidates)
        else:
            # Evenly sample the full match span. This retains head/tail and
            # representative middle records without turning one common
            # selector (for example "stage 3") into thousands of blocks.
            last = len(candidates) - 1
            query_match_source_indices = {
                candidates[(slot * last) // (MAX_QUERY_TEMPLATE_MATCHES - 1)]
                for slot in range(MAX_QUERY_TEMPLATE_MATCHES)
            }

    seen: dict[str, int] = {}
    exemplar_idx: dict[str, int] = {}
    protected_out_indices: set[int] = set()  # E12: verbatim out slots the count pass must not rewrite
    last_seen: dict[str, str] = {}  # v1.4.0 (E10): last instance of each template

    short_counts: dict[str, int] = {}
    for line in kept_lines:
        fp = fingerprint(line)
        if fp:
            short_counts[fp] = short_counts.get(fp, 0) + 1
    # 1.10.0: without a query the pass cannot tell which rare variant matters, so a template seen fewer than
    # _STRUCT_COLLAPSE_MIN times stays verbatim; only a dominant template folds into "[×N] exemplar + [last]".
    collapse_floor = _STRUCT_COLLAPSE_MIN if structural and not query_selectors else 0

    i = 0
    n = len(kept_lines)
    while i < n:
        line = kept_lines[i]
        is_trace_like = _is_trace_line(line) or bool(
            (trace or (out and _looks_indented_frame(line))) and _LEADING_SPACE_RE.match(line)
        )
        if is_trace_like:
            trace.append(line)
            trace_src.append(kept_src[i])
            trace_idx.append(i)
            i += 1
            continue
        flush_trace()
        if i in query_match_source_indices:
            # Volatile values can be the selector (for example "policy 17").
            # Keep the exact matching record outside numeric-template collapse.
            query_match_indices.add(len(out))
            out.append(line)
            out_src.append(kept_src[i])
            i += 1
            continue
        if kept_src[i] in fact_protected_src:
            # 1.10.0 (S5): a protected fact line is never collapsed — it stays verbatim. Only the
            # newest of same-key facts is protected, so a superseded value still folds away.
            protected_out_indices.add(len(out))
            out.append(line)
            out_src.append(kept_src[i])
            i += 1
            continue
        fp = fingerprint(line)
        if fp and short_counts.get(fp, 0) >= collapse_floor and (_template_long_enough(line) or (short_counts.get(fp, 0) >= 5 and sum(ch.isalpha() for ch in line) >= 2 and "=" not in line)):
            if fp in exemplar_idx:
                seen[fp] += 1
                last_seen[fp] = line
                i += 1
                continue
            exemplar_idx[fp] = len(out)
            seen[fp] = 1
        out.append(line)
        out_src.append(kept_src[i])
        i += 1
    flush_trace()

    # Attach counts: replace exemplar line with counted variant.
    # v1.4.0 (E10): a template seen >=3 times keeps its LAST instance verbatim
    # on the next line ("[last] ..."), so the end state of a repeating failure
    # survives next to the first one.
    counted_out: list[str] = []
    counted_src: list[int] = []
    for idx, ln in enumerate(out):
        if idx in query_match_indices or idx in protected_out_indices:
            counted_out.append(ln)
            counted_src.append(out_src[idx])
            continue
        fp = fingerprint(ln)
        cnt = seen.get(fp, 1) if fp else 1
        if fp and cnt > 1 and not ln.lstrip().startswith("[\u00d7"):
            counted_out.append(f"[\u00d7{cnt}] {ln}")
            counted_src.append(out_src[idx])
            last = last_seen.get(fp)
            if cnt >= 3 and last is not None and last != ln:
                counted_out.append(f"[last] {last}")
                counted_src.append(out_src[idx])
        else:
            counted_out.append(ln)
            counted_src.append(out_src[idx])
    result = counted_out
    out_src = counted_src

    # N6 error-signal invariant: original error lines that are missing from
    # the output must be restored. v1.4.0: a line counts as present when an
    # exemplar of its template is present (possibly prefixed "[×N] "), so the
    # 499 copies a "[×500] ..." exemplar already stands for are NOT re-added;
    # genuinely missing lines go back at their ORIGINAL relative position, not
    # at the top.
    def has_error_signal(text: str) -> bool:
        return bool(_ERROR_RE.search(text))

    # 1.10.0: a stack FRAME that merely mentions "Error"/"Exception" in a class name is not an error line
    # (folding it is the point), and a trust-risk line (injection-shaped text) is never restored as one.
    orig_errors = [
        (i, ln)
        for i, ln in enumerate(lines)
        if has_error_signal(ln) and not _is_frame_line(ln) and not _FRAMES_FOLDED_RE.match(ln)
        and not _is_trust_risk_line(ln)
    ]
    if orig_errors:
        present_lines = set(result)
        present_fps: set[str] = set()
        for ln in result:
            if has_error_signal(ln):
                fp = fingerprint(_COUNT_PREFIX_RE.sub("", ln, count=1))
                if fp:
                    present_fps.add(fp)
        missing: list[tuple[int, str]] = []
        for src_idx, ln in orig_errors:
            if ln in present_lines:
                continue
            fp = fingerprint(ln)
            if fp and fp in present_fps:
                continue
            if fp:
                present_fps.add(fp)  # one restored exemplar stands for the template
            missing.append((src_idx, ln))
        if missing:
            merged: list[str] = []
            mi = 0
            for pos, ln in enumerate(result):
                # Restored lines go after every kept line that precedes them
                # in the original (ties: the kept line first), before the next.
                while mi < len(missing) and missing[mi][0] < out_src[pos]:
                    merged.append(missing[mi][1])
                    mi += 1
                merged.append(ln)
            merged.extend(ln for _, ln in missing[mi:])
            result = merged

    return _collapse_blanks(result)


_FRAME_GOROUTINE_RE = re.compile(r"^\s+goroutine \d+")
_FRAME_JAVA_RE = re.compile(r"^\s*at\s+[\w$.]+\(")
_FRAME_GO_RE = re.compile(r"^\s*[\w().*/]+\([\w/.$-]+:\d+\)")
_FRAME_CALL_RE = re.compile(r"^\s+[\w./$-]+\([^)]*:\d+\)")
_LEADING_SPACE_RE = re.compile(r"^\s+")


def _looks_indented_frame(line: str) -> bool:
    """Go/Java-style stack frame shapes (NTK classifier table, subset)."""
    t = line.strip()
    if _FRAME_GOROUTINE_RE.match(t) or "goroutine" in t[:40]:
        return True
    if _FRAME_JAVA_RE.match(t):          # Java: at org.x.Y.f(Foo.java:12)
        return True
    if _FRAME_GO_RE.match(t):  # Go: pkg.Fn(/path/file.go:88)
        return True
    if _FRAME_CALL_RE.match(t):
        return True
    return False


def _crush_value(
    val: Any,
    depth: int,
    query_needles: list[str],
    query_selectors: list[re.Pattern[str]] | None = None,
) -> Any:
    if query_selectors is None:
        query_selectors = _selector_patterns(query_needles)
    if depth > 10:
        return val
    if val is None:
        return None
    if isinstance(val, list):
        if not val:
            return []
        matching = []
        rest = []
        for item in val:
            blob = json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item
            if query_selectors and any(selector.search(blob) for selector in query_selectors):
                matching.append(
                    _crush_value(item, depth + 1, query_needles, query_selectors)
                )
            else:
                rest.append(item)
        # No Baseline RAG first-3 cliff: if nothing matches, keep the
        # whole array. Destructive crush only happens when needles hit.
        if matching:
            leftover = len(val) - len(matching)
            if leftover > 0:
                matching.append(f"... {leftover} more items")
            return matching
        return [
            _crush_value(x, depth + 1, query_needles, query_selectors)
            for x in val
        ]
    if isinstance(val, dict):
        out: dict[str, Any] = {}
        for k, v in val.items():
            if v is None:
                continue
            if isinstance(v, list) and not v:
                continue
            if isinstance(v, str) and not re.search(r"\s", v):
                # Opaque values are commonly hashes, tokens or identifiers;
                # shortening or dropping them destroys their exact meaning.
                out[k] = v
                continue
            if isinstance(v, str) and len(v) > 200:
                if query_selectors and any(
                    selector.search(v) for selector in query_selectors
                ):
                    out[k] = v
                    continue
                # lcc TRIM refusal: if the tail being cut carries a
                # qualifier/negation cue, truncation can invert the claim
                # ("granted to all staff" ← "…, except contractors").
                # A longer safe value beats a shorter misleading one.
                if _QUALIFIER_CUE_RE.search(v, 100):
                    out[k] = v
                    continue
                out[k] = v[:100] + f"... [{len(v) - 100} more chars]"
                continue
            out[k] = _crush_value(v, depth + 1, query_needles, query_selectors)
        return out
    return val


def _json_query_needles(query: str) -> list[str]:
    terms = set(distinctive_query_terms(query))
    terms.update(_extract_entities(query))
    strong = {
        term
        for term in terms
        if any(ch.isdigit() for ch in term)
        or "-" in term
        or "_" in term
        or len(term) >= 8
    }
    return sorted(strong or terms)

_JSON_SUMMARY_STOP_WORDS = {
    "which", "what", "where", "when", "there", "their", "about", "with",
    "from", "that", "this", "have", "were", "been", "does", "didn", "why",
    "show", "list", "item", "items",
}
_JSON_SUMMARY_TRIGGERS = (
    "error", "fail", "exception", "denied", "invalid", "refund",
    "suspend", "timeout", "quota", "reject", "cancel",
)

def _summarize_json_arrays(value: Any, query: str) -> tuple[Any, bool]:
    changed = False
    query_words = set()
    for word in re.findall(r"[a-z]+", query.lower()):
        if len(word) < 4 or word in _JSON_SUMMARY_STOP_WORDS:
            continue
        query_words.add(word)
        for suffix in ("s", "ed", "ing"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                query_words.add(word[:-len(suffix)])

    def process(node: Any, depth: int) -> Any:
        nonlocal changed
        if depth > 10:
            return node
        if isinstance(node, dict):
            return {key: process(val, depth + 1) for key, val in node.items()}
        if isinstance(node, list):
            items = [process(item, depth + 1) for item in node]
            if len(items) >= 20 and all(isinstance(item, dict) for item in items):
                key_counts = {}
                for item in items:
                    for key in item:
                        key_counts[key] = key_counts.get(key, 0) + 1
                common = {key for key, count in key_counts.items() if count >= len(items) * 0.9}
                dominant = {}
                dominant_counts = {}
                for key in common:
                    values = [item.get(key) for item in items]
                    if all(isinstance(val, (str, bool)) or val is None for val in values):
                        value_counts = {}
                        for val in values:
                            value_counts[val] = value_counts.get(val, 0) + 1
                        best, best_count = max(value_counts.items(), key=lambda kv: kv[1])
                        if best_count >= len(items) * 0.8:
                            dominant[key] = best
                            dominant_counts[key] = best_count
                keep = []
                item_texts = [json.dumps(item, ensure_ascii=False).lower() for item in items]
                distinctive_query_words = {
                    word
                    for word in query_words
                    if sum(word in item_text for item_text in item_texts) <= len(items) * 0.2
                }
                for item, item_text in zip(items, item_texts):
                    unusual = any(key not in common for key in item)
                    if not unusual:
                        unusual = any(item.get(key) != val for key, val in dominant.items())
                    if not unusual:
                        unusual = any(trigger in item_text for trigger in _JSON_SUMMARY_TRIGGERS)
                    if not unusual and distinctive_query_words:
                        unusual = any(word in item_text for word in distinctive_query_words)
                    if unusual:
                        keep.append(item)
                if keep and len(keep) <= len(items) * 0.2:
                    changed = True
                    first = items[0]
                    new_items = []
                    if not any(first is item for item in keep):
                        new_items.append(first)
                    new_items.extend(keep)
                    omitted = len(items) - len(new_items)
                    common_ordered = [key for key in first if key in common]
                    if dominant:
                        summary = "; ".join(
                            f"{key}={json.dumps(dominant[key], ensure_ascii=False)} x{dominant_counts[key]}"
                            for key in common_ordered
                            if key in dominant
                        ) or "no dominant values"
                    else:
                        summary = "no dominant values"
                    new_items.append(
                        f"... {omitted} similar items omitted (keys: {', '.join(common_ordered)}; "
                        f"original array: {summary})"
                    )
                    return new_items
            return items
        return node

    return process(value, 0), changed

def _summarize_ndjson(stripped: str, query: str) -> str | None:
    lines = [line for line in stripped.splitlines() if line.strip()]
    if len(lines) < 20:
        return None

    parsed = []
    for line in lines:
        try:
            obj = loads_for_rewrite(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(obj, dict):
            return None
        parsed.append(obj)

    try:
        result, changed = _summarize_json_arrays(parsed, query)
    except RecursionError:
        return None

    if not changed or not isinstance(result, list):
        return None

    used = set()
    rendered = []
    for item in result:
        if isinstance(item, str):
            rendered.append(item)
        else:
            for j, candidate in enumerate(parsed):
                if j in used:
                    continue
                if candidate == item:
                    used.add(j)
                    rendered.append(lines[j])
                    break
            else:
                return None

    rendered_text = "\n".join(rendered)
    if len(rendered_text) < len(stripped) * 0.92:
        return rendered_text
    return None


def preprocess_json(text: str, query: str) -> str:
    """Crush whole-document JSON. 1.10.0 (S5): protected fact lines inside the text are restored
    verbatim — the crush may shorten them but may not delete them."""
    return _restore_fact_lines(text, _crush_json_text(text, query))


def _crush_json_text(text: str, query: str) -> str:
    stripped = text.strip()
    if not query_has_distinctive_selectors(query):
        try:
            parsed = loads_for_rewrite(stripped)
        except (ValueError, RecursionError):
            ndjson = _summarize_ndjson(stripped, query)
            if ndjson is not None:
                return ndjson
            return text
        try:
            result, changed = _summarize_json_arrays(parsed, query)
        except RecursionError:
            return text
        if changed:
            try:
                dumped = json.dumps(result, ensure_ascii=False, indent=2)
            except (TypeError, ValueError, RecursionError):
                return text
            if len(dumped) < len(stripped) * 0.92:
                return dumped
        return text
    needles = _json_query_needles(query)
    try:
        parsed = loads_for_rewrite(stripped)
    except (ValueError, RecursionError):  # JSONDecodeError + the 4300-digit int limit
        return text
    try:
        crushed = _crush_value(parsed, 0, needles)
    except RecursionError:
        return text
    try:
        dumped = json.dumps(crushed, ensure_ascii=False, indent=2)
    except (TypeError, ValueError, RecursionError):
        return text
    if len(dumped) < len(stripped) * 0.92:
        return dumped
    return text


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 6 or lines[0].count(",") < 2:
        return False
    # Paragraph prose is not a table: CSV rows are not separated by blank lines.
    raw = text.split("\n", 120)[:120]
    if sum(1 for ln in raw if not ln.strip()) > 0.3 * len(raw):
        return False
    similar = sum(1 for ln in lines[1:40] if ln.count(",") >= 2)
    if similar < 4:
        return False
    # v1.4.0 (E4): code is not CSV. A numbered read, code lines, or an unstable
    # column count (a JS file whose first line happens to hold commas) is not a
    # table, however many commas it has.
    return not rejects_table(lines)


def _selector_patterns(terms: Iterable[str]) -> list[re.Pattern[str]]:
    return [
        re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE)
        for term in terms
    ]


def preprocess_csv(
    text: str,
    query: str,
    gap_marker: Callable[[int, int], str] | None = None,
) -> str:
    """Keep header + distinctive-matching rows. No first-N cliff.

    ``gap_marker(omitted_chars, total_chars)`` marks each run of dropped rows
    (v1.4.0); ``None`` keeps the output byte-identical to earlier releases."""
    if not query_has_distinctive_selectors(query) or not _looks_like_csv(text):
        return text
    terms = [t for t in distinctive_query_terms(query) if not t.startswith("script:")]
    if not terms:
        return text
    selectors = _selector_patterns(terms)
    lines = text.split("\n")
    # 1.10.0 (S5): a fact-shaped row is never a dropped row — a selector that fails
    # to match it must not delete it (only the newest of same-key facts counts).
    # 1.10.0 (S5, E6): neither is a protected error exemplar.
    fact_protected = (
        _fact_protected_set(lines) | _error_protected_set(lines)
        | _outcome_protected_set(lines)
    )
    kept = [lines[0]]
    flags = [False] * len(lines)
    flags[0] = True
    for idx, line in enumerate(lines[1:], 1):
        if idx in fact_protected or any(selector.search(line) for selector in selectors):
            kept.append(line)
            flags[idx] = True
    if len(kept) == 1 or len(kept) == len(lines):
        return text
    if gap_marker is None:
        return "\n".join(kept)
    out: list[str] = []
    run: list[str] = []
    for line, keep in zip(lines, flags):
        if keep:
            if run:
                dropped = "\n".join(run)
                if dropped.strip():
                    out.append(str(call_gap_marker(gap_marker, len(dropped), len(text), "rows")))
                run = []
            out.append(line)
        else:
            run.append(line)
    if run:
        dropped = "\n".join(run)
        if dropped.strip():
            out.append(str(call_gap_marker(gap_marker, len(dropped), len(text), "rows")))
    return "\n".join(out)


_FLAT_RECORD_RE = re.compile(r"^[^\s:#][^:\n]{0,200}:\s+\S.*$")


def preprocess_flat_records(text: str, query: str) -> str:
    """Select exact rows from a flat key/value record dump."""
    if not query_has_distinctive_selectors(query):
        return text
    lines = text.split("\n")
    if any(not line.strip() for line in lines):
        return text
    if len(lines) < 6 or not all(_FLAT_RECORD_RE.match(line) for line in lines):
        return text
    terms = [
        term
        for term in distinctive_query_terms(query)
        if not term.startswith("script:")
    ]
    selectors = _selector_patterns(terms)
    # 1.10.0 (S5): flat records are key/value facts — a row the selectors miss stays.
    # 1.10.0 (S5, E6): so does a protected error exemplar.
    fact_protected = (
        _fact_protected_set(lines) | _error_protected_set(lines)
        | _outcome_protected_set(lines)
    )
    kept = [
        line
        for index, line in enumerate(lines)
        if index in fact_protected or any(rx.search(line) for rx in selectors)
    ]
    if not kept or len(kept) == len(lines):
        return text
    return "\n".join(kept)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TEST_SUMMARY_RE = re.compile(r"Tests\s+\d+\s+passed", re.IGNORECASE)
_TEST_FILE_NOISE_RE = re.compile(
    r"ExperimentalWarning|Use `node --trace-warnings|^\s*[✓✔]\s"
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def preprocess_test_runner(
    text: str,
    query: str,
    content_hint: str | None = None,
    gap_marker: Callable[[int, int], str] | None = None,
) -> str:
    """Keep suite summary; drop per-file ticks and node warnings.

    Super does this on vitest dumps. Skip if the query names a test file.

    v1.4.0 (E5): pytest, jest, go test and cargo test output is reduced to its
    failure blocks and summary lines (``agent_formats.preprocess_test_output``);
    passing per-test lines become a count marker (or ``gap_marker``). Applied
    when the runner is recognised, or when ``content_hint == "test"``.
    """
    if content_hint in (None, "test"):
        reduced = preprocess_test_output(
            text, query, gap_marker=gap_marker, force=content_hint == "test"
        )
        if reduced is not None:
            return reduced
    plain = strip_ansi(text)
    if not _TEST_SUMMARY_RE.search(plain):
        return text
    q = (query or "").lower()
    if re.search(r"\.(test|spec)\.\w+|__tests__/", q):
        return text
    kept = []
    for ln in text.split("\n"):
        p = strip_ansi(ln)
        if _TEST_FILE_NOISE_RE.search(p):
            continue
        kept.append(p)
    if len(kept) >= len(text.split("\n")):
        return text
    return "\n".join(kept)


# A reduced test run at most this long is final (never re-scored).
_TEST_REDUCTION_FINAL_CHARS = 16000
_FILLER_COMMENT_RE = re.compile(r"^(--|#)\s*filler\b", re.IGNORECASE)
_TRUST_RISK_RE = re.compile(
    r"\b(?:untrusted|not\s+operational)\b"
    r"|\b(?:obsolete|unrelated)\b.{0,24}"
    r"\b(?:glossary|example|sample|entry|data)\b"
    r"|\b(?:ignore|disregard|override|forget)\b.{0,48}"
    r"\b(?:instructions?|prompt|system)\b",
    re.IGNORECASE,
)
_TRUST_QUERY_RE = re.compile(
    r"\b(?:injection|untrusted|malicious|prompt\s+attack|obsolete|unrelated)\b"
    r"|\bignore\s+(?:prior|previous)\b",
    re.IGNORECASE,
)
# v0.6.0: a query that says "trust nothing from untrusted sources",
# "exclude untrusted …" etc. is asking for the SAFE behaviour — it must
# NOT suppress the trust-risk flag. Only explicit include-phrasing
# ("include the untrusted block verbatim") counts as an override.
_TRUST_EXCLUDE_CUE_RE = re.compile(
    r"\b(?:trust\s+nothing|don't\s+trust|do\s+not\s+trust|exclude|filter\s+out|omit)\b"
    r".{0,40}\b(?:untrusted|unverified|malicious)\b"
    r"|\b(?:exclude|drop|skip|omit)\s+(?:any\s+)?(?:untrusted|unverified|malicious)\b",
    re.IGNORECASE,
)


def _normalise_instruction_text(text: str) -> str:
    """Normalise width and remove invisible formatting before classification."""
    text = str(text or "")
    if text.isascii():
        # Perf (v1.4.0): NFKC is the identity on ASCII and ASCII has no Cf
        # (format) characters, so the per-character scan below cannot change
        # anything — it cost ~0.4 s per 850 KB of ASCII log text.
        return text
    normalised = unicodedata.normalize("NFKC", text)
    return "".join(
        char for char in normalised if unicodedata.category(char) != "Cf"
    )


def _is_trust_risk_line(line: str) -> bool:
    """Injection-shaped line (``_TRUST_RISK_RE`` on the normalised text). Never an anchor, a fingerprint or a restored error."""
    return _TRUST_RISK_RE.search(_normalise_instruction_text(line[:_RX_LINE_CAP])) is not None


def preprocess_filler_comments(text: str, query: str) -> str:
    """Drop `-- filler` / `# filler` comments unless the query names them."""
    if "filler" in (query or "").casefold():
        return text
    if not query_has_distinctive_selectors(query or ""):
        return text
    lines = text.split("\n")
    fact_protected = (
        _fact_protected_set(lines) | _error_protected_set(lines)
        | _outcome_protected_set(lines)
    )
    kept = [
        ln
        for index, ln in enumerate(lines)
        if index in fact_protected or not _FILLER_COMMENT_RE.match(ln.strip())
    ]
    if len(kept) == len(lines):
        return text
    return "\n".join(kept)


_UNWRAP_ALIAS_WARNED = False


def unwrap_hermes_tool(text: str) -> str:
    """Deprecated alias: use ``unwrap_tool_payload(text).inner`` (the wrapper is not Hermes-specific).

    Same output as before; emits one ``DeprecationWarning`` per process."""
    global _UNWRAP_ALIAS_WARNED
    if not _UNWRAP_ALIAS_WARNED:
        _UNWRAP_ALIAS_WARNED = True
        warnings.warn(
            "unwrap_hermes_tool is deprecated; use unwrap_tool_payload(text).inner",
            DeprecationWarning, stacklevel=2,
        )
    return unwrap_tool_payload(text).inner


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ToolPayload:
    """A tool result split into its text payload and its envelope (v1.4.0).

    ``inner``   the payload text (the whole input when it was not wrapped)
    ``field``   ``"content"`` or ``"output"`` when unwrapped, else ``None``
    ``meta``    the OTHER top-level keys whose values are scalars
                (str/int/float/bool/None), in original key order — for Hermes
                tools that is ``exit_code``, ``error``, ``total_lines``, ...
    ``wrapped`` True when the input was a JSON object wrapper
    ``order``   every top-level key of the original object, in order (lets
                :func:`rewrap_tool_payload` put the payload back where it was);
                not part of equality or repr, so ``ToolPayload(inner, field,
                meta, wrapped)`` built by hand compares equal to an unwrapped one
    """

    inner: str
    field: str | None
    meta: dict
    wrapped: bool
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)


def unwrap_tool_payload(text: str) -> ToolPayload:
    """Split a Hermes tool result into payload and envelope.

    Detection mirrors :func:`unwrap_hermes_tool`: a JSON object with a string
    ``content`` or ``output`` longer than 200 chars (``content`` first).
    Anything else comes back as ``ToolPayload(text, None, {}, False)``.
    A recognized report document (SARIF, notebook, GraphQL) is NOT a tool
    envelope even when it carries a long ``content``/``output`` property.
    """
    unwrapped = ToolPayload(inner=text, field=None, meta={}, wrapped=False)
    if not isinstance(text, str):
        return unwrapped
    stripped = text.strip()
    if not stripped.startswith("{"):
        return unwrapped
    try:
        parsed = loads_for_rewrite(stripped)
    except (ValueError, RecursionError):  # JSONDecodeError + the 4300-digit int limit
        return unwrapped
    if not isinstance(parsed, dict) or report_format(parsed) is not None:
        return unwrapped
    for key in ("content", "output"):
        val = parsed.get(key)
        if isinstance(val, str) and len(val) > 200:
            meta = {
                k: v
                for k, v in parsed.items()
                if k != key and (v is None or isinstance(v, (str, int, float, bool)))
            }
            return ToolPayload(
                inner=val, field=key, meta=meta, wrapped=True, order=tuple(parsed)
            )
    return unwrapped


def rewrap_tool_payload(payload: ToolPayload, new_inner: str) -> str:
    """Rebuild a tool-result JSON object around a replacement payload.

    ``new_inner`` goes back under ``payload.field`` and the scalar ``meta``
    keys keep their original order; non-scalar keys the unwrap dropped are not
    restored. An unwrapped payload returns ``new_inner`` unchanged. Compact
    separators, so the result is one line of JSON that Hermes' own
    ``"exit_code"\\s*:\\s*N`` matchers still read.
    """
    if not payload.wrapped or payload.field is None:
        return new_inner
    out: dict[str, Any] = {}
    for key in payload.order:
        if key == payload.field:
            out[key] = new_inner
        elif key in payload.meta:
            out[key] = payload.meta[key]
    if payload.field not in out:
        out[payload.field] = new_inner
    for key, value in payload.meta.items():
        out.setdefault(key, value)
    return _compact_json(out)


# v1.4.0 (E8): caller-supplied routing hints. diff/grep/test are recorded in
# the receipt only (their adapters arrive later); they route like None.
_CONTENT_HINTS = frozenset(
    {"code", "numbered_code", "log", "json", "text", "diff", "grep", "test"}
)
_CODE_HINTS = frozenset({"code", "numbered_code"})
# Hints whose content must never be read as a table: source code (commas and
# colons are syntax) and logs (a Java "12:00:00,123" timestamp makes every line
# look like a two-column CSV row).
_NO_TABLE_HINTS = frozenset({"code", "numbered_code", "log"})
_HINT_ROUTES = {
    "code": "code",
    "numbered_code": "code",
    "log": "log",
    "json": "json",
    "text": "text",
}
# Line-number gutter of numbered code: `cat -n` ("   12\t...") or `N|`.
_GUTTER_RE = _AGENT_GUTTER_RE  # `N\t` (cat -n), `N|` (Hermes read_file), `N: `


def _marker_tuple(markers: Iterable[str] | str | None) -> tuple[str, ...]:
    """Materialise ``recursion_markers`` once: a bare string is ONE marker (not
    a set of characters), non-strings and empty strings are dropped (an empty
    marker would match every line)."""
    if not markers:
        return ()
    if isinstance(markers, str):
        markers = (markers,)
    return tuple(m for m in markers if isinstance(m, str) and m)


def _has_anchored_marker(text: str, markers: tuple[str, ...]) -> bool:
    """True when some line of ``text`` starts with one of ``markers`` (after
    ``lstrip``). Explicit and anchored: a marker merely mentioned mid-line,
    or text that resembles a marker without being one, does not count."""
    if not markers:
        return False
    if any(m in text for m in markers) and any(
        line.lstrip().startswith(markers) for line in text.splitlines()
    ):  # (the substring test is a cheap reject before the line scan)
        return True
    return _marker_in_tool_payload(text, markers)


def _marker_in_tool_payload(text: str, markers: tuple[str, ...]) -> bool:
    """A Hermes tool result is a JSON object around ONE payload string, so a
    marker that opens a line of the payload is escaped inside the JSON text and
    never opens a line of it. Judge the unwrapped payload as well, otherwise a
    host that re-wraps its compacted output (``rewrap_tool_payload``) would see
    that output compressed a second time."""
    if text.lstrip()[:1] != "{":
        return False
    escaped = [json.dumps(m, ensure_ascii=a)[1:-1] for m in markers for a in (False, True)]
    if not any(e in text for e in escaped):
        return False
    inner = unwrap_tool_payload(text).inner
    if inner is text:
        return False
    return any(line.lstrip().startswith(markers) for line in inner.splitlines())


def preprocess(
    text: str, query: str, content_hint: str | None = None
) -> tuple[list[str], str]:
    if (
        type(text) is str
        and type(query) is str
        and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS
        and len(query) <= _MEMO_MAX_QUERY_CHARS
    ):
        # 1.10.0 (S5, E4): the call's fact-density is part of the memo key — a fact-dense
        # compress_context call must get (and leave) machinery-off output for the same text.
        # 1.10.0 (S5, E6): so is the protected error-exemplar set — it changes what the
        # destructive pre-filters keep. (E12): so is the outcome-protected set.
        lines, kind = _preprocess_cached(text, query, content_hint, _FACT_OFF.get(),
                                         _ERR_PROTECTED.get(), _OUTCOME_PROTECTED.get())
        return list(lines), kind
    return _preprocess_scan(text, query, content_hint)


@functools.lru_cache(maxsize=_MEMO_ENTRIES)
def _preprocess_cached(
    text: str, query: str, content_hint: str | None, _facts_off: bool = False,
    _err_prot=frozenset(), _out_prot=frozenset(),
) -> tuple[tuple[str, ...], str]:
    lines, kind = _preprocess_scan(text, query, content_hint)
    return tuple(lines), kind


_PROGRESS_GLYPH_RE = re.compile(
    r"^(?P<prefix>\S+\.\w{1,8}\s+)?([.FEsSx*!PRWN]{40,})"
    r"(\s+\d+\s*/\s*\d+\s*\(\s*\d+%\)|\s+\[\s*\d+%\])?\s*$"
)


def _compact_progress_line(line: str) -> str:
    """A run of 40+ test-progress glyphs becomes one inert summary that keeps every glyph count and the
    1-based position of each non-'.' glyph (first 20), plus any trailing "63 / 630 ( 10%)" counter or
    "[ 60%]" suffix, after an optional "path.py " prefix:
    "[progress x1001: .=1000 F=1 | F@901]". Other lines are returned unchanged."""
    m = _PROGRESS_GLYPH_RE.match(line)
    if m is None:
        return line
    run = m.group(2)
    counts: dict[str, int] = {}
    for ch in run:
        counts[ch] = counts.get(ch, 0) + 1
    marks = [f"{ch}@{i + 1}" for i, ch in enumerate(run) if ch != "."][:20]
    summary = " ".join(f"{ch}={n}" for ch, n in sorted(counts.items()))
    tail = f" | {' '.join(marks)}" if marks else ""
    counter = (m.group(3) or "").strip()
    prefix = m.group("prefix") or ""
    return prefix + f"[progress x{len(run)}: {summary}{tail}]" + (f" {counter}" if counter else "")


def _compact_progress_lines(lines: list[str]) -> list[str]:
    """``_compact_progress_line`` over ``lines`` (the same list object when no line qualifies)."""
    if any(len(ln) >= 40 and _PROGRESS_GLYPH_RE.match(ln) for ln in lines):
        return [_compact_progress_line(ln) for ln in lines]
    return lines


_REPEAT_LINE_MIN_CHARS = 60
_REPEAT_UNIT_MIN_CHARS = 20
_REPEAT_MIN_COUNT = 3


def _fold_repeated_sentences(lines: list[str]) -> list[str]:
    """Fold a line made of one unit repeated back to back into "[\u00d7N] unit".

    Language-independent: uses the line's own repeated whitespace period, not a
    sentence splitter. Lossless apart from exact whitespace between copies.
    """
    folded: list[str] = []
    fact_protected = _fact_protected_set(lines) | _outcome_protected_set(lines)
    for index, line in enumerate(lines):
        t = " ".join(line.split())
        if index not in fact_protected and len(t) >= _REPEAT_LINE_MIN_CHARS:
            u = t + " "
            p = (u + u).find(u, 1)
            if (
                _REPEAT_UNIT_MIN_CHARS <= p < len(u)
                and len(u) % p == 0
                and len(u) // p >= _REPEAT_MIN_COUNT
            ):
                indent = line[: len(line) - len(line.lstrip())]
                folded.append(f"{indent}[\u00d7{len(u) // p}] {u[:p].strip()}")
                continue
        folded.append(line)
    return folded


_SENTENCE_BREAK_RE = re.compile(
    r"(?<=[^\W\d_][.!?\u2026])[\"'\u201d\u2019)\]]*\s+(?=\S)"
    r"|(?<=[\u3002\uff01\uff1f])\s*(?=\S)"
    r"|(?<=[\u0964\u0965\u061f\u06d4])\s+(?=\S)"
    r"|(?<=[\u0e01-\u0e4e])\s+(?=[\u0e01-\u0e4e])"
)


def _split_prose_sentences(lines: list[str]) -> list[str]:
    """Put each sentence of a long multi-sentence prose line on its own line, separated by blank lines, so each sentence is its own block for the prose brief. Lossless apart from the whitespace between sentences."""
    out = None
    for index, line in enumerate(lines):
        if len(line) >= 120:
            parts = [part for part in _SENTENCE_BREAK_RE.split(line.strip()) if part]
            if len(parts) >= 3:
                if out is None:
                    out = lines[:index]
                indent = line[: len(line) - len(line.lstrip())]
                for part_index, part in enumerate(parts):
                    if part_index:
                        out.append("")
                    out.append(indent + part)
                continue
        if out is not None:
            out.append(line)
    return lines if out is None else out


def _preprocess_scan(
    text: str, query: str, content_hint: str | None = None
) -> tuple[list[str], str]:
    lines = _norm_newlines(text).split("\n")
    lines = _compact_progress_lines(lines)
    kind = _HINT_ROUTES.get(content_hint) or route_content_type(lines)
    if kind == "log":
        return preprocess_logs(lines, query), kind
    if kind == "code":
        return _collapse_blanks(lines), kind
    if kind == "json":
        # Decode recognised Hermes content/output wrappers structurally before
        # JSON crushing. json.loads distinguishes escaped newlines from literal
        # backslash-n bytes; a blanket text replacement cannot.
        unwrapped = unwrap_tool_payload(text).inner
        if unwrapped != text:
            return preprocess(unwrapped, query)
        processed = preprocess_json(text, query)
        return processed.split("\n"), kind
    if kind == "text":
        processed = preprocess_flat_records(text, query)
        if processed != text:
            return processed.split("\n"), kind
        lines = _fold_repeated_sentences(lines)
        query_text = query or ""
        distinctive_terms = [
            term
            for term in distinctive_query_terms(query_text)
            if not term.startswith("script:")
        ]
        joined_lines = "\n".join(lines).lower()
        if (
            not (
                query_has_distinctive_selectors(query_text)
                and distinctive_terms
                and not any(
                    term.lower() in joined_lines for term in distinctive_terms
                )
            )
            and _looks_like_repetitive_tool_output(lines)
        ):
            return preprocess_logs(lines, query), kind
    return _collapse_blanks(lines), kind


def _looks_like_repetitive_tool_output(lines: list[str]) -> bool:
    """Heuristic: text-routed tool output that is mostly repeated templates.

    Strict guards (all required) so prose, markdown and short outputs never
    route here: >= 20 non-blank lines; blank lines <= 20% of all lines; no
    markdown structure (a ``^#{1,6} `` heading or a ``` fence); mean non-blank
    line length <= 200; no diff/grep-shaped output; and lines whose
    _log_fingerprint template occurs >= 5 times make up >= 50% of the
    non-blank lines.
    """
    non_blank = [ln for ln in lines if ln.strip()]
    if len(non_blank) < 20:
        return False
    if len(lines) - len(non_blank) > 0.2 * len(lines):
        return False
    text = "\n".join(lines)
    if detect_unified_diff(text):
        return False
    if detect_grep_lines(text):
        paths = set()
        for ln in non_blank:
            m = re.match(r"^([^\s:][^:]*):(\d+):", ln)
            if m:
                paths.add(m.group(1))
        if len(paths) >= 2 or any("/" in p for p in paths):
            return False
    for ln in lines:
        if re.match(r"^#{1,6} ", ln) or ln.startswith("```"):
            return False
    if sum(len(ln) for ln in non_blank) / len(non_blank) > 200:
        return False
    counts: dict[str, int] = {}
    for ln in non_blank:
        fp = _log_fingerprint(ln)
        if fp is not None:
            counts[fp] = counts.get(fp, 0) + 1
    repeated = sum(c for c in counts.values() if c >= 5)
    return repeated >= 0.5 * len(non_blank)


_QUERY_MEMO_CHARS = 8192  # was 2048: a tool call plus a 2000-character user message is longer than that


def _is_han_ord(o: int) -> bool:
    """Han: unified, Extension A, compatibility ideographs, Extension B and later (supplementary planes)."""
    return 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F


def _is_syllabic_ord(o: int) -> bool:
    """A script whose terms match by substring (no word boundaries): Han, kana, hangul, Arabic, Thai."""
    return (
        _is_han_ord(o)
        or 0x3040 <= o <= 0x30FF
        or 0xAC00 <= o <= 0xD7A3
        or 0x0600 <= o <= 0x06FF
        or 0x0E00 <= o <= 0x0E7F
    )


def _nfkc(text: str) -> str:
    """NFKC of ``text`` (identity on ASCII). Classifiers, fingerprints and term extraction read this view, so a
    full-width ``ＥＲＲＯＲ：`` is the ``ERROR:`` it looks like; the output is always the raw slices."""
    return text if text.isascii() else unicodedata.normalize("NFKC", text)


def _extract_terms(query: str) -> list[str]:
    if type(query) is str and len(query) <= _QUERY_MEMO_CHARS:
        return list(_extract_terms_cached(query))
    return _extract_terms_scan(query)


@functools.lru_cache(maxsize=256)
def _extract_terms_cached(query: str) -> tuple[str, ...]:
    return tuple(_extract_terms_scan(query))


def _extract_terms_scan(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    query = _split_cjk_edges(_nfkc(query or ""))
    for raw in _TERM_TOKEN_RE.findall(query):
        term = raw.lower().strip("؟?!.،,;:…\"'()[]")
        if not term:
            continue
        o = ord(raw[0]) if raw else 0
        if _is_han_ord(o):
            continue  # 1.10.0: Han is read as bigrams and trigrams below; a single character is never a term
        is_cjk = _is_syllabic_ord(o)
        if (len(term) <= 2 and not is_cjk) or term in _STOP or term in _KANA_STOP or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    for raw in search_units(query or "")[:128]:
        term = raw.strip("؟?!.،,;:…\"'()[]")
        if not term or term in seen or term in _STOP or term in _KANA_STOP:
            continue
        representative = next((char for char in term if char.isalnum()), term[0])
        script = script_of(representative)
        if script in {"han", "kana", "hangul", "arabic"}:
            continue
        if len(term) <= 2 and script in {None, "latin", "greek", "cyrillic"}:
            continue
        seen.add(term)
        terms.append(term)
    # Hyphenated compound names in the query ("titanium-torsion-rod") are
    # single search terms too — the tokenizer splits them on "-".
    for m in re.findall(r"\b\w+(?:-\w+)+\b", query):
        m = m.lower()
        if m not in _STOP and m not in seen:
            seen.add(m)
            terms.append(m)
    # 1.10.0: Han bigrams/trigrams, minus function words (的/是/了 ...), after the Latin terms.
    for unit in han_units(query):
        if unit not in seen:
            seen.add(unit)
            terms.append(unit)
    return terms


_WEAK_NEXT_CHAT = frozenset(
    {
        "keep",
        "track",
        "every",
        "detail",
        "details",
        "next",
        "chat",
        "start",
        "work",
        "please",
        "note",
        "final",
        "begin",
    }
) | FILLER_WORDS | frozenset(
    # v1.4.0 (E6): conversational filler — a reply made only of these names
    # nothing in the document ("continue", "thanks", "go ahead", "keep going",
    # "carry on", "sounds good"). FILLER_WORDS (format_adapters.py) supplies
    # continue/thanks/thank/ahead/proceed/okay/sure/lgtm/sounds/good/great/
    # yes/yeah/yep/cool/done/again/retry/going/carry/nice/perfect/…
    {"sounds", "looks", "works"}
)

# Words that, alone or together, make a query "filler only": the reply to the
# agent rather than a question about the text ("fix it", "ok thanks", "LGTM").
# Such a query is treated as an EMPTY query on every path (see
# _is_filler_query) — adapters, destructive preprocess, selection, fail-open.
_FILLER_QUERY_WORDS = frozenset(
    _WEAK_NEXT_CHAT
    | _STOP
    | {"fix", "fixes", "do", "so", "now", "then"}
    | {
        # Filler-only: these words only make a query filler when every query word is filler; not stop words because report/resume/happened are real terms in longer queries.
        "happened", "happen", "overview", "tldr", "report", "resume",
        "resumen", "resumir", "résume", "résumé", "résumer", "rapport",
        "informe", "pasó", "ocurrió", "sucedió", "resumo", "resuma",
        "aconteceu", "ocorreu", "relatório", "riassumi", "riassunto",
        "successo", "rapporto", "ringkasan", "rangkuman", "ringkaskan",
        "terjadi", "laporan", "özetle", "özet", "oldu", "rapor", "podsumuj",
        "podsumowanie", "raport", "zusammenfassung", "passiert", "bericht",
        "le", "la", "el", "lo", "il", "de", "du", "di", "o", "a", "e", "y",
        "un", "me", "mi", "se", "ist", "est", "ce", "ne", "es", "isso",
        "esto", "ça", "qu",
        # Filler-only summary/report words for more languages (sv, nl, da, no, fi, cs, ro, hu, el, ru, uk, de, fr).
        "sammanfatta", "sammanfattning", "hände", "hänt",
        "samenvatting", "samenvatten", "vat", "samen", "gebeurd", "verslag",
        "opsummer", "opsummering", "oppsummer", "oppsummering", "sammendrag", "skete", "skjedde",
        "yhteenveto", "tiivistä", "tapahtui", "raportti",
        "shrnutí", "shrň", "shrnout", "stalo",
        "rezumat", "rezumă", "rezumați", "rezuma", "întâmplat",
        "összefoglaló", "összefoglalás", "foglald", "össze",
        "περίληψη", "σύνοψη",
        "резюме", "итог", "итоги", "кратко", "отчет", "отчёт", "резюмируй",
        "підсумок", "підсумуй", "звіт",
        "zusammenfassen", "fasse", "zusammen", "synthèse"
    }
)


def _is_filler_query(query: str) -> bool:
    """True when every word of the query is conversational filler.

    Uppercase variants count ("OK", "LGTM" would otherwise pass the
    distinctive-identifier gate as CAPS tokens). A query with any other word —
    a digit-bearing token, an identifier, a topical noun — is not filler.
    """
    words = re.findall(r"[^\W_]+", (query or "").casefold())
    return bool(words) and all(w in _FILLER_QUERY_WORDS for w in words)


def _topic_terms(query: str) -> list[str]:
    """English topic words that are not stop/generic/next-chat filler."""
    return [
        t
        for t in _extract_terms(query)
        if len(t) >= 4
        and t not in _STOP
        and t not in GENERIC_WORDS
        and t not in _WEAK_NEXT_CHAT
    ]


def _extract_entities(query: str) -> list[str]:
    if type(query) is str and len(query) <= _QUERY_MEMO_CHARS:
        return list(_extract_entities_cached(query))
    return _extract_entities_scan(query)


@functools.lru_cache(maxsize=256)
def _extract_entities_cached(query: str) -> tuple[str, ...]:
    return tuple(_extract_entities_scan(query))


_CJK_EDGE_RE = re.compile(
    r"(?<=[A-Za-z0-9_./\-])(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7a3\U00020000-\U0002fa1f])"
    r"|(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7a3\U00020000-\U0002fa1f])(?=[A-Za-z0-9_./\-])"
)


def _split_cjk_edges(text: str) -> str:
    """A space between an ASCII identifier and the CJK text glued to it (``test_auth.py为什么``), so the identifier
    is one term and the CJK units are others. ASCII and CJK-free text is returned untouched."""
    if text.isascii():
        return text
    return _CJK_EDGE_RE.sub(" ", text)


def _extract_entities_scan(query: str) -> list[str]:
    found: list[str] = []
    query = _split_cjk_edges(_nfkc(query or ""))
    for rx in (_URI_RE, _PATH_RE, _DOTTED_RE, _CAMEL_RE, _QUOTED_RE, _CAPS_RE):
        for m in rx.finditer(query):
            val = m.group(1) if m.lastindex else m.group(0)
            if val and val not in found and len(val) >= 2:
                found.append(val)
    return found


_GIT_ONELINE_RE = re.compile(r"^[0-9a-f]{7,40}\s+\d{4}-\d{2}-\d{2}\s")
_NPM_VERBOSE_RE = re.compile(
    r"^\d+\s+(verbose|info|silly|http|warn|error|timing)\b"
)
_HEX_ID_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _looks_like_line_records(lines: list[str]) -> bool:
    """Git oneline / npm verbose / key/value listings: one record per line.

    Covers sysctl-style and settings-table lines instead of 10-line chunks.
    """
    sample = [ln for ln in lines[:80] if ln.strip()]
    if len(sample) < 8:
        return False
    git_n = sum(1 for ln in sample if _GIT_ONELINE_RE.match(ln))
    npm_n = sum(1 for ln in sample if _NPM_VERBOSE_RE.match(ln))
    if git_n >= 6 or npm_n >= 6:
        return True
    if len(sample) >= 20:
        kv_n = sum(
            1
            for ln in sample
            if len(ln) <= 200 and _KV_RECORD_RE.match(ln)
        )
        if kv_n * 10 >= len(sample) * 9:
            return True
    return False


_KV_RECORD_RE = re.compile(r"^[A-Za-z_][\w.\-/]*\s*(?:=|\|)\s*\S")


def segment_blocks(lines: list[str]) -> list[dict[str, Any]]:
    if _looks_like_line_records(lines):
        blocks: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            blocks.append(
                {
                    "id": len(blocks),
                    "start": i,
                    "end": i,
                    "type": "log" if _NPM_VERBOSE_RE.match(line) else "text",
                    "text": line,
                    "tokens": max(1, estimate_tokens(line)),
                }
            )
        return blocks
    return _segment_blocks_chunked(lines)


def _segment_blocks_chunked(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    start: Optional[int] = None
    btype = "text"
    tokens = 0

    def close(end: int) -> None:
        nonlocal start, tokens
        if start is None:
            return
        while end >= start and not lines[end].strip():
            end -= 1
        if end < start:
            start = None
            tokens = 0
            return
        text = "\n".join(lines[start : end + 1])
        if text.strip():
            blocks.append(
                {
                    "id": len(blocks),
                    "start": start,
                    "end": end,
                    "type": btype,
                    "text": text,
                    "tokens": max(1, tokens or estimate_tokens(text)),
                }
            )
        start = None
        tokens = 0

    prev_type = None
    in_fence = False
    for i, line in enumerate(lines):
        kind = classify_line(line)
        line_toks = estimate_tokens(line)
        if in_fence:
            tokens += line_toks
            if kind == "fence":
                close(i)
                in_fence = False
            prev_type = kind
            continue
        if kind == "fence":
            close(i - 1)
            start = i
            btype = "fence"
            tokens = line_toks
            in_fence = True
            prev_type = kind
            continue
        new = False
        if (
            start is None
            or kind in {"heading", "fence", "definition"}
            or (
                i > 0
                and "[last] " in lines[i - 1]
                and lines[i - 1].lstrip().startswith("[last] ")
                and line.strip()
                and not line.lstrip().startswith(("[\u00d7", "[last] "))
            )
            or kind == "list"
            or (prev_type == "blank" and kind != "blank")
            or (kind != prev_type and kind in {"log", "chat", "import", "list", "table", "json"})
        ):
            new = True
        elif btype == "text" and kind in {"definition", "code"}:
            # A code/definition region starting inside a text block: split so
            # the code has its own block. Otherwise one "fn name(" line
            # classifies the whole block as code and the impl body ends up
            # scored as text.
            new = True
        elif start is not None and (i - start >= 10 or tokens + line_toks > 220):
            new = True
        if new:
            close(i - 1)
            start = i
            btype = kind if kind != "blank" else "text"
            tokens = line_toks
        else:
            tokens += line_toks
            if btype == "text" and kind != "blank":
                btype = kind
        prev_type = kind
    close(len(lines) - 1)
    return blocks



_SEG_BLOCK_TYPE_CODES: dict[str, int] = {}
_SEG_BLOCK_TYPE_NAMES: list[str] = []


def _seg_block_type_code(btype: str) -> int:
    code = _SEG_BLOCK_TYPE_CODES.get(btype)
    if code is None:
        code = len(_SEG_BLOCK_TYPE_NAMES)
        _SEG_BLOCK_TYPE_CODES[btype] = code
        _SEG_BLOCK_TYPE_NAMES.append(btype)
    return code


def _segment_blocks_cached(lines: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    text = chr(10).join(lines)
    if len(text) > _MEMO_MAX_CHARS:
        return tuple(segment_blocks(list(lines)))
    key = content_key(ENGINE_VERSION, "segment_blocks", text)
    hit = _CONTENT.get(key)
    if hit is not _MISS:
        lst = list(lines)
        packed, names = hit
        return tuple(
            {
                "id": i // 4, "start": packed[i], "end": packed[i + 1], "type": names[packed[i + 2]],
                "text": "\n".join(lst[packed[i] : packed[i + 1] + 1]), "tokens": packed[i + 3],
            }
            for i in range(0, len(packed), 4)
        )
    blocks = segment_blocks(list(lines))
    # S7: the record holds packed spans, not text — the dicts used to pin every segment's
    # text (a 28 KB input's ~800 blocks weighed ~631 KB). ``id`` is the slot position; the
    # text is rebuilt from the caller's identical lines on a hit.
    packed = array.array("i")
    for b in blocks:
        packed.extend((b["start"], b["end"], _seg_block_type_code(b["type"]), b["tokens"]))
    _CONTENT.set(key, (packed, _SEG_BLOCK_TYPE_NAMES))
    return tuple(blocks)


def _source_pin_texts(text: str, patterns: list[str] | None, recent: int) -> list[str]:
    """Texts of the original blocks a caller pinned: the caller's floor, which no
    later reduction or summary may drop."""
    if not patterns and not recent:
        return []
    blocks = _segment_blocks_memo(text.split('\n'))
    expressions = compile_pin_patterns(patterns)
    if expressions is None:
        return [text]
    pinned = {block['id'] for block in blocks
              if any(expr.search(block['text']) for expr in expressions)}
    if recent and blocks:
        pinned.add(blocks[0]['id'])
        pinned.update(block['id'] for block in blocks[-recent:])
    return [block['text'] for block in blocks if block['id'] in pinned]


def _segment_blocks_memo(lines: list[str]) -> list[dict[str, Any]]:
    """:func:`segment_blocks`, remembered as compact spans without source text.

    A block is a flat dict of str/int values, so a shallow copy per block is
    a full copy: callers may mutate what they get back.
    """
    if not _MEMO_MIN_CHARS <= sum(map(len, lines)) <= _MEMO_MAX_CHARS:
        return segment_blocks(lines)
    return [dict(b) for b in _segment_blocks_cached(tuple(lines))]




def _score_blocks_memo(
    score_lines: list[str],
    blocks: list[dict[str, Any]],
    query: str,
    content_type: str | None,
    *,
    degraded: bool,
) -> list[dict[str, Any]]:
    """``score_blocks(blocks, query, content_type=...)`` for the blocks of
    ``score_lines``, remembered for the newest few large inputs.

    The key is the line content (the blocks are a function of it), the query
    and the content type; a degraded scoring view rewrites block text and is
    never remembered. Scored blocks are flat dicts, copied on the way out.
    """
    if (
        degraded
        or type(query) is not str
        or len(query) > _MEMO_MAX_QUERY_CHARS
        or not _MEMO_MIN_CHARS <= sum(map(len, score_lines)) <= _MEMO_MAX_CHARS
    ):
        return score_blocks(blocks, query, content_type=content_type)
    key = content_key(ENGINE_VERSION, "scored", chr(0).join(score_lines), (query, content_type))
    hit = _SCORED.get(key)
    if hit is _MISS:
        scored = score_blocks(blocks, query, content_type=content_type)
        _SCORED.set(key, tuple({k: v for k, v in block.items() if k != "text"} for block in scored))
        return scored
    source = {block["id"]: block["text"] for block in blocks}
    return [dict(block, text=source[block["id"]]) for block in hit]


def _clear_memos() -> None:
    """Forget every remembered analysis (tests and benchmarks use this to
    measure a cold call; the engine never needs it)."""
    from . import contract_gates, industrial, unicode_profile

    for fn in (
        _contains_secret_cached, _error_fingerprints_cached, _extract_critical_lines_cached,
        _preprocess_cached, _brief_scan_cached,
        _block_link_terms_cached, _extract_entities_cached, _extract_terms_cached,
        _estimate_tokens_cached, _evidence_blob,
        industrial._profile_input_cached, unicode_profile._search_units_cached,
        contract_gates._distinctive_query_terms_cached, contract_gates._source_blob,
    ):
        fn.cache_clear()
    _CONTENT.clear()
    _SCORED.clear()


def cache_stats() -> dict[str, Any]:
    """Process-wide content/scored-cache counters (S7); keys are digests, never text."""
    return {"content": _CONTENT.stats(), "scored": _SCORED.stats()}


def _soft_has(text: str, needle: str) -> bool:
    if not needle:
        return False
    if needle in text:
        return True
    return needle.lower() in text.lower()


_INFLECT_SUFFIXES = ("ures", "ure", "ing", "ed", "es", "s")
_INFLECT_RE_TAIL = r"(?:s|es|ed|ing|ure|ures)?"


@functools.lru_cache(maxsize=4096)
def _inflection_stem(term: str) -> str | None:
    if not (term.isascii() and term.isalpha() and len(term) >= 4):
        return None
    for suffix in _INFLECT_SUFFIXES:
        if term.endswith(suffix):
            remainder = term[:-len(suffix)]
            if len(remainder) < 4:
                continue
            if suffix == "s" and (remainder[-1] in "sui" or term.endswith("ss")):
                continue
            return remainder
    return term


@functools.lru_cache(maxsize=4096)
def _compiled_term_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a term pattern once, independent of the ``re`` module cache."""
    return re.compile(pattern)


def _term_test(term: str) -> Callable[[str], bool]:
    """``lambda lower: _term_in_text(term, lower)`` with the pattern compiled once."""
    if not term:
        return lambda lower: False
    syllabic = _is_syllabic_ord(ord(term[0]))
    if syllabic or len(term) > 5:
        def base(lower: str) -> bool:
            return term in lower
    else:
        if term.isdigit():
            search = _compiled_term_pattern(rf"(?<!\d:)\b{re.escape(term)}\b(?!:\d)").search
        elif term.isalpha():
            # Treat underscore as a boundary for short alphabetic terms
            # literal first so the regex engine can use its fast prefix scan
            search = _compiled_term_pattern(rf"{re.escape(term)}(?<![^\W_]{re.escape(term)})(?![^\W_])").search
        else:
            search = _compiled_term_pattern(rf"\b{re.escape(term)}\b").search

        def base(lower: str) -> bool:
            return search(lower) is not None
    stem = _inflection_stem(term)
    if stem is None:
        return base
    inflect = _compiled_term_pattern(rf"\b{re.escape(stem)}{_INFLECT_RE_TAIL}\b").search

    def test(lower: str) -> bool:
        return base(lower) or (stem in lower and inflect(lower) is not None)

    return test


def _any_test(tests: list[Callable[[str], bool]], lower: str) -> bool:
    for test in tests:
        if test(lower):
            return True
    return False


def _term_in_text(term: str, lower: str) -> bool:
    """Substring for long / syllabic terms; word-boundary for short Latin."""
    if not term:
        return False
    syllabic = _is_syllabic_ord(ord(term[0]))
    if syllabic:
        if len(term) > 5:
            return term in lower
        return re.search(rf"\b{re.escape(term)}\b", lower) is not None
    if len(term) > 5:
        base = term in lower
    else:
        base = re.search(rf"\b{re.escape(term)}\b", lower) is not None
    if not base:
        stem = _inflection_stem(term)
        if stem is not None and stem in lower and re.search(rf"\b{re.escape(stem)}{_INFLECT_RE_TAIL}\b", lower):
            return True
    return base


@functools.lru_cache(maxsize=16384)
def _dup_fp(text: str) -> str:
    """Duplicate-block key: lowercased, volatile fields masked per line (``mask_template``), capped at 240."""
    parts: list[str] = []
    size = -1
    for line in text[:4000].split("\n"):
        masked = mask_template(line.lower())
        parts.append(masked)
        size += len(masked) + 1
        if size >= 240:
            break
    return " ".join(parts)[:240]


# A query term directly after a negator only counts when the block also shows failure/negation.
# This prevents "not start" from matching boilerplate lines that say a process started.
_NEGATED_TERM_RE = re.compile(r"\b(?:not|never|no|cannot|can't|won't|didn't|doesn't|don't|isn't|wasn't|couldn't|wouldn't|failed to|fails to|unable to)\s+([a-z][a-z0-9_]*)")
_FAILURE_EVIDENCE_RE = re.compile(r"fail|error|err\b|fatal|emerg|crit|panic|unable|cannot|can't|couldn't|refused|denied|timed? ?out|abort|killed|\bnot\b|exit(?:ed)? (?:code|status) [1-9]")

_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)*\b")


def _bridge_index(blocks: list[dict[str, Any]], n: int) -> tuple[list[list[str]], dict[str, list[int]]]:
    """Tokenise each block once and index bridge entities by lowercase token (helper of score_blocks)."""
    bridge_entities: dict[str, int] = {}
    # Perf (v0.6.0): lowercase every block text exactly once. The previous
    # code re-lowered all N texts for every candidate of every block
    # (O(n²·c) .lower() calls) — the dominant cost on large documents.
    # Results are byte-identical; only the redundant work is removed.
    lower_texts = [b["text"].lower() for b in blocks]
    # Perf (v0.6.0): deduplicate candidates globally and resolve df via a
    # token Counter for single-token candidates (the vast majority). Only
    # multi-token phrases pay the exact substring scan. df is the number of
    # blocks holding the token (each token counted once per block), so an
    # identifier repeated inside one block is not a bridge.
    token_counter: dict[str, int] = {}
    token_block_df: dict[str, int] = {}
    # Perf (v0.6.0): one shared \w+ tokenisation per block feeds the counter,
    # the candidate scan AND tok_df below (previously 3 separate passes).
    block_token_lists: list[list[str]] = []
    for lt in lower_texts:
        toks = re.findall(r"\w+", lt)
        block_token_lists.append(toks)
        for w in toks:
            token_counter[w] = token_counter.get(w, 0) + 1
        for w in set(toks):
            token_block_df[w] = token_block_df.get(w, 0) + 1
    seen_candidates: set[str] = set()
    candidate_blocks: dict[str, int] = {}
    for b_idx, b in enumerate(blocks):
        toks = block_token_lists[b_idx]
        # Extract candidate bridge entities: CamelCase, UPPER_SNAKE, dotted
        # paths, quoted strings, and 6+ char tokens with digits (identifiers).
        candidates = set()
        candidates.update(_CAMEL_RE.findall(b["text"]))
        candidates.update(_PROPER_NOUN_RE.findall(b["text"]))  # Proper nouns
        candidates.update(re.findall(r"\b[A-Z][A-Z_][A-Z_0-9]{3,}\b", b["text"]))  # UPPER_SNAKE
        candidates.update(_DOTTED_RE.findall(b["text"]))
        candidates.update(_QUOTED_RE.findall(b["text"]))
        # 6+ char identifier tokens with digits — from the shared token list
        # instead of a second regex sweep over the raw text.
        # Perf (v0.6.0): the any(ch.isdigit()) genexpr over every token was
        # the single hottest line in score_blocks (266k calls). isdigit()
        # on the whole token is equivalent for this gate (we only care
        # whether ANY digit exists, and str.isdigit() short-circuits in C).
        for tok in toks:
            if len(tok) >= 6 and not tok.isdigit() and not tok.isalpha() and tok not in _STOP:
                candidates.add(tok)
        for cand in candidates:
            if len(cand) < 4 or cand in _STOP:
                continue
            is_identifier = (
                cand in cand.upper()  # ALL CAPS (UPPER_SNAKE, acronyms)
                or cand[0].isupper()  # Proper noun or CamelCase
                or re.search(r"\d", cand)  # Contains a digit
                or "." in cand  # Dotted path
            )
            if is_identifier and cand not in seen_candidates:
                seen_candidates.add(cand)
                candidate_blocks[cand] = 0
    for cand in seen_candidates:
        c_lower = cand.lower()
        # Perf (v1.4.0): only single-token candidates can ever match the
        # per-block token sets in the boost loop below; dotted / multi-word /
        # quoted candidates never could, and their df was an O(candidates x
        # blocks) substring scan (thousands of unique `abc123.json` names in a
        # log). Skipping them changes no score.
        if not re.fullmatch(r"\w{4,}", c_lower):
            continue
        df = token_block_df.get(c_lower, 0)
        # Require the entity to be in at least 2 but at most n/2 blocks
        # (if it's in every block, it's a filler word, not a bridge)
        if 2 <= df <= n // 2:
            bridge_entities[cand] = df
    # Index by lowercase token so the per-block boost is O(tokens in block),
    # not O(bridge entities). Boost values are multiples of 0.5, so summation
    # order cannot change a score.
    bridge_by_lower: dict[str, list[int]] = {}
    for ent, span in bridge_entities.items():
        bridge_by_lower.setdefault(ent.lower(), []).append(span)
    return block_token_lists, bridge_by_lower


def _error_exemplar_ids(blocks: list[dict[str, Any]], content_type: str | None) -> set[int]:
    """Ids of the first block carrying each error fingerprint (helper of score_blocks)."""
    error_exemplar_ids: set[int] = set()
    if content_type == "log":
        seen_error_fps: set[str] = set()
        for b in blocks:
            for line in b["text"].splitlines():
                if _is_level_error_line(line):
                    fp = _error_fp(line)
                    if fp not in seen_error_fps:
                        seen_error_fps.add(fp)
                        error_exemplar_ids.add(b["id"])
    elif content_type != "code":
        # v1.6.0 (multilang): compiler/test/runtime diagnostics (DIAGNOSTIC_CODE_LINE_RE: gcc/clang/tsc/
        # rustc/.NET/Kotlin/Swift errors, Ruby/PHP/JS runtime errors, frames, signals) in non-log output keep
        # one exemplar block per fingerprint; non-English level words are excluded so prose is unaffected;
        # bounded so a wall of distinct warnings cannot pin all.
        seen_diag_fps: set[str] = set()
        for b in blocks:
            if len(error_exemplar_ids) >= _DIAG_EXEMPLAR_CAP:
                break
            for line in b["text"].splitlines():
                if (
                    (
                        is_diagnostic_line(line[:_RX_LINE_CAP], code_only=True)
                        # E14: a BRACKETED uppercase level tag ("[CRITICAL]",
                        # "[FATAL]") in any non-code content is the same
                        # exemplar contract as a log ERROR — sslscan-style
                        # reports tag severities without a leading log level
                        # and were invisible here. The bracket is required:
                        # a bare "ERROR" in prose ("ERROR is the name of the
                        # sentinel enum value") is not an exemplar.
                        or _ERR_LEVEL_TAG_RE.search(line[:_RX_LINE_CAP])
                    )
                    and _ERR_NEGATED_RE.search(line[:_RX_LINE_CAP]) is None
                ):
                    fp = _error_fp(line)
                    if fp not in seen_diag_fps:
                        seen_diag_fps.add(fp)
                        error_exemplar_ids.add(b["id"])
    return error_exemplar_ids


def _line_ubiquitous_terms(
    blocks: list[dict[str, Any]],
    query: str,
    n: int,
    is_log_context: bool,
    term_tests: list[tuple[str, Callable[[str], bool]]],
    term_df: dict[str, int],
    entities: list[str],
) -> set[str]:
    """Terms present on >80% of lines of a small log context (helper of score_blocks)."""
    line_ubiquitous_terms = set()
    if is_log_context and n < 10 and blocks:
        non_blank_lines = [
            line.lower()
            for block in blocks
            for line in block["text"].splitlines()
            if line.strip()
        ]
        if non_blank_lines:
            term_test_by_term = {t.lower(): test for t, test in term_tests}
            candidate_terms = {t.lower() for t in term_df}
            candidate_terms.update(t.lower() for t in _topic_terms(query))
            candidate_terms.update(t.lower() for t, _ in term_tests)
            line_counts = {}
            for term in sorted(candidate_terms):
                test = term_test_by_term.get(term)
                if test is None:
                    continue
                line_counts[term] = sum(
                    1 for line in non_blank_lines if test(line)
                )
            entity_line_counts = {}
            entity_block_hits = {}
            for entity in entities:
                entity_line_counts[entity] = sum(
                    1 for line in non_blank_lines if _soft_has(line, entity)
                )
                entity_block_hits[entity] = sum(
                    1 for block in blocks if _soft_has(block["text"], entity)
                )
            raw_line_ubiquitous = {
                term
                for term, count in line_counts.items()
                if count / len(non_blank_lines) > 0.8
            }
            has_selective_signal = any(
                df > 0 and term.lower() not in raw_line_ubiquitous
                for term, df in term_df.items()
            ) or any(
                entity_block_hits.get(entity, 0) > 0
                and entity_line_counts.get(entity, 0) / len(non_blank_lines) <= 0.8
                for entity in entities
            )
            if has_selective_signal:
                line_ubiquitous_terms = raw_line_ubiquitous
    return line_ubiquitous_terms


def _weak_boost(
    blocks: list[dict[str, Any]],
    query: str,
    terms: list[str],
    n: int,
    term_df: dict[str, int],
    line_ubiquitous_terms: set[str],
) -> float:
    """1.0 when the query carries no distinctive information, else 0.0 (helper of score_blocks)."""
    weak_boost = 0.0
    if len(blocks) >= 6 and terms:
        distinctive = 0
        for t in terms:
            if len(t) < 4 or t in _STOP:
                continue
            if re.search(r"[\d_./-]", t) or t[0].isupper():
                distinctive += 1
        # A topic word present in nearly every block is not a topic (IDF floor).
        topic = [
            t for t in _topic_terms(query)
            if (n < 10 or term_df.get(t.lower(), 0) <= 0.8 * n)
            and t.lower() not in line_ubiquitous_terms
        ]
        # English topic words (alena, cinematography) are not "weak" just
        # because they lack digits. Vague next-chat ("keep every detail")
        # still gets the uniqueness floor.
        weak_boost = 0.0 if distinctive > 0 or len(topic) >= 2 else 1.0
    return weak_boost


def _critical_line_counts(blocks: list[dict[str, Any]]) -> list[int]:
    """Count operational-fact lines per block (helper of score_blocks)."""
    crit_lines_per_block: list[int] = []
    for b in blocks:
        cnt = 0
        for line in b["text"].splitlines():
            if _is_critical_line(line):
                cnt += 1
        crit_lines_per_block.append(cnt)
    return crit_lines_per_block


def _token_df(block_token_lists: list[list[str]]) -> tuple[dict[str, int], list[set[str]]]:
    """Per-token block frequency and per-block token sets (helper of score_blocks)."""
    tok_df: dict[str, int] = {}
    # Perf (v0.6.0): reuse the shared per-block token lists (built above for
    # the bridge-candidate scan) — no third tokenisation pass.
    block_token_sets: list[set[str]] = []
    for toks in block_token_lists:
        seen_in_block: set[str] = set()
        block_tokens: set[str] = set(toks)
        for tok in toks:
            if len(tok) >= 4 and tok not in _STOP and tok not in seen_in_block:
                seen_in_block.add(tok)
                tok_df[tok] = tok_df.get(tok, 0) + 1
        block_token_sets.append(block_tokens)
    return tok_df, block_token_sets


def _score_one_block(
    idx: int,
    b: dict[str, Any],
    *,
    n: int,
    entities: list[str],
    entity_df: dict[str, int],
    term_tests: list[tuple[str, Callable[[str], bool]]],
    term_df: dict[str, int],
    ubiquitous_terms: set[str],
    error_exemplar_ids: set[int],
    is_log_context: bool,
    log_err_re: re.Pattern[str] | None,
    log_noise_re: re.Pattern[str] | None,
    crit_lines_per_block: list[int],
    bridge_by_lower: dict[str, list[int]],
    block_token_sets: list[set[str]],
    weak_boost: float,
    tok_df: dict[str, int],
    fp_counts: dict[str, int],
) -> dict[str, Any]:
    """Score one block (the per-block body of score_blocks)."""
    score = 0.0
    reason = "context"
    entity_hits = 0
    term_hits = 0
    rare_term_hits = 0
    for e in entities:
        if _soft_has(b["text"], e):
            entity_hits += 1
            df = entity_df.get(e, 1)
            score += 1.4 + 4.6 * math.log((n + 1) / (df + 1))
            reason = "query entity"
    lower = b["text"].lower()
    # Classification belongs to the block, never to question wording.
    # An intentional override must be explicit through pin_patterns.
    trust_risk = bool(
        _TRUST_RISK_RE.search(_normalise_instruction_text(b["text"]))
    )
    for t, term_test in term_tests:
        if t in ubiquitous_terms:
            continue
        if term_test(lower):
            term_hits += 1
            df = term_df.get(t, 1)
            if df <= max(2, int(0.2 * n)):
                rare_term_hits += 1
            score += 0.9 + 3.2 * math.log((n + 1) / (df + 1))
            if reason == "context":
                reason = "query term"
    if b["type"] == "definition":
        score += 2.0
    if b["type"] == "trace":
        score += 2.8
    if b["type"] == "heading":
        score += 0.8
    if b["type"] == "log" and re.search(r"error|fail|exception|timeout|denied|invalid", lower):
        score += 1.2
    # Old-error purge (leanctx-inspired): errored dumps with ZERO query
    # hits deep inside a large document are handled history — the fact of
    # the error survives via citations; the bulk shouldn't. Only applies
    # when there are enough blocks that recency is meaningful.
    error_exemplar = b["id"] in error_exemplar_ids
    if (
        n >= 12
        and idx < n - 6
        and entity_hits == 0
        and term_hits == 0
        and not error_exemplar
        and (
            b["type"] == "trace"
            or (
                b["type"] == "log"
                and re.search(r"error|fail|exception|denied", lower)
            )
            or "Traceback (most recent call last)" in b["text"]
        )
    ):
        score -= 4.5
        if reason == "context":
            reason = "stale error"

    # Log-context policy (Baseline RAG "Log" policy): in log-heavy
    # contexts, boost error/traceback blocks and penalize pure INFO
    # noise so the signal stands out from the chatter.
    if is_log_context:
        if log_err_re.search(b["text"]):
            score += 3.0
            if reason == "context":
                reason = "log error"
        else:
            lines = b["text"].splitlines()
            noise_lines = sum(
                1 for block_line in lines if log_noise_re.match(block_line)
            )
            if noise_lines >= len(lines) * 0.8 and len(lines) >= 2:
                score -= 1.5
                if reason == "context":
                    reason = "log noise"
    # Critical-line floor: blocks containing operational facts (errors,
    # config, key-value pairs, dates, versions) get a floor boost so
    # they survive even without query overlap. This is the Baseline RAG
    # "important_kept_pct" signal — their verifier tracks critical lines
    # and flags risk when they're dropped. We make it a scoring input
    # instead, so the critical lines are kept in the first place.
    crit = crit_lines_per_block[idx]
    if crit > 0:
        score += min(3.0, 0.8 * crit)
        if reason == "context":
            reason = "critical lines"
    # Bridge-entity boost: blocks that contain cross-block entities (the
    # links in a multi-hop chain) get a floor boost so the chain doesn't
    # get severed. The boost scales with how many blocks the entity spans.
    # Perf (v0.6.0): iterate only over entities present in this block
    # via the precomputed token set instead of scanning every bridge
    # entity for every block (O(n·e) substring scans → O(n + e)).
    bridge_boost = 0.0
    block_tokens = block_token_sets[idx]
    if bridge_by_lower:
        for tok in block_tokens:
            for span in bridge_by_lower.get(tok, ()):
                bridge_boost += 1.5 + 0.5 * min(span, 5)
    if bridge_boost > 0:
        score += bridge_boost
        if reason == "context":
            reason = "bridge entity"
    # Uniqueness floor (ACON insight): if a block contains a
    # high-information identifier that appears in NO OTHER block,
    # it's uniquely valuable. Drop it and the fact is gone forever
    # (unless CCR is enabled). Give it a floor boost so scattered
    # facts survive even when the query doesn't mention them.
    # Only applies when the query is weak (low entropy) — a vague
    # "keep track of every detail" query deserves a higher keep
    # threshold. A strong, specific query ("who won the 1998 world
    # cup") should still evict unrelated blocks even if they're
    # unique.
    unique_id_count = 0
    list_noise = b["type"] == "list" and entity_hits == 0 and term_hits == 0
    if weak_boost > 0 and not list_noise:
        # Perf (v0.6.0): reuse the shared token set — no extra regex pass.
        for tl in block_tokens:
            if len(tl) < 6 or tl in _STOP:
                continue
            if _HEX_ID_RE.match(tl):
                continue
            df = tok_df.get(tl, 0)
            if df == 1:
                unique_id_count += 1
        if unique_id_count >= 2:
            score += min(4.0, 1.5 + 0.8 * unique_id_count)
            if reason in ("context",):
                reason = "unique facts"
    # Recency + novelty prior: recent blocks get a ramp up to ~2.0;
    # rare high-information identifiers (short tokens, dotted paths,
    # UPPER_SNAKE, REL-xxx, 8+ hex) give a small floor so scattered
    # facts survive a vague "keep everything" query.
    # Weak-query boost: when the query has low information content,
    # raise both the recency ramp and the novelty floor so middle
    # blocks survive. This is the rate-distortion H(Q) theory: a
    # vague query deserves a higher keep threshold.
    recency_max = 2.0 + weak_boost
    recency = recency_max * (idx + 1) / n
    score += recency
    novelty = 0.0
    rare_count = 0
    # Perf (v0.6.0): reuse block_token_sets instead of re-tokenising
    # and re-lowering every block here (third full token pass removed).
    for tl in block_token_sets[idx]:
        if len(tl) < 4 or tl in _STOP:
            continue
        if _HEX_ID_RE.match(tl):
            continue
        df = tok_df.get(tl, 0)
        if df <= 2 and not re.match(r"^[a-z]{4}$", tl):
            novelty += 0.6
            rare_count += 1
    # Weak-query boost on novelty floor: raise the cap from 2.4 to
    # 2.4 + weak_boost (up to 3.4) when the query is vague.
    score += min(2.4 + weak_boost, novelty)
    # Fact density: blocks with many distinct rare identifiers are
    # information-dense. Even without query overlap, a block packed
    # with rare facts is worth keeping. This rescues scattered facts
    # in large contexts where the query only mentions a few entities.
    # Threshold: 5+ rare tokens → +1.0, 10+ → +2.0, 15+ → +3.0 (cap).
    if rare_count >= 5 and not list_noise:
        fact_density = min(3.0, 0.2 * rare_count)
        score += fact_density
    # Recency / sinks
    if idx == 0:
        score += 0.35
    if idx == n - 1:
        score += 0.45
    fp = _dup_fp(b["text"])
    dup = fp_counts.get(fp, 0)
    if dup > 1:
        score -= min(3.0, dup * 0.8)
    if trust_risk:
        score -= 50.0
        reason = "untrusted instruction"
    # Final stale-error cap: after every boost (recency, novelty,
    # fact-density), a handled error dump must stay below the adaptive
    # floor minimum so it drops to citations instead of re-inflating.
    if reason == "stale error":
        score = min(score, 1.8)
    if error_exemplar and reason in ("context", "log error", "critical lines"):
        reason = "error exemplar"
    return {
            **b,
            "score": max(0.0, score),
            "reason": reason,
            "entity_hits": entity_hits,
            "term_hits": term_hits,
            "rare_term_hits": rare_term_hits,
            "trust_risk": trust_risk,
            "error_exemplar": error_exemplar,
    }


_LOG_ERR_RE = re.compile(
    r"\b(?:ERROR|FATAL|WARN|WARNINGS?)\b|Traceback|Exception",
    re.IGNORECASE,
)
_LOG_NOISE_RE = re.compile(r"^\s*(?:INFO|DEBUG)\b", re.MULTILINE)


def score_blocks(
    blocks: list[dict[str, Any]],
    query: str,
    *,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    terms = _extract_terms(query)
    entities = _extract_entities(query)
    # The word-boundary pattern of each short term is compiled once per call:
    # ``re`` keeps only 512, so a long query (thousands of terms) recompiled
    # every pattern for every block (~80k compiles for a 30 KB query).
    term_tests = [(t, _term_test(t)) for t in terms]
    negated = {m.group(1) for m in _NEGATED_TERM_RE.finditer((query or "").lower())}
    if negated:
        term_tests = [
            (t, lambda lower, _test=test: _test(lower) and _FAILURE_EVIDENCE_RE.search(lower) is not None)
            if t in negated
            else (t, test)
            for t, test in term_tests
        ]
    n = max(1, len(blocks))
    entity_df: dict[str, int] = {}
    term_df: dict[str, int] = {}
    fp_counts: dict[str, int] = {}
    # Bridge-entity detection: find entities (proper nouns, identifiers) that
    # appear in multiple blocks. These are the links in a multi-hop chain —
    # dropping the block that holds a bridge entity severs the chain.
    # Only boost entities that look like proper nouns or code identifiers,
    # not common filler words.
    block_token_lists, bridge_by_lower = _bridge_index(blocks, n)
    for b in blocks:
        fp = _dup_fp(b["text"])
        if len(fp) > 20:
            fp_counts[fp] = fp_counts.get(fp, 0) + 1
        for e in entities:
            if _soft_has(b["text"], e):
                entity_df[e] = entity_df.get(e, 0) + 1
        lower = b["text"].lower()
        for t, term_test in term_tests:
            if term_test(lower):
                term_df[t] = term_df.get(t, 0) + 1
    # Pre-compute token document frequency for novelty + fact-density.
    # A token's DF is the number of blocks it appears in. Low DF (1-2)
    # means the token is rare and information-dense.
    tok_df, block_token_sets = _token_df(block_token_lists)

    # Log-type detection (Baseline RAG "Log" policy): if > 60% of blocks
    # look like timestamped log lines, apply log-specific scoring weights.
    # Error/traceback blocks get a bonus; pure INFO/WARN noise gets penalized.
    _LOG_LINE_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}"    # timestamp prefix
        r"|^\[(?:DEBUG|INFO|WARN|ERROR|FATAL)\]"      # bracketed level
        r"|^(?:DEBUG|INFO|WARN|ERROR|FATAL)\s"       # bare level prefix
    )
    log_block_count = sum(
        1 for b in blocks
        if any(_LOG_LINE_RE.match(line) for line in b["text"].splitlines()[:3])
    )
    is_log_context = log_block_count >= 2 and log_block_count / n > 0.4
    # Recency + novelty prior (rate-distortion signal): even without query
    # overlap, recent blocks and blocks holding rare, high-information
    # identifiers deserve a base floor so a "keep track of every detail"
    # style query does not evict scattered facts.
    # Critical-line pre-computation (Baseline RAG-style):
    # Pre-identify lines that carry operational facts — errors, exceptions,
    # config assignments, key-value pairs, dates, versions, large numbers.
    # Blocks containing these lines get a floor boost so they survive
    # compression even without query overlap.
    # v1.4.0 (E1): the regex is module-level and compiled with IGNORECASE; the
    # old call `.search(line, re.IGNORECASE)` passed the flag as `pos=2`, so it
    # matched case-sensitively and skipped the first two characters of a line.
    # A bare LEADING timestamp is a log prefix, not a fact: the search starts
    # after it, so timestamped INFO lines are not all "critical".
    crit_lines_per_block = _critical_line_counts(blocks)

    # v1.4.0 (E3): for content routed as a log, the first block carrying each
    # level-tagged error fingerprint (ERROR/FATAL/CRITICAL/PANIC/FAIL*) is an
    # "error exemplar". It is exempt from the stale-error penalty/cap, and the
    # selectors keep it even when the floor-saturated path reduces to
    # `_important`. Non-log, non-code content uses code-tool diagnostic lines
    # (``DIAGNOSTIC_CODE_LINE_RE``), capped at ``_DIAG_EXEMPLAR_CAP`` blocks.
    error_exemplar_ids = _error_exemplar_ids(blocks, content_type)

    line_ubiquitous_terms = _line_ubiquitous_terms(blocks, query, n, is_log_context, term_tests, term_df, entities)

    # Weak-query adaptive floor (rate-distortion H(Q) theory):
    # When the query has low information content, raise the novelty floor
    # and recency ramp so middle blocks survive. A vague "keep track of
    # every detail" query has H(Q) ≈ 0 — it tells us nothing about what
    # to keep, so we should be more conservative about dropping.
    #
    # A query is "weak" if NONE of its terms are distinctive identifiers
    # (digits, separators, uppercase). "database host port" is weak
    # (all generic words, no identifiers). "REL-2026 user_id 99113" is
    # strong (has identifiers). This matches the rate-distortion theory:
    # H(Q) ≈ 0 when the query carries no specific information.
    #
    # Guard: only apply the weak-query boost when there are enough
    # blocks (≥ 6) to make compression meaningful. With ≤ 5 blocks,
    # the keep_ratio will be ~1.0 and we'd fail-open anyway.
    weak_boost = _weak_boost(blocks, query, terms, n, term_df, line_ubiquitous_terms)

    # IDF floor: a query term in nearly every block carries no signal; it
    # neither scores nor counts as a hit (else every block looks relevant).
    ubiquitous_terms = {
        t for t, df in term_df.items()
        if (n >= 10 and df > 0.8 * n) or t.lower() in line_ubiquitous_terms
    }
    scored = []
    for idx, b in enumerate(blocks):
        scored.append(
            _score_one_block(
                idx,
                b,
                n=n,
                entities=entities,
                entity_df=entity_df,
                term_tests=term_tests,
                term_df=term_df,
                ubiquitous_terms=ubiquitous_terms,
                error_exemplar_ids=error_exemplar_ids,
                is_log_context=is_log_context,
                log_err_re=_LOG_ERR_RE if is_log_context else None,
                log_noise_re=_LOG_NOISE_RE if is_log_context else None,
                crit_lines_per_block=crit_lines_per_block,
                bridge_by_lower=bridge_by_lower,
                block_token_sets=block_token_sets,
                weak_boost=weak_boost,
                tok_df=tok_df,
                fp_counts=fp_counts,
            )
        )
    return scored


def _is_sink_noise(text: str) -> bool:
    """Trailing `-- filler` / `# filler` comments are not a recency sink."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    return all(re.match(r"^(--|#)\s*filler\b", ln, re.IGNORECASE) for ln in lines)


def _query_signal(blocks: list[dict[str, Any]]) -> float:
    hits = sum(1 for b in blocks if b["entity_hits"] or b["term_hits"])
    return hits / max(1, len(blocks))


def _important(blocks: list[dict[str, Any]]) -> set[int]:
    n = max(1, len(blocks))
    rare = []
    for b in blocks:
        if b.get("trust_risk"):
            continue
        if b["entity_hits"] and b["score"] >= 4:
            rare.append(b)
    ids: set[int] = set()
    for b in blocks:
        # v0.7.0: stale-error heads are handled history — not "important".
        # v1.4.0 (E3): a level-tagged log error exemplar is never "stale".
        if b.get("reason") == "stale error" and not b.get("error_exemplar"):
            continue
        # v0.6.0: trust-risk blocks are never "important" — previously the
        # trace/high-score/definition passes ignored the flag, letting an
        # untrusted instruction block into the keep-set (production QA v3
        # injection finding). The rare-candidate loop above already skips.
        if b.get("trust_risk"):
            continue
        if (
            b["type"] == "trace"
            or (b["entity_hits"] and b["score"] >= 5.0)
            or (b["score"] >= 9 and (b["entity_hits"] or b["term_hits"]))
            or (b["type"] == "definition" and b["entity_hits"])
        ):
            ids.add(b["id"])
    cap = max(3, min(18, math.ceil(n * 0.22)))
    if len(ids) > cap:
        ranked = sorted((blocks[i] for i in ids), key=lambda b: (-b["score"], b["tokens"]))
        ids = {b["id"] for b in ranked[:cap]}
    return ids


_TRACE_UNIT_MAX_BLOCKS = 32  # contiguous trace blocks kept as one unit around a kept trace block


def _stitch_neighbors(blocks: list[dict[str, Any]], kept: set[int]) -> set[int]:
    by_id = {b["id"]: b for b in blocks}
    extra: set[int] = set()
    for i in list(kept):
        prev_id = i - 1
        if prev_id in by_id and by_id[prev_id]["type"] == "heading":
            extra.add(prev_id)
        nxt = i + 1
        if nxt in by_id and by_id[i]["type"] == "heading":
            extra.add(nxt)
        # A traceback is one unit: if we keep any part of a stack, keep the
        # whole stack and the log line that triggered it (error/exception).
        if by_id[i]["type"] == "trace" or i in extra and by_id[i]["type"] == "trace":
            # 1.10.0: the unit is the whole (already folded) chain: every contiguous trace block around the
            # kept one (bounded), plus the error log line that opened it.
            for step in (-1, 1):
                nb = i + step
                walked = 0
                while nb in by_id and walked < _TRACE_UNIT_MAX_BLOCKS and (
                    by_id[nb]["type"] == "trace" or _FRAME_TAIL_RE.match(by_id[nb]["text"]) is not None
                    or _FRAMES_FOLDED_RE.match(by_id[nb]["text"]) is not None
                ):
                    extra.add(nb)
                    nb += step
                    walked += 1
                if nb in by_id and by_id[nb]["type"] == "log" and re.search(
                    r"error|fail|exception|traceback", by_id[nb]["text"].lower()
                ):
                    extra.add(nb)
    # Code-block stitching: a signature line ("fn delay(...)") and its
    # indented body lines are separate blocks because each indented line
    # classifies as "definition". Keep them whole:
    #   1. kept body line -> pull in the preceding signature (dedent) line
    #   2. kept signature/definition line -> pull in the following
    #      indented definition body while it stays inside the function
    # Without this, the gold "what does this cap at?" fact (in the body)
    # can be dropped while the signature stays, or vice versa.
    for i in list(kept):
        b = by_id[i]
        if b["type"] in {"code", "definition"}:
            # Pull preceding dedent signature line if we keep a body line.
            p = i - 1
            while p in by_id and not by_id[p]["text"].strip():
                p -= 1
            if p in by_id:
                pt = by_id[p]["text"]
                indent = len(pt) - len(pt.lstrip())
                bt = b["text"]
                bindent = len(bt) - len(bt.lstrip())
                if (
                    b["type"] in {"code", "definition"}
                    and bindent > 0
                    and indent == 0
                    and pt.strip()
                ):
                    extra.add(p)
            # Pull following indented definition body lines.
            q = i + 1
            while q in by_id:
                qb = by_id[q]
                qt = qb["text"]
                if qb["type"] in {"definition", "code"} and qt.strip():
                    qindent = len(qt) - len(qt.lstrip())
                    if qindent > 0:
                        extra.add(q)
                        q += 1
                        continue
                    break
                break
    # Structural closure must never undo trust gating. Explicit caller pins
    # remain the sole opt-in override.
    return {
        bid
        for bid in kept | extra
        if not by_id[bid].get("trust_risk") or by_id[bid].get("pinned")
    }


def _block_link_terms(text: str) -> frozenset[str]:
    """Rare relation keys used only for bounded evidence-path closure.

    Perf (v1.5.0): remembered per block text (a retry of the same output
    scores the same blocks again); callers only read the result.
    """
    if type(text) is str and len(text) <= 2048:
        return _block_link_terms_cached(text)
    return frozenset(_block_link_terms_scan(text))


@content_memo("block_link_terms", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _block_link_terms_cached(text: str) -> frozenset[str]:
    return frozenset(_block_link_terms_scan(text))


def _block_link_terms_scan(text: str) -> set[str]:
    out = {e.casefold() for e in _extract_entities(text) if len(e) >= 3}
    for raw in _TOKEN_RE.findall(text or ""):
        term = raw.casefold().strip("؟?!.،,;:…\"'()[]")
        if len(term) < 4 or term in _STOP or term in GENERIC_WORDS:
            continue
        # v0.6.0: pure-number tokens ("1001", "2026") are timestamps/ids of
        # no linking value — every numeric log line would share one and
        # fabricate a "coherent chain" for the ambiguity guard.
        if term.isdigit():
            continue
        if _HEX_ID_RE.match(term):
            continue
        out.add(term)
    return out


_DERIVE_MIN_TERMS = 3
_DERIVE_MAX_TERMS = 8


def _derive_query_terms(text: str, *, max_terms: int = _DERIVE_MAX_TERMS) -> list[str]:
    """TPC-style derived objective for empty or generic queries.

    Infers a conservative task descriptor from the document itself: rare
    content terms that recur — appearing in too few lines marks a passing
    detail, in too many marks boilerplate — ranked by idf·log(1+tf).
    Fully deterministic (frequency statistics only, no model calls).
    Returns [] when the document has no stable term structure; callers
    keep their normal fail-open path in that case.
    """
    if not text or not text.strip():
        return []
    lines = [ln for ln in text.split("\n") if ln.strip()]
    n = len(lines)
    if n < 8:
        return []
    # Bounded work: this runs before the industrial size gate, so huge
    # inputs are sampled deterministically (uniform stride — no head bias).
    if n > 4096:
        stride = math.ceil(n / 4096)
        lines = lines[::stride]
        n = len(lines)
    df: dict[str, int] = {}
    tf: dict[str, int] = {}
    for ln in lines:
        terms = _block_link_terms(ln)
        for t in terms:
            df[t] = df.get(t, 0) + 1
            tf[t] = tf.get(t, 0) + 1
    if not df:
        return []
    # Thematic band: recurs across lines (topic) but not near-everywhere
    # (boilerplate). Cap scales with document size, floor keeps tiny docs strict.
    hi = max(3, int(n * 0.20))
    cands = [t for t, d in df.items() if 2 <= d <= hi]
    if len(cands) < _DERIVE_MIN_TERMS:
        return []
    # idf·log(1+tf), tie-broken alphabetically — set order must not leak in.
    ranked = sorted(
        cands,
        key=lambda t: (-(math.log(1 + n / df[t]) * math.log(1 + tf[t])), t),
    )
    return ranked[:max_terms]


def _graph_path_closure(
    blocks: list[dict[str, Any]],
    kept: set[int],
    max_hops: int = 4,
    link_terms: dict[int, set[str]] | None = None,
) -> set[int]:
    """Keep short rare-term paths connecting already-selected evidence."""
    if len(kept) < 2 or not blocks:
        return kept
    # Perf (v0.6.0): callers that already tokenised every block (CFA runs
    # right after this in select_adaptive) pass their map to avoid a second
    # full-document regex pass.
    if link_terms is None:
        terms_by_id = {
            b["id"]: (set() if b.get("trust_risk") else _block_link_terms(b["text"]))
            for b in blocks
        }
    else:
        terms_by_id = {
            b["id"]: (set() if b.get("trust_risk") else link_terms.get(b["id"], set()))
            for b in blocks
        }
    term_ids: dict[str, list[int]] = {}
    for bid, terms in terms_by_id.items():
        for term in terms:
            term_ids.setdefault(term, []).append(bid)
    # Bridge terms must be genuinely rare. The old len//5 ceiling let a
    # term appear in up to 800 of 4000 blocks and still form edges — in
    # homogeneous dumps that turns adjacency into a dense hub graph and
    # the BFS floods (v0.6.0 perf regression). Hard-cap at 12.
    max_df = max(3, min(len(blocks) // 5, 12))
    adjacency: dict[int, set[int]] = {b["id"]: set() for b in blocks}
    for ids in term_ids.values():
        if len(ids) < 2 or len(ids) > max_df:
            continue
        for left in ids:
            adjacency[left].update(right for right in ids if right != left)
    scores = {b["id"]: float(b.get("score", 0.0)) for b in blocks}
    seeds = sorted(kept, key=lambda bid: scores.get(bid, 0.0), reverse=True)[:24]
    closed = set(kept)
    # v0.6.0 contract: bridge nodes are evidence when they EXTEND a seed's
    # evidence path (chain rescue: Moonlight→Selene→DB-77-Z hangs off the
    # query-hit block), but the total extension is bounded so hub terms in
    # homogeneous dumps cannot flood the keep-set. Nodes are admitted
    # closest-seed-distance first, up to a budget proportional to the seed
    # count; everything beyond the budget stays dropped.
    reach: dict[int, int] = {}  # node -> nearest seed BFS depth
    for src in seeds:
        queue = [(src, 0)]
        # Standard BFS: mark depth at enqueue time, but EXPAND a node when
        # it is dequeued unless an equal-or-better depth was already
        # expanded. The previous guard also skipped expansion on first
        # discovery, so chains died after one hop (v0.6.0 regression).
        expanded: set[int] = set()
        for node, depth in queue:
            if depth >= max_hops:
                continue
            d = reach.get(node)
            if d is not None and (d < depth or node in expanded):
                continue
            reach[node] = depth
            expanded.add(node)
            for nxt in adjacency.get(node, ()):
                nd = reach.get(nxt)
                if nd is None or nd > depth + 1:
                    reach[nxt] = depth + 1
                    queue.append((nxt, depth + 1))
    budget = max(8, 2 * len(seeds))
    candidates = sorted(
        ((d, n) for n, d in reach.items() if n not in closed),
        key=lambda x: (x[0], -scores.get(x[1], 0.0)),
    )
    # Bridge nodes must carry some intrinsic value — a near-zero-score
    # block that merely shares a token with a seed is noise, not evidence
    # (v0.6.0: '- ccache' style lines were flooding the keep-set).
    min_bridge_score = min(3.0, max(scores.get(s, 0.0) for s in seeds) * 0.25 if seeds else 3.0)
    for _, node in candidates[:budget]:
        if scores.get(node, 0.0) >= min_bridge_score:
            closed.add(node)
    return closed


# Qualifier/negation cues: a dropped block carrying one of these while
# sharing a rare entity with a kept block is a QUALIFIES edge — cutting it
# can invert the surviving claim ("safe for adults" vs "safe for adults,
# except when..."). Same vocabulary class as lcc's TRIM refusal.
_QUALIFIER_CUE_RE = re.compile(
    r"\b(except|exception|excluding|excluded|unless|only|not\b|no\b|never|"
    r"but\b|however|although|though|nevertheless|otherwise|without|despite|"
    r"until|provided\s+that|subject\s+to|if)\b",
    re.IGNORECASE,
)

# Definition cues: the dropped block DEFINES a term the kept block uses.
_DEFINITION_CUE_RE = re.compile(
    r"\b(is\s+defined\s+as|refers?\s+to|stands\s+for|means|i\.e\.|namely|denotes)\b",
    re.IGNORECASE,
)


def _dependency_closure(
    blocks: list[dict[str, Any]],
    kept: set[int],
    *,
    link_terms: dict[int, set[str]] | None = None,
    budget_tokens: int | None = None,
) -> tuple[set[int], list[int]]:
    """Sufficiency restore over typed edges (lcc graph.closure lesson).

    A dropped block that QUALIFIES or DEFINES a rare term carried by a
    kept block changes the meaning of what survives — restore it. Rare
    means document-frequency <= cap, so only genuinely linking terms form
    edges; restoration is document-ordered and capped at 8 blocks so a
    cue-dense corpus cannot flood the keep-set. Never resurrects
    trust-risk or frozen-drop blocks; supersession still runs after this
    and can evict stale restorations. ``budget_tokens`` (fixed mode)
    refuses a restoration that would overflow the caller's hard budget.
    """
    if not kept or len(blocks) < 2:
        return kept, []
    if link_terms is None:
        link_terms = {
            b["id"]: (set() if b.get("trust_risk") else _block_link_terms(b["text"]))
            for b in blocks
        }
    df: dict[str, int] = {}
    for terms in link_terms.values():
        for term in terms:
            df[term] = df.get(term, 0) + 1
    rare_cap = min(6, max(3, len(blocks) // 8))
    kept_rare = {
        term
        for bid in kept
        for term in link_terms.get(bid, ())
        if df.get(term, 0) <= rare_cap
    }
    if not kept_rare:
        return kept, []
    used = sum(b["tokens"] for b in blocks if b["id"] in kept) if budget_tokens is not None else 0
    restored: list[int] = []
    for b in blocks:  # document order -> deterministic
        if len(restored) >= 8:
            break
        bid = b["id"]
        if bid in kept or b.get("trust_risk") or b.get("freeze_decision") == "drop":
            continue
        if not (link_terms.get(bid, set()) & kept_rare):
            continue
        text = b["text"]
        if not (_QUALIFIER_CUE_RE.search(text) or _DEFINITION_CUE_RE.search(text)):
            continue
        if budget_tokens is not None and used + b["tokens"] > budget_tokens:
            continue
        restored.append(bid)
        used += b["tokens"]
    if not restored:
        return kept, []
    return kept | set(restored), restored


def _counterfactual_overlap_ambiguity(
    blocks: list[dict[str, Any]],
    kept: set[int],
    *,
    query: str,
    link_terms: dict[int, set[str]] | None = None,
    semantic_tier: Any = None,
) -> bool:
    """Detect a high-scoring kept distractor masking a dropped answer chain.

    Fires ONLY when:
      1. A kept block scores high on query-term overlap (the "winner").
      2. Two or more dropped blocks share a *rare, non-generic* link term
         (appearing in ≤3 blocks document-wide, length ≥4, not in
         GENERIC_WORDS) AND at least one of them mentions a query content
         word as a whole word — i.e. a coherent, query-relevant chain
         was evicted.

    This intentionally does NOT fire for generic high-volume logs (git, npm)
    where shared tokens like dates, SHAs, "verbose", "docs", "commit" are
    ubiquitous and would cause false positives.
    """
    kept_with_terms = [
        b
        for b in blocks
        if b["id"] in kept
        and not b.get("trust_risk", False)
        and (b.get("term_hits") or b.get("entity_hits"))
    ]
    if not kept_with_terms:
        return False

    winner = max(
        kept_with_terms,
        key=lambda b: (
            b.get("rare_term_hits", 0)
            + b.get("entity_hits", 0)
            + b.get("term_hits", 0),
            b["score"],
        ),
    )

    content = _query_content_terms(query)
    if not content:
        return False

    # If the kept set is already large enough that the answer is likely
    # present, a single distractor cannot meaningfully mask it.  The guard
    # only fires when the kept set is small (<10% of the document) AND the
    # winner is a single high-scoring block (not a coherent multi-block
    # chain).  This targets the narrow production QA P0: one distractor block
    # outscoring a linked answer chain that was evicted.
    if len(kept) / max(1, len(blocks)) >= 0.10:
        return False

    # Precompile word-boundary patterns for each query content term.
    content_patterns = [_compiled_term_pattern(r"\b" + re.escape(t) + r"\b") for t in content]

    # The dropped chain must be scoring well (near the floor) to count as
    # a "genuinely evicted answer".  Low-scoring dropped blocks are just
    # noise, not a hidden answer.  Use 0.38× the top safe score as the
    # threshold (same floor as the main selection path).
    safe_blocks = [b for b in blocks if not b.get("trust_risk")]
    top_score = max((b["score"] for b in safe_blocks), default=0.0)
    floor = max(2.2, min(11.5, 0.38 * top_score))

    dropped = [
        b
        for b in blocks
        if b["id"] != winner["id"]
        and b["id"] not in kept
        and not b.get("trust_risk", False)
        and b["score"] >= floor
    ]
    if len(dropped) < 2:
        return False

    # Perf bound (v0.6.0): the pair scan below is O(d²) with per-pair set
    # intersections and regex searches. Cap the candidate pool to the top-
    # scoring dropped blocks — a masked answer chain lives at the top of
    # the evicted mass, never in the tail.
    if len(dropped) > 64:
        dropped = sorted(dropped, key=lambda b: -b["score"])[:64]

    if link_terms is not None:
        def _terms_of(b: dict[str, Any]) -> set[str]:
            return set() if b.get("trust_risk") else link_terms.get(b["id"], set())
    else:
        def _terms_of(b: dict[str, Any]) -> set[str]:
            return set() if b.get("trust_risk") else _block_link_terms(b["text"])

    max_df = 3

    # Document-wide df for the candidates' link terms, computed with a
    # cheap substring scan over pre-lowered texts instead of tokenising
    # every block (v0.6.0 perf: 4000 regex passes → ~len(cand_terms)
    # str-in checks). Substring df can overcount when a term is a
    # fragment of a longer word; that only makes the rarity gate MORE
    # conservative (term judged common → not a chain link), which is safe.
    cand_term_set: set[str] = set()
    for b in dropped:
        cand_term_set |= _terms_of(b)
    lower_texts = [b["text"].casefold() for b in blocks]
    term_df: dict[str, set[int]] = {t: set() for t in cand_term_set}
    for idx, lt in enumerate(lower_texts):
        for t in cand_term_set:
            if t in lt:
                term_df[t].add(idx)

    def _meaningful_shared(term: str) -> bool:
        """A shared link term must be rare, long enough, and not generic."""
        if len(term) < 4:
            return False
        if term in GENERIC_WORDS:
            return False
        return len(term_df.get(term, ())) <= max_df

    rare_terms_by_block: dict[int, set[str]] = {}
    for b in dropped:
        terms = _terms_of(b)
        rare = {t for t in terms if _meaningful_shared(t)}
        rare_terms_by_block[b["id"]] = rare

    # Inverted index over the candidates' rare terms: propose pairs by
    # shared term instead of scanning all pairs.
    postings: dict[str, list[int]] = {}
    for b in dropped:
        for t in rare_terms_by_block[b["id"]]:
            postings.setdefault(t, []).append(b["id"])
    candidate_pairs: list[tuple[int, int]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for ids in postings.values():
        if len(ids) < 2 or len(ids) > max_df:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    candidate_pairs.append(key)
    by_id = {b["id"]: b for b in dropped}
    for left_id, right_id in candidate_pairs:
        left = by_id[left_id]
        right = by_id[right_id]
        left_has_content = any(p.search(left["text"].lower()) for p in content_patterns)
        if left_has_content:
            return True
        if any(p.search(right["text"].lower()) for p in content_patterns):
            return True

    # Semantic upgrade (v0.8.0): the lexical scan found no shared-term
    # chain. With a tier attached, ambiguity now means: >=2 dropped
    # candidates score within eps of the winner in embedding space —
    # i.e. paraphrase distractors that share NO vocabulary with the query.
    if semantic_tier is not None:
        try:
            tier = semantic_tier
            if not getattr(tier, "available", False):
                return False
            cands = [
                b for b in blocks
                if b["id"] != winner["id"] and b["id"] not in kept
                and not b.get("trust_risk", False)
            ]
            if len(cands) < 2:
                return False
            capped = sorted(cands, key=lambda b: -b["score"])[:32]
            _, sims = tier.score_against_query(query, [c["text"] for c in capped])
            win_sim = tier.score_against_query(query, [winner["text"]])[1][0]
            near = [c for c, sm in zip(capped, sims) if abs(sm - win_sim) < 0.05]
            return len(near) >= 2
        except Exception:  # tier failure must NEVER break compression
            return False
    return False


def _is_collapse_only_block(block) -> bool:
    lines = [ln for ln in block.get("text", "").splitlines() if ln.strip()]
    if not lines:
        return False
    return all(ln.lstrip().startswith(("[\u00d7", "[last] ")) for ln in lines)


def select_adaptive(
    blocks: list[dict[str, Any]],
    *,
    needle_only: bool = False,
    query: str = "",
    semantic_tier: Any = None,
    out: dict[str, Any] | None = None,
) -> tuple[set[int], bool, str]:
    def _ret(kept, fail, risk, name):
        if out is not None:
            out["path"] = name
        return kept, fail, risk

    if not blocks:
        return _ret(set(), True, "high", "empty")
    signal = _query_signal(blocks)
    if signal < 0.04 and max(b["score"] for b in blocks) < 3.5:
        return _ret({b["id"] for b in blocks}, True, "high", "weak-signal")
    hits = {b["id"] for b in blocks if b["entity_hits"] or b["term_hits"]}
    rare = {
        b["id"]
        for b in blocks
        if b.get("rare_term_hits") or b["entity_hits"]
    }
    # v1.4.0 (E3): one exemplar block per level-tagged log error fingerprint
    # survives every selector path (stale-error cap, floor saturation, needle).
    err_keep = {
        b["id"]
        for b in blocks
        if b.get("error_exemplar") and not b.get("trust_risk")
    }
    # Discrimination guard: when the hit set is most of the document the
    # needle found no needle — a selector matching nearly every block gave
    # no signal a tight set can be built on. Keep going and the keep-set
    # saturates into a fail-open; fall through to scored selection, which
    # picks within the same blocks under the savings bound.
    needle_use = {bid for bid in (rare if rare else hits) if not blocks[bid].get("trust_risk")}
    if needle_only and hits and not needle_use:
        return _ret({b["id"] for b in blocks}, True, "high", "needle-all-trust")
    if needle_only and needle_use and len(needle_use) / len(blocks) <= 0.6:
        use = needle_use
        kept = set(use) | err_keep
        if not blocks[0].get("trust_risk") or blocks[0].get("pinned"):
            skip_lead = (
                _is_collapse_only_block(blocks[0])
                and not blocks[0].get("entity_hits")
                and not blocks[0].get("term_hits")
                and not blocks[0].get("pinned")
            )
            if not skip_lead:
                kept.add(blocks[0]["id"])
        if (
            not _is_sink_noise(blocks[-1]["text"])
            and not blocks[-1].get("trust_risk")
            and blocks[-1]["id"] in use
        ):
            kept.add(blocks[-1]["id"])
        # Perf (v0.6.0): tokenise once, share with the CFA guard below.
        link_terms_map = {
            b["id"]: (set() if b.get("trust_risk") else _block_link_terms(b["text"]))
            for b in blocks
        }
        kept = _graph_path_closure(blocks, kept, link_terms=link_terms_map)
        # Needle-path saturation guard: on bilingual/mirrored documents the
        # closure floods (EN/JP block pairs share bridge terms) and the
        # "needle" keep-set approaches the whole document. Cap it back to
        # the query-hit core — the needle path's contract is a tight set.
        if len(kept) > max(len(use) * 2, 16) and len(kept) / len(blocks) > 0.6:
            kept = set(use) | err_keep
            if not blocks[0].get("trust_risk") or blocks[0].get("pinned"):
                skip_lead = (
                    _is_collapse_only_block(blocks[0])
                    and not blocks[0].get("entity_hits")
                    and not blocks[0].get("term_hits")
                    and not blocks[0].get("pinned")
                )
                if not skip_lead:
                    kept.add(blocks[0]["id"])
        kept = _stitch_neighbors(blocks, kept)
        if _counterfactual_overlap_ambiguity(
            blocks, kept, query=query, link_terms=link_terms_map, semantic_tier=semantic_tier
        ):
            return _ret({b["id"] for b in blocks}, True, "high", "needle-ambiguous")
        kept, restored = _dependency_closure(blocks, kept, link_terms=link_terms_map)
        if restored and out is not None:
            out["sufficiency_restored"] = restored
        return _ret(kept, False, "low", "needle")
    important = _important(blocks)
    safe_blocks = [b for b in blocks if not b.get("trust_risk")]
    top = max((b["score"] for b in safe_blocks), default=0.0)
    # Floor: 0.38× the top score, but capped so one dominant block
    # (e.g. a head block with many query terms) doesn't evict all the
    # middle. The cap is 11.5 — high enough to keep the top blocks,
    # low enough that scattered facts with scores 8-12 survive.
    # Rate-distortion insight: lossy schemes compound under repeated
    # compaction; a single high scorer shouldn't create a cascade.
    floor = max(2.2, min(11.5, 0.38 * top))
    any_hit = any(b["entity_hits"] or b["term_hits"] for b in safe_blocks)

    def _bare_fold(b) -> bool:
        # A folded repeat line with no query hit is boilerplate, not the answer,
        # once another block answers the query.
        return (
            any_hit
            and _is_collapse_only_block(b)
            and not b.get("entity_hits")
            and not b.get("term_hits")
            and not b.get("pinned")
        )

    kept = set(important) | err_keep
    for b in safe_blocks:
        if b["score"] >= floor and not _bare_fold(b):
            kept.add(b["id"])
    # Saturation guard (v0.6.0, production QA v3 performance finding): on huge
    # homogeneous dumps every line matches a broad query, so the floor
    # keeps everything and the payload never shrinks. When the floor pass
    # keeps nearly all blocks AND the query is broad (no distinctive
    # selector), fall back to the important-set only — the ranked top of
    # the document — instead of the whole dump.
    floor_ratio = sum(b["tokens"] for b in safe_blocks if b["id"] in kept) / max(
        1, sum(b["tokens"] for b in safe_blocks)
    )
    path = "floor"
    if floor_ratio > 0.9 and len(safe_blocks) > 64 and not needle_only:
        kept = set(important) | err_keep
        path = "floor-saturated"
    # Keep the head. A trust-risk tail is not a safe recency sink.
    # Exception (leanctx old-error purge): a stale-error head is handled
    # history — citations preserve its fact; don't re-admit the dump.
    if (
        (blocks[0].get("reason") != "stale error" or len(kept) == 0)
        and (not blocks[0].get("trust_risk") or blocks[0].get("pinned"))
        and not (kept and _bare_fold(blocks[0]))
    ):
        kept.add(blocks[0]["id"])
    if (
        not _is_sink_noise(blocks[-1]["text"])
        and not blocks[-1].get("trust_risk")
        and not (kept and _bare_fold(blocks[-1]))
    ):
        kept.add(blocks[-1]["id"])
    # Perf (v0.6.0): the graph closure tokenises every block (regex-heavy).
    # When the keep-set has at most one member there is nothing to bridge,
    # and on huge weak-signal documents that is the common case — skip it.
    # Otherwise tokenise ONCE and share the map between the closure and the
    # CFA guard below (saves a second full-document regex pass).
    link_terms_map: dict[int, set[str]] | None = None
    if len(kept) >= 2:
        link_terms_map = {
            b["id"]: (set() if b.get("trust_risk") else _block_link_terms(b["text"]))
            for b in blocks
        }
        kept = _graph_path_closure(blocks, kept, link_terms=link_terms_map)
    kept = _stitch_neighbors(blocks, kept)
    keep_ratio = sum(blocks[i]["tokens"] for i in kept) / max(1, sum(b["tokens"] for b in blocks))
    # Line dumps (git / npm): Super keeps matching records only. Priors
    # (unique SHAs, dates on every line) must not keep the whole log.
    # This check must come before the keep_ratio guard because line records
    # have a well-defined compression strategy that the generic "keep too
    # much -> fail open" escape would preempt.
    texts = [b["text"] for b in blocks]
    if _looks_like_line_records(texts):
        path = "line-records"
        kept = {
            b["id"]
            for b in blocks
            if (b["entity_hits"] or b["term_hits"]) and not b.get("trust_risk")
        }
        if not kept:
            return _ret({b["id"] for b in blocks}, True, "high", "line-records-empty")
        kept |= err_keep
        if not blocks[0].get("trust_risk") or blocks[0].get("pinned"):
            kept.add(blocks[0]["id"])
        if (
            not _is_sink_noise(blocks[-1]["text"])
            and not blocks[-1].get("trust_risk")
        ):
            kept.add(blocks[-1]["id"])
        kept = _stitch_neighbors(blocks, kept)
        keep_ratio = sum(blocks[i]["tokens"] for i in kept) / max(1, sum(b["tokens"] for b in blocks))
    if keep_ratio > 0.92 and signal < 0.12 and len(blocks) >= 8:
        # The floor/closure saturated: nearly everything scored keepable —
        # often selector-driven hits flooding a uniform table dump. When the
        # ranked core is still a tight set, it IS the compression the savings
        # bound wants; only when even the core is broad does the honest answer
        # stay fail-open. Small documents keep the old verdict — declining a
        # few-block input costs little and the full text stays truthful.
        core = set(important) | err_keep
        if (
            (blocks[0].get("reason") != "stale error" or len(core) == 0)
            and (not blocks[0].get("trust_risk") or blocks[0].get("pinned"))
        ):
            core.add(blocks[0]["id"])
        if (
            not _is_sink_noise(blocks[-1]["text"])
            and not blocks[-1].get("trust_risk")
        ):
            core.add(blocks[-1]["id"])
        core = _stitch_neighbors(blocks, core)
        core_ratio = sum(blocks[i]["tokens"] for i in core) / max(1, sum(b["tokens"] for b in blocks))
        if core and core_ratio <= 0.92:
            kept, keep_ratio, path = core, core_ratio, "saturated-core"
        else:
            return _ret({b["id"] for b in blocks}, True, "high", "saturated-failopen")
    elif keep_ratio > 0.92 and signal < 0.12:
        return _ret({b["id"] for b in blocks}, True, "high", "saturated-failopen")
    if _counterfactual_overlap_ambiguity(
        blocks, kept, query=query, link_terms=link_terms_map, semantic_tier=semantic_tier
    ):
        return _ret({b["id"] for b in blocks}, True, "high", "ambiguous-failopen")
    kept, restored = _dependency_closure(blocks, kept, link_terms=link_terms_map)
    if restored and out is not None:
        out["sufficiency_restored"] = restored
    risk = "low"
    if keep_ratio > 0.8:
        risk = "medium"
    if not important and signal < 0.1:
        # No query signal and nothing important: a guess. Retained log error
        # exemplars (E3) make it a defensible one, not a certain one.
        risk = "medium" if err_keep else "high"
    return _ret(kept, False, risk, path)


# v1.6.0 (multilang): no-query prose brief (opt-in ``prose_brief``).
_PROSE_DATA_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|％|万|萬|億|亿|元|円|원|€|\$|£|¥|[kKmM]\b|GB|MB|ms\b)"
    r"|[$€£¥]\s*\d"
    r"|\b(?!ke-)[A-Za-z]{1,8}[-_]\d{2,}\b"  # not Indonesian/Malay ordinals (minggu ke-12)
    r"|\d{4,}"
    r"|\d+\.\d+"
    r"|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"
)
_PROSE_MIN_BLOCKS = 8


def _prose_key(text: str) -> str:
    """Repeat key: NFKC-normalised, digit runs -> '#', lowercased, whitespace collapsed, first 2000 chars."""
    return " ".join(_DIGITS_RE.sub("#", unicodedata.normalize("NFKC", text[:2000]).lower()).split())


def select_prose_brief(
    blocks: list[dict[str, Any]], *, out: dict[str, Any] | None = None
) -> tuple[set[int], bool, str]:
    """Keep-set for the no-query prose brief (see ``prose_brief`` in :func:`compress_context`)."""
    def _ret(kept: set[int], fail: bool, risk: str, name: str) -> tuple[set[int], bool, str]:
        if out is not None:
            out["path"] = name
        return kept, fail, risk

    all_ids = {b["id"] for b in blocks}
    if len(blocks) < _PROSE_MIN_BLOCKS:
        return _ret(all_ids, True, "high", "prose-brief-small")
    kept: set[int] = set()
    seen: set[str] = set()
    last_block = blocks[-1]
    if not last_block.get("trust_risk") or last_block.get("pinned"):
        seen.add(_prose_key(last_block["text"]))
    for pos, b in enumerate(blocks):
        if b.get("trust_risk") and not b.get("pinned"):
            continue
        if pos in (0, len(blocks) - 1) or b.get("pinned") or b.get("error_exemplar"):
            kept.add(b["id"])
            seen.add(_prose_key(b["text"]))
            continue
        key = _prose_key(b["text"])
        if key not in seen:
            seen.add(key)
            kept.add(b["id"])
        elif _PROSE_DATA_RE.search(b["text"]):
            kept.add(b["id"])
    total = sum(b["tokens"] for b in blocks) or 1
    if sum(b["tokens"] for b in blocks if b["id"] in kept) / total > 0.9:
        return _ret(all_ids, True, "high", "prose-brief-saturated")
    return _ret(kept, False, "medium", "prose-brief")


def select_fixed(
    blocks: list[dict[str, Any]],
    budget_ratio: float,
    out: dict[str, Any] | None = None,
    *,
    reserve_tokens: int = 0,
) -> tuple[set[int], bool, str]:
    if out is not None:
        out["path"] = "fixed"
    if not blocks:
        return set(), True, "high"
    total = sum(b["tokens"] for b in blocks)
    pinned_ids = {b["id"] for b in blocks if b.get("pinned")}
    if pinned_ids:
        # ARGP-style: the ratio governs compressible tokens only. Pins are
        # immovable — they must not consume the budget they outrank.
        pinned_tokens = sum(b["tokens"] for b in blocks if b["id"] in pinned_ids)
        budget = pinned_tokens + max(
            1, round(max(0, total - pinned_tokens) * budget_ratio)
        )
    else:
        budget = max(1, round(total * budget_ratio))
    if reserve_tokens > 0:
        # v1.4.0 (E8): tokens the caller's gap markers will occupy are not
        # available to content.
        budget = max(1, budget - int(reserve_tokens))
    important = _important(blocks)
    ranked = sorted(
        (b for b in blocks if not b.get("trust_risk")),
        key=lambda b: (-b["score"], b["start"]),
    )
    # v1.4.0 (E3): log error exemplars are forced into the keep-set.
    err_keep = {
        b["id"]
        for b in blocks
        if b.get("error_exemplar") and not b.get("trust_risk")
    }
    kept: set[int] = set(important) | pinned_ids | err_keep
    used = sum(b["tokens"] for b in blocks if b["id"] in kept)
    for b in ranked:
        if b["id"] in kept:
            continue
        if used >= budget and used >= max(1, budget // 2):
            # still take a high-score leftover if we have almost no query hits
            if b["score"] < 6:
                continue
        if used + b["tokens"] > budget * 1.15 and used >= budget * 0.6 and b["id"] not in important:
            continue
        kept.add(b["id"])
        used += b["tokens"]
        if used >= budget and len(kept) >= max(2, len(important)):
            break
    if not blocks[0].get("trust_risk") or blocks[0].get("pinned"):
        kept.add(blocks[0]["id"])
    if (
        not _is_sink_noise(blocks[-1]["text"])
        and (not blocks[-1].get("trust_risk") or blocks[-1].get("pinned"))
    ):
        kept.add(blocks[-1]["id"])
    kept = _stitch_neighbors(blocks, kept)
    kept, restored = _dependency_closure(blocks, kept, budget_tokens=budget)
    if restored and out is not None:
        out["sufficiency_restored"] = restored
    return kept, False, "low"


def _query_content_terms(query: str) -> set[str]:
    """Content words in the query, after generic stop-words are removed."""
    return set(_extract_terms(query))


def _match_fold(text: str) -> str:
    """The lower-cased NFKC view keys are looked up in (ASCII: plain ``lower``)."""
    return text.lower() if text.isascii() else unicodedata.normalize("NFKC", text).lower()


@content_memo("evidence_blob", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _evidence_blob(text: str) -> str:
    """``_match_fold(text)`` without its trust-risk lines. Injection-shaped text is never evidence: a key that only
    an ``ignore previous instructions`` line holds is not present, and such a line never counts as kept."""
    folded = _match_fold(text)
    if _TRUST_RISK_RE.search(_normalise_instruction_text(folded)) is None:
        return folded
    return "\n".join(ln for ln in folded.split("\n") if not _is_trust_risk_line(ln))


def _source_keys(query: str, blob: str) -> list[str]:
    """The entities and terms of ``query`` that occur in ``blob`` (a folded source). Only these can count for or
    against recall: a query word the text never contains says nothing about what was kept."""
    keys: list[str] = []
    seen: set[str] = set()
    for item in _extract_entities(query) + _extract_terms(query):
        if item not in seen and item.lower() in blob:
            keys.append(item)
            seen.add(item)
    return keys


_QUERY_TERM_CAP = 24
_IDENTIFIER_RE = re.compile(r"[_./:-]|"+chr(92)+chr(92))


def _prune_query(query: str, source: str) -> str:
    """A query with more than ``_QUERY_TERM_CAP`` terms (a tool call plus a long user message) is cut to the
    terms the text contains: identifiers (a term with a digit or a ``_ . / \\ : -`` in it) always stay, the rest are
    ranked by how rarely they occur in the text (fewest occurrences first, then the longer term, then the term
    itself, so the order is fixed) and fill up to the cap. Only the query's own terms are ranked, never anything
    the text offers, and text that only a trust-risk line holds is not present. Terms the text lacks are dropped:
    they cannot match, and they used to hold confidence down. A query with no term in the text is returned
    unchanged (that is the "absent objective" case). No tokenizing pass over the text: one ``str.count`` per term."""
    terms = _extract_terms(query)
    if len(terms) <= _QUERY_TERM_CAP:
        return query
    blob = _evidence_blob(source)
    counted = [(blob.count(t), t) for t in terms]
    present = [(c, t) for c, t in counted if c > 0]
    if not present:
        return query
    ents = [e for e in _extract_entities(query) if e.lower() in blob]
    identifiers = [t for c, t in present if _IDENTIFIER_RE.search(t)]
    others = sorted((c, -len(t), t) for c, t in present if not _IDENTIFIER_RE.search(t))
    room = max(0, _QUERY_TERM_CAP - len(identifiers))
    kept = identifiers + [t for _c, _n, t in others[:room]]
    return " ".join(dict.fromkeys([*ents, *kept]))


_LOCATOR_RE = re.compile(r"[\w./\\-]+\.[A-Za-z]{1,5}:\d+|[A-Za-z_][\w.$]*(?:Error|Exception)\b|\b[A-Za-z_][\w.]{3,}\b")


_LEVEL_WORDS = frozenset({"info", "debug", "warn", "warning", "error", "fatal", "trace", "notice", "critical"})


def _dropped_summary(original: str, output: str, redact: bool = False) -> tuple:
    """Up to three ``(category, line_count, first_locator)`` of the lines the output leaves out, largest first.

    A line of the original is left out when the output holds no more copies of it than it has (a ``[×N]`` prefix
    is read as the one copy it stands for). The category is ``classify_line``'s; the locator is the first
    ``file:line`` or identifier of the first such line, else ``line N``. Pure function of the two texts: the same
    input gives the same summary. With ``redact`` a first line that holds a credential is named by its number (``line N``), and any locator is
    redacted again, so a credential never reaches ``dropped``."""
    if not original or original == output:
        return ()
    have = collections.Counter(ln.strip() for ln in _norm_newlines(output).split("\n"))
    for line in list(have):
        bare = _COUNT_PREFIX_RE.sub("", line, count=1)
        if bare != line:
            have[bare] += 1
    counts: dict[str, int] = {}
    first: dict[str, tuple[int, str]] = {}
    for number, raw in enumerate(_norm_newlines(original).split("\n"), 1):
        line = raw.strip()
        if not line:
            continue
        if have[line] > 0:
            have[line] -= 1
            continue
        category = classify_line(line)
        counts[category] = counts.get(category, 0) + 1
        if category not in first:
            first[category] = (number, line)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    out = []
    for category, count in ranked:
        number, line = first[category]
        if redact:
            clean = redact_secrets_in(line)
            line = "" if clean != line else line   # a line that held a credential names its number, not a cut of itself
        found = next(
            (m.group(0) for m in _LOCATOR_RE.finditer(line[:_RX_LINE_CAP]) if m.group(0).lower() not in _LEVEL_WORDS),
            None,
        )
        locator = found[:80] if found else f"line {number}"
        out.append((category, count, redact_secrets_in(locator) if redact else locator))
    return tuple(out)


def _entity_recall(original: str, compressed: str, query: str) -> float:
    """Recall of the query keys the ORIGINAL contains (1.0 when it contains none: this is the selection's own
    signal; the confidence reported to a host never takes 1.0 from zero keys, see ``_compute_confidence``)."""
    orig_l = _match_fold(original)
    keys = []
    for item in _extract_entities(query) + _extract_terms(query):
        if item.lower() in orig_l and item not in keys:
            keys.append(item)
    if not keys:
        return 1.0
    comp_l = _match_fold(compressed)
    hit = sum(1 for k in keys if k.lower() in comp_l)
    return hit / len(keys)


_CRITICAL_ERROR_RE = re.compile(
    r"\b(?:error|exception|traceback|fail|fatal|timeout|denied|invalid)\b", re.IGNORECASE
)
# v1.4.0 (E2): the key is bounded ({1,64}) — `[\w]+[=:]` rescanned a 20k-char
# word run from every start position (quadratic). A longer key still matches
# through its last 64 characters, so the boolean result is unchanged.
_CRITICAL_KV_RE = re.compile(r"\w{1,64}[=:]\s*\w[\w.-]*")
_CRITICAL_NUM_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d+\.\d+\.\d+\b|\b\d{6,}\b"
    r"|\b\d+\s*(?:ms|s|sec|bytes|kb|mb|gb)\b"
)


def _extract_critical_lines(text: str) -> list[str]:
    if type(text) is str and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS:
        return list(_extract_critical_lines_cached(text))
    return _extract_critical_lines_scan(text)


@content_memo("critical_lines", max_chars=_MEMO_MAX_CHARS, version=lambda: ENGINE_VERSION)
def _extract_critical_lines_cached(text: str) -> tuple[str, ...]:
    return tuple(_extract_critical_lines_scan(text))


def _extract_critical_lines_scan(text: str) -> list[str]:
    """Extract lines that look like critical facts: error lines, key-value
    pairs with identifiers, tracebacks, and lines containing numbers + words.
    Mirrors Baseline RAG's critical_lines_total/kept/dropped reporting.

    v1.4.0: a bare leading timestamp is a prefix, not a fact — previously
    `12:03:45` satisfied the key-value rule and the date satisfied the number
    rule, so EVERY timestamped log line was "critical" and the verifier could
    not see error loss in the crowd. Error lines still are. (A chat role label
    keeps counting here, as it always did; only scoring skips it.)
    """
    critical: list[str] = []
    for line in text.split("\n"):
        t = line.strip()
        if not t:
            continue
        scan = t[:_RX_LINE_CAP]
        # Error/exception/traceback lines
        if _CRITICAL_ERROR_RE.search(scan):
            critical.append(t)
            continue
        start = _lead_ts_end(scan)
        # Lines with key-value patterns (config, settings, identifiers), or
        # lines containing specific numbers (dates, IDs, versions, counts)
        # (the key-value pattern needs a "=" or ":" after the prefix; most log
        # lines have neither, and the pattern is the slow part of this scan)
        if (
            len(t) > 15
            and (scan.find("=", start) >= 0 or scan.find(":", start) >= 0)
            and _CRITICAL_KV_RE.search(scan, start)
        ) or _CRITICAL_NUM_RE.search(scan, start):
            critical.append(t)
    return critical


def _critical_kept(critical: list[str], compressed: str) -> int:
    """How many of the ``critical`` lines (stripped, original case) the compressed text still holds."""
    kept = 0
    # Perf (v1.4.0, E2): lowercase the compressed text ONCE. Lowering it inside
    # the per-line loop was O(lines x output) — 30 s of a 35 s run on a 650 KB
    # log (and ~10x worse again when the output holds a non-ASCII "[…]").
    compressed_lower = compressed.lower()
    # Collapse prefixes do not change a line's facts.
    out_lines: set[str] = set()
    for out_line in compressed_lower.split("\n"):
        out_line = out_line.strip()
        out_lines.add(out_line)
        bare = _COUNT_PREFIX_RE.sub("", out_line, count=1)
        if bare is not out_line:
            out_lines.add(bare)
    for line in critical:
        core = line.strip().lower()
        if core in out_lines:
            kept += 1
    return kept


def _critical_line_recall(original: str, compressed: str) -> tuple[int, int]:
    """Return (kept, total) counts of critical lines, matching Baseline RAG
    verifier's critical_lines_kept/critical_lines_total fields."""
    critical = _extract_critical_lines(original)
    if not critical:
        return 0, 0
    return _critical_kept(critical, compressed), len(critical)


_KEY_LINE_MAX = 12  # a key found on more lines than this names a topic, not a line that must survive


def _verification_critical_lines(original: str, keys: list[str]) -> list[str]:
    """The lines whose loss the verifier counts (1.10.0): error lines, and the lines that hold a query key the
    source contains and that are rare (at most ``_KEY_LINE_MAX`` lines). A line with only a number or a
    ``key: value`` in it is not critical. Trust-risk lines never count; identical stripped lines count once."""
    lines = original.split("\n")
    flines = [ln.lower() for ln in lines] if original.isascii() else [_match_fold(ln) for ln in lines]
    key_hits: set[int] = set()
    wanted = [k.lower() for k in keys if len(k) >= 2]
    if wanted:
        # one pass per key over the folded text (C speed), then each hit position -> its line
        blob = "\n".join(flines)
        starts: list[int] = []
        pos = 0
        for fl in flines:
            starts.append(pos)
            pos += len(fl) + 1
        for key in wanted:
            found: set[int] = set()
            at = blob.find(key)
            while at >= 0 and len(found) <= _KEY_LINE_MAX:
                found.add(bisect.bisect_right(starts, at) - 1)
                at = blob.find(key, at + 1)
            if len(found) <= _KEY_LINE_MAX:
                key_hits |= found
    critical: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(lines):
        t = raw.strip()
        if not t:
            continue
        scan = t[:_RX_LINE_CAP]
        if i not in key_hits and _CRITICAL_ERROR_RE.search(scan) is None:
            continue
        if _is_trust_risk_line(scan):
            continue
        shape = flines[i].strip()
        if shape in seen:
            continue
        seen.add(shape)
        critical.append(t)
    return critical


def verify_compression(
    original: str,
    compressed: str,
    query: str,
) -> dict[str, Any]:
    """Post-compression self-check, mirroring Baseline RAG's verifier object.

    Returns a dict with:
      entity_recall     — fraction of the query's entities/terms THE ORIGINAL CONTAINS that are in compressed
      keyword_recall    — the same over the query's terms alone (same source-present denominator)
      important_kept_pct — fraction of critical lines retained
      critical_lines_total / kept / dropped
      keys_total        — how many query keys the original contains (0: recall says nothing)
      risk              — "low" / "medium" / "high" based on recall thresholds
      score             — overall 0-1 quality score (weighted blend)

    1.10.0: a query word the text never contains no longer counts against recall (with a long tool-call
    query, confidence used to fall as savings rose for that reason alone); critical lines are error lines
    and the rare lines holding a query key, not every line with a number; trust-risk lines count for
    nothing. With no key in the text, recall is not evidence: the score is the critical-line retention.

    This is a diagnostic pass: it does NOT modify the compressed output.
    Callers can use the result to decide whether to re-compress with a
    different strategy, expand dropped blocks, or fail open.
    """
    source = _evidence_blob(original)
    kept_text = _evidence_blob(compressed)
    keys = _source_keys(query, source)
    if keys:
        entity_recall = sum(1 for k in keys if k.lower() in kept_text) / len(keys)
        query_terms = set(_extract_terms(query))
        term_keys = [k for k in keys if k in query_terms]
        keyword_recall = (
            sum(1 for k in term_keys if k.lower() in kept_text) / len(term_keys) if term_keys else entity_recall
        )
    else:
        entity_recall = keyword_recall = 1.0

    critical = _verification_critical_lines(original, keys)
    cl_total = len(critical)
    cl_kept = _critical_kept(critical, compressed) if critical else 0
    important_kept_pct = (cl_kept / cl_total) if cl_total > 0 else 1.0
    critical_lines_dropped = cl_total - cl_kept

    # Risk assessment: combine all three signals
    risk = "low"
    if keys:
        if entity_recall < 0.5:
            risk = "high"
        elif entity_recall < 0.8:
            risk = "medium"
        if keyword_recall < 0.5 and risk == "low":
            risk = "medium"
        elif keyword_recall < 0.3:
            risk = "high"
    if important_kept_pct < 0.5 and risk != "high":
        risk = "high" if important_kept_pct < 0.3 else "medium"

    # Overall score: weighted blend (entity recall matters most for
    # answer quality, keyword recall next, critical lines last). With no key
    # in the text there is no recall to blend.
    if keys:
        score = round(0.5 * entity_recall + 0.3 * keyword_recall + 0.2 * important_kept_pct, 3)
    else:
        score = round(important_kept_pct, 3)

    return {
        "entity_recall": round(entity_recall, 3),
        "keyword_recall": round(keyword_recall, 3),
        "important_kept_pct": round(important_kept_pct, 3),
        "critical_lines_total": cl_total,
        "critical_lines_kept": cl_kept,
        "critical_lines_dropped": critical_lines_dropped,
        "keys_total": len(keys),
        "risk": risk,
        "score": score,
    }


def _query_basis(
    caller_query: str,
    source: str,
    *,
    anchored: bool = False,
    derived: bool = False,
    structural: bool = False,
) -> str:
    """What the confidence of a result rests on (one of ``contract_gates.QUERY_BASES``). The caller's own words
    win when the text contains any of them; otherwise the objective the engine took over (derived, error-anchored,
    the structural fold); otherwise what the words are worth against this text (cross-lingual, none)."""
    profile = query_profile(
        caller_query or "", source,
        extra_terms=_extract_entities(caller_query or "") + _extract_terms(caller_query or ""),
        blob=_evidence_blob(source),
    )
    if profile.basis in ("lexical", "tool_call"):
        return profile.basis
    if derived:
        return "derived"
    if anchored:
        return "anchored"
    if structural:
        return "structural"
    return profile.basis


def _error_retention(original: str, compressed: str) -> tuple[int, int]:
    """(kept, total) of the original's error fingerprints (error heads) that the compressed text still holds.
    Trust-risk lines are never a fingerprint to keep."""
    want = {
        fp for fp, example in error_fingerprints(original, status_rows=False).items()
        if not _is_trust_risk_line(example)
    }
    if not want:
        return 0, 0
    have = set(error_fingerprints(compressed, status_rows=False))
    return len(want & have), len(want)


# Confidence ceilings per basis. A confidence that does not rest on the caller's own words stays below what a
# host gates on (DeepSeek's default gate is 0.7): derived below it, the others cannot reach 1.0.
_CONF_CAP_STRUCTURAL = 0.95
_CONF_CAP_ANCHORED = 0.95
_CONF_CAP_DERIVED = 0.69
_CONF_NO_ERRORS_STRUCTURAL = 0.75  # a fold that only counts repeats, in text with no error to lose
_CONF_NO_ERRORS_ANCHORED = 0.5
_CONF_CAP_NONE = 0.5


def _compute_confidence(
    *,
    basis: str,
    compressed: str,
    fail_open: bool,
    original: str,
    recall: float,
) -> float:
    """The confidence a result reports, by what the objective rests on.

    ``lexical`` / ``tool_call``: the selection's recall over the keys the text contains.
    ``structural`` / ``anchored``: error-fingerprint and error-head retention. ``derived``:
    the same, capped below 0.7, and never the recall of the derived terms themselves. ``cross_lingual`` /
    ``none``: capped at 0.5. A fail-open result keeps the recall it was given (it returns the original)."""
    if fail_open:
        return recall
    if basis in ("lexical", "tool_call"):
        return recall
    if basis in ("structural", "anchored", "derived"):
        kept, total = _error_retention(original, compressed)
        if basis == "structural":
            return _CONF_NO_ERRORS_STRUCTURAL if not total else min(_CONF_CAP_STRUCTURAL, kept / total)
        if basis == "anchored":
            return _CONF_NO_ERRORS_ANCHORED if not total else min(_CONF_CAP_ANCHORED, kept / total)
        return _CONF_NO_ERRORS_ANCHORED if not total else min(_CONF_CAP_DERIVED, kept / total)
    return min(_CONF_CAP_NONE, recall)


def _span_chars(lines: list[str], lo: int, hi: int) -> int:
    """Length of ``"\\n".join(lines[lo:hi])`` without building the string."""
    if hi <= lo:
        return 0
    return sum(len(ln) for ln in lines[lo:hi]) + (hi - lo - 1)


class InliningGapMarker:
    """Wrap a gap marker so renderers may inline short dropped spans.

    Renderers which see it emit a dropped span verbatim when the rendered
    marker is not shorter than the span.
    """

    __slots__ = ("fn",)
    inline_short = True

    def __init__(self, fn: Callable[[int, int], str]) -> None:
        self.fn = fn

    def __call__(self, omitted: int, total: int, kind: str = "lines") -> str:
        return call_gap_marker(self.fn, omitted, total, kind)


def _inlines_short(marker) -> bool:
    return bool(getattr(marker, "inline_short", False))


_SPAN_KIND_SAMPLE = 200
_PASSING_TEST_LINE_RE = re.compile(r"(?:^|[\s\[(])(?:PASSED|PASS|ok|passed)(?:$|[\s\])]|:)|^\s*[✓✔]", re.IGNORECASE)


def _span_kind(span: list[str]) -> str:
    """What a dropped span of lines is, for a kind-aware gap marker: ``frames``, ``progress``, ``tests``, ``repeats``
    (one repeated template) or ``lines``. Looks at the first ``_SPAN_KIND_SAMPLE`` non-blank lines only."""
    sample = [ln for ln in span[:_SPAN_KIND_SAMPLE * 2] if ln.strip()][:_SPAN_KIND_SAMPLE]
    if not sample:
        return "lines"
    if all(_is_frame_line(ln) or _FRAMES_FOLDED_RE.match(ln) for ln in sample):
        return "frames"
    if all(_PROGRESS_RE.match(ln.strip()) for ln in sample):
        return "progress"
    if all(_PASSING_TEST_LINE_RE.search(ln[:_RX_LINE_CAP]) for ln in sample):
        return "tests"
    if len(sample) > 1:
        prints = {_log_fingerprint(ln) for ln in sample}
        if len(prints) == 1 and None not in prints:
            return "repeats"
    return "lines"


_MAX_KEPT_LINE_CHARS = 8192


def _window_oversized_line(
    line: str,
    cap: int,
    hit_terms: tuple[str, ...],
    marker_fn,
    total_chars: int,
    raw_terms: tuple[str, ...] = (),
) -> str:
    """Bound a single oversized kept line to about ``cap`` chars: keep the
    head, the tail and windows around query hits, joining the elided spans
    with the chars-omitted marker. The emitted text always STARTS with a
    prefix of the original line, so a checker reads it as a truncated input
    line, never invented text."""
    span = max(64, cap // 4)
    n = len(line)

    # Hit windows are located on the casefolded text — matching _render's
    # folded terms against 'Straße' needs 'strasse' to hit. Two folds need
    # care: 'İ'.casefold() yields 'i' + a combining dot, which would break a
    # plain 'istanbul' term, so combining marks are dropped from the folded
    # text AND every term; and non-ASCII folding can change length
    # ('ß' → 'ss'), so folded offsets are mapped back to source — but only
    # when the fold actually grew. For ASCII (the megabyte-line case)
    # offsets are identity and no per-character map is built at all.
    low = line.casefold()
    if not low.isascii():
        low = "".join(c for c in low if not unicodedata.combining(c))

    def _fold_len(ch: str) -> int:
        return sum(1 for c in ch.casefold() if not unicodedata.combining(c))

    # Offsets are identity only when EVERY char folds to exactly one output
    # char — len(low) == n alone is not enough: an expansion ('ß' → 'ss')
    # and a removed combining mark can cancel in total length while offsets
    # in between still drift. ASCII folds are always length-1, so the
    # megabyte-line case keeps the fast path with no per-char map.
    need_map = len(low) != n or (
        not low.isascii() and any(_fold_len(ch) != 1 for ch in line)
    )
    if not need_map:
        def _src(folded_pos: int) -> int:
            return min(folded_pos, n - 1)
    else:
        fold_map = [0]
        for ch in line:
            fold_map.append(fold_map[-1] + _fold_len(ch))
        def _src(folded_pos: int) -> int:
            """First source index whose fold covers ``folded_pos``."""
            return bisect.bisect_right(fold_map, folded_pos) - 1

    intervals: list[list[int]] = []
    for ti, term in enumerate(hit_terms):
        t = term.casefold() if term else term
        if t:
            t = "".join(c for c in t if not unicodedata.combining(c))
        if not t:
            continue
        pos = 0
        while True:
            i = low.find(t, pos)
            if i < 0:
                break
            sa = _src(i)
            sb = _src(i + len(t) - 1) + 1
            intervals.append([max(0, sa - span), min(n, sb + span), ti, sa, sb])
            pos = i + len(t)
            if len(intervals) >= 8192:
                break
        if len(intervals) >= 8192:
            break
    # Merge in source order: merging per-term first and sorting after would
    # drop the earlier hit whenever the query lists a later term first, and
    # the merged-span cap must not preferentially keep one term's matches.
    intervals.sort()
    spans: list[list[int]] = []
    span_terms: list[set[int]] = []
    # The hit bounds inside each merged window: a window too big to emit is
    # clipped to an ANCHOR at its earliest still-missing hit rather than its
    # tail — trailing context must never crowd the match itself out.
    span_hits: list[list[list[int]]] = []
    for a, b, ti, ha, hb in intervals:
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
            span_terms[-1].add(ti)
            span_hits[-1].append([ha, hb, ti])
        else:
            spans.append([a, b])
            span_terms.append({ti})
            span_hits.append([[ha, hb, ti]])

    # An earlier folded-only match (an accent-stripped or 'ß'→'ss' variant)
    # must not spend the emit budget ahead of a later VERBATIM hit: spans
    # holding an exact occurrence of a raw (unfolded, original-case) term
    # are preferred — kept first when the merged-span cap trims, and a
    # non-preferred span is skipped only when it would crowd a preferred
    # one out of the remaining budget.
    verbatim = tuple(t for t in (raw_terms or hit_terms) if t)
    pref = [any(t in line[a:b] for t in verbatim) for a, b in spans]
    # Case comparison slices each span BEFORE lowering: lower() can expand
    # a character ('İ' → 'i̇'), so slicing a lowered copy of the whole line
    # at source coordinates reads the wrong window.
    _seg_lows = [line[a:b].lower() for a, b in spans]
    # Match-quality tiers mirror the emit ranking: a verbatim window ('strasse'
    # for a 'strasse' query) outranks a case-only window ('STRASSE'), which
    # outranks a spelling variant ('Straße'). ``q2`` marks the top two tiers;
    # a weaker window is skipped whenever a stronger later one needs the
    # budget, and the span cap below keeps the tiers in the same order.
    q2 = [
        p or any(t.lower() in _seg_lows[i] for t in verbatim)
        for i, p in enumerate(pref)
    ]
    if len(spans) > 32:
        # Tiered trim with term coverage: within each tier, a span holding a
        # term no kept span covers yet is taken first — otherwise 32 repeats
        # of one term's windows could erase another term's only match.
        keep_set: set[int] = set()
        covered_terms: set[int] = set()

        def _want(i: int) -> bool:
            return any(ti not in covered_terms for ti in span_terms[i])

        def _take(i: int) -> None:
            keep_set.add(i)
            covered_terms.update(span_terms[i])

        for tier in (pref, q2):
            for i, ok in enumerate(tier):
                if len(keep_set) >= 32:
                    break
                if ok and i not in keep_set and _want(i):
                    _take(i)
        for i in range(len(spans)):
            if len(keep_set) >= 32:
                break
            if i not in keep_set and _want(i):
                _take(i)
        # Spare slots fill by tier too — a weaker repeat earlier in the
        # line must not take a stronger later window's slot.
        for tier in (pref, q2):
            for i, ok in enumerate(tier):
                if len(keep_set) >= 32:
                    break
                if ok and i not in keep_set:
                    _take(i)
        for i in range(len(spans)):
            if len(keep_set) >= 32:
                break
            if i not in keep_set:
                _take(i)
        keep = sorted(keep_set)
        spans = [spans[i] for i in keep]
        span_terms = [span_terms[i] for i in keep]
        span_hits = [span_hits[i] for i in keep]
        pref = [pref[i] for i in keep]
        q2 = [q2[i] for i in keep]
        _seg_lows = [_seg_lows[i] for i in keep]
    # Match quality per span: a window whose hit only surfaces through the
    # deep fold ('Straße' for 'strasse') is weaker evidence than a window
    # holding the term with just its case different ('STRASSE'). A deep-fold
    # window emitted first must not mark a term covered for a case-exact
    # window later — covered tracks the best emitted quality per term.
    # hit_terms arrive casefolded ('ß' → 'ss'): compare quality against the
    # RAW terms so 'MAẞSTRAẞE' (case-only difference) outranks 'MASSSTRASSE'
    # (spelling difference) for a 'Maßstraße' query.
    _qual_terms = raw_terms or hit_terms
    span_qual = [
        {
            ti: (2 if ti < len(_qual_terms) and _qual_terms[ti].lower() in _seg_lows[i] else 1)
            for ti in ts
        }
        for i, ts in enumerate(span_terms)
    ]
    later_pref = [0] * (len(spans) + 1)
    later_q2 = [0] * (len(spans) + 1)
    for i in range(len(spans) - 1, -1, -1):
        later_pref[i] = later_pref[i + 1] + (spans[i][1] - spans[i][0] if pref[i] else 0)
        later_q2[i] = later_q2[i + 1] + (spans[i][1] - spans[i][0] if q2[i] else 0)

    def _clip_anchor(pos: int, b: int, room: int, hits: list[list[int]],
                     qual: dict[int, int], covered: dict[int, int]) -> int:
        """Where a clipped window begins: at the earliest hit for a
        still-missing term — covering another query term outranks match
        quality, and anchoring early keeps later hits inside the clip.
        Only hits wholly past ``pos`` count — a hit whose head the prefix
        already emitted is no fresh evidence. Match quality only breaks
        ties among repeats of already-covered terms: a verbatim hit
        outranks an earlier case variant."""
        pending = [h for h in hits if h[0] >= pos]
        fresh = [h for h in pending if covered.get(h[2], 0) == 0]
        pool = fresh or pending or [h for h in hits if h[1] > pos]
        if fresh:
            # The earliest still-missing TERM wins the anchor — a later
            # verbatim hit for another term cannot crowd out an earlier
            # term's only match. Within that term the best-quality hit
            # anchors: its verbatim occurrence beats an earlier case
            # variant of the same term.
            first = min(h[0] for h in fresh)
            term = next(h[2] for h in fresh if h[0] == first)
            same = [h for h in fresh if h[2] == term]
            best = max(qual.get(h[2], 0) for h in same)
            anchor = min(h[0] for h in same if qual.get(h[2], 0) == best)
        elif pool:
            best = max(qual.get(h[2], 0) for h in pool)
            anchor = min(h[0] for h in pool if qual.get(h[2], 0) == best)
        else:
            anchor = b - room
        return max(pos, min(b - room, anchor))

    def mark(omitted: int) -> str:
        if marker_fn is not None:
            made = call_gap_marker(marker_fn, omitted, total_chars, "other")
            return str(made) if made else ""
        return f"[… {omitted} chars omitted …]"

    segs: list[str] = []
    pos = 0
    emitted = 0
    # The head always survives: an oversized line kept for structural
    # reasons still shows how it begins, and a marker may never open a line.
    # A hit window overlapping the head may extend it — but only within the
    # same ``cap`` every other segment obeys.
    head = min(span, n)
    for idx, (a, b) in enumerate(spans):
        # Only a strong-tier window may extend the head — a weaker match
        # overlapping it is emitted through the budgeted path like any
        # other — and only when the whole window fits inside ``cap``: a
        # wider window extending the head to ``cap`` would drop a hit
        # sitting past the boundary.
        if a <= head and (pref[idx] or q2[idx]) and b <= cap:
            head = min(cap, max(head, b))
    segs.append(line[:head])
    emitted = head
    pos = head
    covered: dict[int, int] = {}
    for idx, (a, b) in enumerate(spans):
        if b <= pos:
            for ti, q in span_qual[idx].items():
                covered[ti] = max(covered.get(ti, 0), q)
            continue
        a = max(a, pos)
        seg_len = b - a
        if not pref[idx]:
            # 'Fresh' means an UNCOVERED term: a window that only upgrades an
            # already-covered term's match quality ('STRASSE' after 'Straße')
            # is emitted when room allows — but ranks with the duplicates
            # whenever a still-missing term needs the same budget.
            fresh = any(covered.get(ti, 0) == 0 for ti in span_qual[idx])
            if not fresh:
                # A window that only repeats terms already emitted must not
                # fill the remaining budget ahead of a stronger-tier window
                # or a window holding the ONLY match for a still-missing
                # term — it is skipped, not clipped, whenever later evidence
                # needs the room. A case-only duplicate reserves only for a
                # later verbatim window; a spelling-variant duplicate
                # reserves for either.
                later_need = (later_pref if q2[idx] else later_q2)[idx + 1] + sum(
                    spans[j][1] - spans[j][0]
                    for j in range(idx + 1, len(spans))
                    if not pref[j]
                    and (q2[idx] or not q2[j])
                    and any(
                        covered.get(ti, 0) == 0 for ti in span_qual[j]
                    )
                )
                if later_need and emitted + seg_len + later_need > cap:
                    continue
            elif later_pref[idx + 1] and emitted + seg_len + later_pref[idx + 1] > cap:
                # Reserve the remaining budget for a later verbatim-hit
                # window — but keep this fresh hit too when trimming the
                # window's context fits it next to the reservation. The clip
                # is anchored at the earliest still-missing hit, not the
                # window tail: ``room`` smaller than the trailing context
                # would otherwise keep only context and drop the match.
                room = cap - emitted - later_pref[idx + 1]
                if room > 0:
                    clip_a = _clip_anchor(pos, b, room, span_hits[idx],
                                          span_qual[idx], covered)
                    if clip_a > pos:
                        segs.append(mark(clip_a - pos))
                    clip_b = clip_a + room
                    segs.append(line[clip_a:clip_b])
                    emitted += clip_b - clip_a
                    pos = clip_b
                    for ti, q in span_qual[idx].items():
                        covered[ti] = max(covered.get(ti, 0), q)
                continue
        if emitted + seg_len > cap:
            # A window that does not fit whole is not dropped: it fills the
            # remaining budget anchored at the earliest still-missing hit,
            # so a late query term — or an early hit inside a merged window
            # that sits before the tail — is never silently lost. ``pos``
            # lands at the clip's end so a later marker counts what the
            # clip actually omitted, not the whole window width.
            remain = cap - emitted
            if remain > 0:
                clip_a = _clip_anchor(pos, b, remain, span_hits[idx],
                                      span_qual[idx], covered)
                if clip_a > pos:
                    segs.append(mark(clip_a - pos))
                clip_b = clip_a + remain
                segs.append(line[clip_a:clip_b])
                emitted += clip_b - clip_a
                pos = clip_b
            break
        # A window overlapping the kept prefix starts mid-match: nothing
        # was omitted between ``pos`` and ``a``, so no boundary marker —
        # inserting one would split the match visually.
        if a > pos:
            segs.append(mark(a - pos))
        segs.append(line[a:b])
        emitted += seg_len
        pos = b
        for ti, q in span_qual[idx].items():
            covered[ti] = max(covered.get(ti, 0), q)
    tail_a = max(pos, n - span)
    if emitted + (n - tail_a) <= cap and tail_a > pos:
        segs.append(mark(tail_a - pos))
        segs.append(line[tail_a:])
        pos = n
    if pos < n:
        segs.append(mark(n - pos))
    return "".join(segs)


def _render(
    lines: list[str],
    blocks: list[dict[str, Any]],
    kept: set[int],
    citations: bool = False,
    reorder_best: bool = False,
    gap_marker: Callable[[int, int], str] | None = None,
    total_chars: int | None = None,
    content_lines: list[str] | None = None,
    query: str | None = None,
) -> str:
    chronological_blocks: list[dict[str, Any]] | None = None
    block_starts: list[int] = []
    order = sorted((b for b in blocks if b["id"] in kept), key=lambda b: b["start"])
    chronological = True
    if reorder_best and len(order) >= 3:
        # Lost-in-the-middle mitigation (LongLLMLingua / twotrim): models
        # attend hardest to window edges. Best-scoring block anchors the
        # front, second-best anchors the end, the rest stay chronological.
        ranked = sorted(order, key=lambda b: -float(b.get("score", 0.0)))
        best, second = ranked[0], ranked[1]
        rest = [b for b in order if b["id"] not in {best["id"], second["id"]}]
        order = [best, *rest, second]
        chronological = False
    # v1.4.0 (E8): a caller-supplied gap marker replaces EVERY gap marker
    # (citations=False only): leading, internal and trailing. It is called as
    # gap_marker(omitted_chars, total_chars) with the length of the dropped
    # span (its lines joined with "\n") and the length of the caller's input.
    # Spans of blank lines only are not content and get no marker, and one
    # dropped span yields exactly one marker however many blocks it holds.
    # gap_marker=None keeps the historical "[…]" behaviour byte for byte.
    marker_fn = gap_marker if (gap_marker is not None and not citations) else None
    total = total_chars if total_chars is not None else _span_chars(lines, 0, len(lines))
    # "Is this span blank?" is judged on the lines the scorer read: a
    # numbered-code gutter ("75|", "    75\t") makes an empty source line
    # non-empty in `lines`, and would earn a bogus marker between two
    # adjacent kept blocks.
    probe_lines = content_lines if content_lines is not None else lines
    inline_short = _inlines_short(marker_fn) if marker_fn is not None else False
    wants_kind = marker_fn is not None and gap_accepts_kind(getattr(marker_fn, "fn", marker_fn))

    # A kept line may not be unbounded: a hostile 1MB single line used to
    # pass through byte for byte and saved nothing. Bound it to
    # _MAX_KEPT_LINE_CHARS, keeping head, tail and windows around query hits.
    hit_terms: tuple[str, ...] = ()
    raw_hit_terms: tuple[str, ...] = ()
    if query:
        raw_hit_terms = tuple(
            t for t in (_extract_entities(query) + _extract_terms(query))
            if len(t) >= 3
        )
        hit_terms = tuple(t.casefold() for t in raw_hit_terms)

    def _bound(ln: str) -> str:
        if len(ln) <= _MAX_KEPT_LINE_CHARS:
            return ln
        return _window_oversized_line(
            ln, _MAX_KEPT_LINE_CHARS, hit_terms, marker_fn, total, raw_hit_terms
        )

    def _gap(lo: int, hi: int) -> list[str] | None:
        if marker_fn is None:
            return None
        if not any(ln.strip() for ln in probe_lines[lo:hi]):
            return None
        span_text = "\n".join(lines[lo:hi]) if inline_short else None
        kind = _span_kind(lines[lo:hi]) if wants_kind else "lines"
        text = call_gap_marker(marker_fn, _span_chars(lines, lo, hi), total, kind)
        marker = str(text) if text is not None else ""
        if not marker:
            return None
        # 1.4.1 opt-in: only InliningGapMarker emits the dropped lines
        # verbatim when the rendered marker is not shorter than the span.
        if inline_short and span_text is not None and len(marker) >= len(span_text):
            return lines[lo:hi]
        return [marker]

    parts: list[str] = []
    prev_end = -1
    for b in order:
        if chronological and b["end"] <= prev_end:
            continue
        if marker_fn is not None:
            if prev_end < 0 and chronological and b["start"] > 0:
                lead = _gap(0, b["start"])
                if lead is not None:
                    parts.extend(lead)
            elif prev_end >= 0 and b["start"] > prev_end + 1:
                between = _gap(prev_end + 1, b["start"])
                if between is not None:
                    parts.extend(between)
        elif prev_end >= 0 and b["start"] > prev_end + 1:
            if citations:
                if chronological_blocks is None:
                    chronological_blocks = sorted(blocks, key=lambda block: block["start"])
                    block_starts = [block["start"] for block in chronological_blocks]
                # ARC-style citation: name every dropped block so the model
                # knows it can recall the exact head/tail by hash later.
                # Only emit citations when they're net-positive: the stub
                # tokens must be less than the dropped block tokens they replace.
                left = bisect.bisect_right(block_starts, prev_end)
                right = bisect.bisect_left(block_starts, b["start"])
                dropped = [
                    block
                    for block in chronological_blocks[left:right]
                    if block["id"] not in kept and block["end"] < b["start"]
                ]
                gap_tokens = 0
                dropped_tokens = 0
                for d in dropped:
                    dropped_tokens += d["tokens"]
                    d_text = d.get("full_text") or d["text"]
                    if d.get("trust_risk") and not d.get("pinned"):
                        stub = "[§] (flagged block withheld)"
                    else:
                        head = d_text.split("\n", 1)[0][:60]
                        tail = d_text.rsplit("\n", 1)[-1][:60]
                        stub = f'[§] "{head}"…"{tail}"'
                    gap_tokens += estimate_tokens(stub)
                if gap_tokens < dropped_tokens:
                    # Citations save tokens — emit them. For long runs of
                    # consecutive dropped blocks, per-block stubs defeat
                    # the purpose (v0.6.0: 4000-block dump → 500KB of
                    # stubs). Collapse runs longer than 8 into one summary.
                    if len(dropped) > 8:
                        first = dropped[0]
                        last = dropped[-1]
                        parts.append(
                            f"[§run:{len(dropped)} blocks #{first['start']}–{last['end']} elided]"
                        )
                    else:
                        for d in dropped:
                            d_text = d.get("full_text") or d["text"]
                            digest = hashlib.sha256(d_text.encode("utf-8", errors="surrogatepass")).hexdigest()[:8]
                            if d.get("trust_risk") and not d.get("pinned"):
                                # A block dropped as a suspected injection is
                                # not quoted back into its citation stub.
                                parts.append(f"[§{digest}] (flagged block withheld)")
                                continue
                            head = d_text.split("\n", 1)[0][:60]
                            tail = d_text.rsplit("\n", 1)[-1][:60]
                            parts.append(f'[§{digest}] "{head}"…"{tail}"')
                else:
                    # Citations would add more tokens than they save — use bare gap
                    parts.append("[…]")
            else:
                parts.append("[…]")
        start, end = b["start"], b["end"]
        if chronological:
            start = max(start, prev_end + 1)
        # Structural verbatim invariant (leanctx-inspired): a kept fenced
        # code block must survive whole — extend the keep range to the
        # closing fence if it lands just outside, so agents see exact tokens.
        kept_text = lines[start : end + 1]
        fences = sum(1 for ln in kept_text if ln.strip().startswith("```"))
        if fences % 2 == 1:
            j = end + 1
            while j < len(lines):
                if lines[j].strip().startswith("```"):
                    end = j
                    break
                j += 1
        # Verbatim regions are exempt from the oversized-line window: a pinned
        # block must come back byte-for-byte (the pin gate compares exact
        # source), and rewriting text inside an intact fence presents altered
        # code as unaltered.
        if b.get("pinned"):
            parts.extend(lines[start : end + 1])
        else:
            in_fence = False
            for ln in lines[start : end + 1]:
                if ln.strip().startswith("```"):
                    in_fence = not in_fence
                    parts.append(ln)
                else:
                    parts.append(ln if in_fence else _bound(ln))
        prev_end = end
    if marker_fn is not None and chronological and parts and prev_end < len(lines) - 1:
        trail = _gap(prev_end + 1, len(lines))
        if trail is not None:
            parts.extend(trail)
    return "\n".join(parts)


def _gap_marker_reserve(
    lines: list[str],
    blocks: list[dict[str, Any]],
    kept: set[int],
    gap_marker: Callable[[int, int], str],
    total_chars: int,
    content_lines: list[str] | None = None,
) -> int:
    """Tokens the caller's gap markers will take for this keep-set: the number
    of dropped spans that hold content (leading, internal, trailing) times the
    size of a marker. Mirrors _render's gap rules."""
    spans = sorted((b["start"], b["end"]) for b in blocks if b["id"] in kept)
    if not spans:
        return 0
    n = len(lines)
    probe_lines = content_lines if content_lines is not None else lines

    def content(lo: int, hi: int) -> bool:
        return any(ln.strip() for ln in probe_lines[lo:hi])

    gaps = 1 if spans[0][0] > 0 and content(0, spans[0][0]) else 0
    prev_end = spans[0][1]
    for start, end in spans[1:]:
        if start > prev_end + 1 and content(prev_end + 1, start):
            gaps += 1
        prev_end = max(prev_end, end)
    if prev_end < n - 1 and content(prev_end + 1, n):
        gaps += 1
    if not gaps:
        return 0
    # One probe call sizes a marker at its widest (a span as long as the
    # whole input); callers that count gap_marker calls see exactly one extra
    # call in fixed mode, none in adaptive mode.
    sample = str(call_gap_marker(gap_marker, total_chars, total_chars, "lines") or "")
    return gaps * estimate_tokens(sample)


def cache_wrap(compressed: str, query: str) -> str:
    return (
        "<compressed_context version=\"1\">\n"
        "The following text is extractive context: original wording only, "
        "low-value blocks removed. Use it to answer the user.\n\n"
        "--- context ---\n"
        f"{compressed}\n"
        "--- end context ---\n"
        "</compressed_context>\n\n"
        f"Answer the question: {query}"
    )


def _block_fingerprint(block: dict[str, Any]) -> str:
    """Stable fingerprint for freeze-on-first-sight: type + id + content.

    The block id distinguishes repeated identical records that can receive
    different head/middle/tail decisions. Appending turns preserves prior ids.
    """
    content_hash = hashlib.sha256(block["text"].encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"{block['type']}:{block.get('id', '?')}:{content_hash}"


_FREEZE_PREFIX_CHARS = 500


def _apply_freeze(
    decision_cache: dict,
    scored: list[dict[str, Any]],
    original_text: str,
    query: str = "",
) -> list[dict[str, Any]]:
    """Replay stored keep/drop decisions for blocks whose fingerprint matches.

    The cache maps block fingerprint -> 'keep' | 'drop'. On a multi-turn
    session, the first turn that sees a block makes the decision; later turns
    replay it byte-identically so the provider prompt cache stays warm.

    New blocks remain undecided until selection has completed. Their actual
    keep/drop outcome is recorded by :func:`_record_freeze_decisions`.
    """
    cache_key = "decisions"
    schema_version = decision_cache.get("schema_version")
    if schema_version is not None and schema_version != 1:
        for stale_key in (
            cache_key,
            "query_hash",
            "ctx_hash",
            "ctx_prefix_len",
        ):
            decision_cache.pop(stale_key, None)
    if not isinstance(decision_cache.get(cache_key), dict):
        decision_cache[cache_key] = {}
    decisions: dict = decision_cache[cache_key]
    decision_cache["schema_version"] = 1

    query_hash = hashlib.sha256((query or "").encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    cached_query_hash = decision_cache.get("query_hash")
    if isinstance(cached_query_hash, str) and cached_query_hash != query_hash:
        decisions = {}
        decision_cache[cache_key] = decisions
    decision_cache["query_hash"] = query_hash

    # Store a hash and length for the original prefix. Length matters when the
    # first turn is shorter than 500 chars: hashing a fresh 500-char slice on
    # the next turn would include appended content and falsely invalidate the
    # cache. No plaintext context is retained in the decision cache.
    cached_prefix_len = decision_cache.get("ctx_prefix_len")
    if (
        not isinstance(cached_prefix_len, int)
        or not 0 <= cached_prefix_len <= _FREEZE_PREFIX_CHARS
    ):
        cached_prefix_len = min(len(original_text), _FREEZE_PREFIX_CHARS)
        decision_cache["ctx_prefix_len"] = cached_prefix_len
    ctx_hash = hashlib.sha256(
        original_text[:cached_prefix_len].encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:12]
    if "ctx_hash" not in decision_cache:
        decision_cache["ctx_hash"] = ctx_hash
    elif decision_cache["ctx_hash"] != ctx_hash:
        # Context changed fundamentally — clear decisions to avoid stale replay.
        decisions = {}
        decision_cache[cache_key] = decisions
        cached_prefix_len = min(len(original_text), _FREEZE_PREFIX_CHARS)
        decision_cache["ctx_prefix_len"] = cached_prefix_len
        ctx_hash = hashlib.sha256(
            original_text[:cached_prefix_len].encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:12]
        decision_cache["ctx_hash"] = ctx_hash

    # Tag old decisions for enforcement after the normal selector runs.
    result = []
    for b in scored:
        fp = _block_fingerprint(b)
        decision = decisions.get(fp)
        if not isinstance(decision, str) or decision not in {"keep", "drop"}:
            decision = None
        result.append(
            {
                **b,
                "frozen": decision is not None,
                "freeze_decision": decision,
            }
        )
    return result


def _enforce_frozen_decisions(
    scored: list[dict[str, Any]], kept: set[int]
) -> set[int]:
    """Apply cached decisions without allowing them to bypass trust or pins."""
    enforced = set(kept)
    for b in scored:
        bid = b["id"]
        if b.get("pinned"):
            enforced.add(bid)
            continue
        decision = b.get("freeze_decision")
        if decision == "drop":
            enforced.discard(bid)
        elif decision == "keep" and not b.get("trust_risk"):
            enforced.add(bid)
    return enforced


def _record_freeze_decisions(
    decision_cache: dict,
    scored: list[dict[str, Any]],
    kept: set[int],
) -> bool:
    """Record first-sight outcomes, preserving the oldest bounded prefix."""
    decisions = decision_cache.setdefault("decisions", {})
    if not isinstance(decisions, dict):
        decisions = {}
        decision_cache["decisions"] = decisions
    saturated = False
    for b in scored:
        fp = _block_fingerprint(b)
        if fp in decisions:
            continue
        if len(decisions) >= FREEZE_MAX_DECISIONS:
            saturated = True
            break
        decisions[fp] = "keep" if b["id"] in kept else "drop"
    return saturated


def _ccr_metadata(data: Any) -> tuple[float, float] | None:
    """Return validated ``(stored_at, ttl)`` metadata for a CCR record."""
    if not isinstance(data, dict):
        return None
    try:
        stored = float(data["stored_at"])
        ttl = float(data.get("ttl", CCR_TTL_SECONDS))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(stored)
        or not math.isfinite(ttl)
        or stored <= 0
        or ttl <= 0
    ):
        return None
    return stored, ttl


def sweep_ccr_cache(
    ccr_dir: str | Path = DEFAULT_CCR_DIR,
    *,
    now: float | None = None,
    max_records: int | None = None,
) -> int:
    """Delete expired valid CCR records and return the removal count.

    Files that cannot be read or parsed are left untouched: retention
    maintenance is best-effort. A file that parses but is not a valid record
    (bad metadata, a non-object payload) is removed like an expired one.
    """
    global _CCR_SWEEP_CURSOR
    root = Path(ccr_dir)
    if not root.is_dir():
        return 0
    try:
        current = time.time() if now is None else float(now)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(current) or current <= 0:
        return 0
    removed = 0
    limit = None if max_records is None else max(0, int(max_records))
    # Cursor progression only works when every call sees the same ordering,
    # so the directory is listed once, partitioned by name, and sorted.
    try:
        names = [entry.name for entry in root.iterdir()]
    except OSError:
        return 0
    records = sorted((root / name) for name in names if name.endswith(".json"))
    if limit is not None and records:
        total = len(records)
        key = str(root.resolve())
        with _CCR_SWEEP_LOCK:
            if not isinstance(_CCR_SWEEP_CURSOR, dict):
                _CCR_SWEEP_CURSOR = {}
            start = int(_CCR_SWEEP_CURSOR.get(key, 0)) % total
            count = min(limit, total)
            _CCR_SWEEP_CURSOR[key] = (start + count) % total
        records = [records[(start + offset) % total] for offset in range(count)]
    for fp in records:
        if not _CCR_HASH_RE.fullmatch(fp.stem):
            continue
        try:
            data = _read_ccr_record(fp)
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            continue
        metadata = _ccr_metadata(data)
        if (
            metadata is not None
            and metadata[0] <= current + CCR_MAX_CLOCK_SKEW_SECONDS
            and current - metadata[0] <= metadata[1]
        ):
            continue
        try:
            fp.unlink()
            removed += 1
        except OSError:
            continue
    # A killed store leaves a ``.<name>.XXXXXX`` temp file holding the full
    # original. Remove it once it is old enough that no live writer could
    # still hold it.
    for name in names:
        if not name.startswith(".") or ".json." not in name:
            continue
        fp = root / name
        try:
            info = fp.lstat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and current - info.st_mtime > _CCR_TEMP_GRACE_SECONDS:
            try:
                fp.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _ccr_store(original: str, ccr_dir: str | Path) -> dict[str, Any] | None:
    # Secrets screen: archival would persist credentials to disk at rest.
    # The unwrapped payload is screened too — inside a JSON tool envelope a
    # line-start credential is escaped as ``\nX``, which the line-anchored
    # rules cannot see on the raw envelope text.
    if _contains_secret(original) or _contains_secret(unwrap_tool_payload(original).inner):
        return None
    path = Path(ccr_dir)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise OSError(f"CCR directory must be a real directory: {path}")
    try:
        path.chmod(0o700)
    except OSError:
        pass
    sweep_ccr_cache(path, max_records=CCR_SWEEP_MAX_RECORDS)
    digest = hashlib.sha256(original.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
    payload = {
        "hash": digest,
        "stored_at": time.time(),
        "ttl": CCR_TTL_SECONDS,
        "original": original,
    }
    record = path / f"{digest}.json"
    encoded = json.dumps(payload).encode("utf-8")
    if len(encoded) > _CCR_MAX_RECORD_BYTES:
        return None
    _write_private_atomic(record, encoded)
    return {"hash": digest, "path": str(record)}


def _write_private_atomic(path: str | Path, content: str | bytes) -> None:
    """Atomically replace bytes or a UTF-8 sidecar with owner-only permissions."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        if not target.parent.is_dir():
            raise
    else:
        try:
            target.parent.chmod(0o700)
        except OSError:
            pass
    fd: int | None = None
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with (os.fdopen(fd, "wb") if isinstance(content, bytes)
              else os.fdopen(fd, "w", encoding="utf-8")) as fh:
            fd = None
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, target)
        temporary = None
        target.chmod(0o600)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _clear_tool_payloads(text: str) -> str:
    """Strategy='clear': drop re-fetchable tool-result payloads.

    Finds lines that look like tool output (indented JSON, long indented
    blocks after a tool-call line) and replaces them with a one-line
    marker. The tool name and call signature are preserved. This is the
    cheapest compression step — zero LLM cost, just regex.

    Patterns handled:
    - Lines starting with 2+ spaces that contain JSON braces/brackets
      (tool output indented under a tool-call line)
    - Long JSON blobs (> 200 chars) that appear to be tool results
    - Multi-line indented blocks following a 'TOOL:' or '> ' prefix

    Returns the text with payloads replaced by [tool-result: N chars cleared].
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        # Detect tool-result start: indented JSON, or a line that looks
        # like a tool output marker.
        is_tool_result = False
        if (
            (line.startswith("  ") or line.startswith("\t"))
            and (
                stripped.startswith("{")
                or stripped.startswith("[")
                or stripped.startswith('"')
            )
        ) or (stripped.startswith("TOOL:") and len(stripped) > 30):
            is_tool_result = True
        elif re.match(r"^\s{2,}\w[^(]*\(", line) and "=>" in stripped:
            # Indented function-call line with an arrow (tool call result)
            is_tool_result = True

        if is_tool_result:
            # Collect the full payload (consecutive indented lines)
            j = i + 1
            total_chars = len(line)
            while j < len(lines):
                payload_line = lines[j]
                if payload_line.strip() == "":
                    # Blank line might end the payload or be part of it.
                    # Look ahead: if the next non-blank line is also indented,
                    # the payload continues.
                    k = j + 1
                    while k < len(lines) and lines[k].strip() == "":
                        k += 1
                    if k < len(lines) and (
                        lines[k].startswith("  ") or lines[k].startswith("\t")
                    ):
                        j += 1
                        continue
                    else:
                        break
                elif lines[j].startswith("  ") or lines[j].startswith("\t"):
                    total_chars += len(payload_line)
                    j += 1
                else:
                    break
            # Only clear if the payload is substantial (> 100 chars)
            if total_chars > 100:
                # Extract the tool name if visible
                tool_name = ""
                m = re.search(r"(?:TOOL:|=>)\s*(\w+)", line)
                if m:
                    tool_name = m.group(1)
                marker = f"  [tool-result{':' + tool_name if tool_name else ''}: {total_chars} chars cleared — re-fetch if needed]"
                out.append(marker)
                i = j
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


_SUMMARY_MAX_MODELS = 16
_SUMMARY_MAX_MODEL_CHARS = 1024


def _summarise_with_llm(
    text: str,
    query: str,
    target_ratio: float = 0.25,
    *,
    endpoint: str | None = None,
    model_candidates: Iterable[str] | str | None = None,
    timeout: float | None = None,
    allow_remote: bool | None = None,
) -> Optional[str]:
    """Strategy='summarise': use a local LLM to compress the context.

    Calls an OpenAI-compatible endpoint. Endpoint, model candidates, and the
    total retry budget can be supplied directly or through the
    ``TAMERU_SUMMARY_ENDPOINT``, ``TAMERU_SUMMARY_MODELS``, and
    ``TAMERU_SUMMARY_TIMEOUT`` environment variables.
    Returns the summarised text, or None on any failure (fail-open).

    The prompt asks the model to produce a faithful summary that:
    - Preserves all entities, identifiers, and facts
    - Keeps the query-relevant content verbatim
    - Drops filler and re-fetchable tool payloads
    - Targets ~target_ratio of the original length

    This is the "smart" end of the strategy ladder: highest quality,
    highest cost (one LLM call). Falls back to None (caller fails open)
    on any error: model unavailable, timeout, JSON parse failure, etc.
    """
    import urllib.request
    import urllib.error
    import urllib.parse

    # Target length in tokens
    try:
        ratio = float(target_ratio)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(ratio) or not 0 < ratio <= 1:
        return None
    target_tokens = max(50, int(estimate_tokens(text) * ratio))

    prompt = (
        f"Summarise the following context faithfully. Keep ALL entities, "
        f"identifiers, names, numbers, dates, and specific facts verbatim. "
        f"Drop filler, lorem ipsum, and re-fetchable tool output. "
        f"The user's question is: \"{query}\"\n"
        f"Target length: approximately {target_tokens} tokens.\n"
        f"Preserve the original wording for key facts. Do not add new information.\n\n"
        f"CONTEXT:\n{text[:60000]}"  # Cap input at 60k chars to avoid overflow
    )

    endpoint = endpoint or os.environ.get("TAMERU_SUMMARY_ENDPOINT") or DEFAULT_SUMMARY_ENDPOINT
    if allow_remote is None:
        allow_remote = os.environ.get("TAMERU_SUMMARY_ALLOW_REMOTE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
    try:
        parsed_endpoint = urllib.parse.urlsplit(endpoint)
    except (TypeError, ValueError):
        return None
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.hostname:
        return None
    local_hosts = {"127.0.0.1", "::1", "localhost"}
    if parsed_endpoint.hostname.casefold() not in local_hosts and not allow_remote:
        return None
    if model_candidates is None:
        configured = os.environ.get("TAMERU_SUMMARY_MODELS", "")
        model_candidates = configured if configured.strip() else DEFAULT_SUMMARY_MODELS
    if isinstance(model_candidates, str):
        model_candidates = model_candidates.split(",", _SUMMARY_MAX_MODELS)[:_SUMMARY_MAX_MODELS]
    models: list[str] = []
    try:
        for model in itertools.islice(model_candidates, _SUMMARY_MAX_MODELS):
            if not isinstance(model, str):
                return None
            if len(model) > _SUMMARY_MAX_MODEL_CHARS:
                return None
            model = model.strip()
            if model:
                models.append(model)
    except Exception:  # caller-provided iterators must fail open
        return None
    if not models:
        return None
    if timeout is None:
        try:
            timeout = float(os.environ.get("TAMERU_SUMMARY_TIMEOUT", DEFAULT_SUMMARY_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_SUMMARY_TIMEOUT
    try:
        timeout = float(timeout)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return None
    timeout = max(0.1, timeout)
    deadline = time.monotonic() + timeout

    class _NoSummaryRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, "summary redirects disabled", headers, fp)

    opener = urllib.request.build_opener(_NoSummaryRedirect())
    for model in models:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": target_tokens,
                    "temperature": 0.1,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(req, timeout=remaining) as resp:
                raw = resp.read(MAX_SUMMARY_RESPONSE_BYTES + 1)
                if len(raw) > MAX_SUMMARY_RESPONSE_BYTES:
                    continue
                data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                continue
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            if not content or len(content.strip()) < 20:
                continue
            return content.strip()
        except (
            urllib.error.URLError,
            OSError,
            ValueError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TimeoutError,
            TypeError,
            AttributeError,
            OverflowError,
            RecursionError,
        ):
            continue
    return None


# v1.4.0 (E2): the two class runs are bounded ({0,127}); the unbounded form
# re-scanned the rest of a long separator-rich run (`a.a.a.…`, 20k chars) from
# every word boundary — quadratic. Tokens up to 256 chars match as before.
_SUMMARY_STRUCTURED_TOKEN_RE = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9_.:/-]{0,127}\d[A-Za-z0-9_.:/-]{0,127}"
    r"|\d+(?:[.:/-]\d+)*)\b"
)


def _summary_preserves_required_facts(
    source: str, summary: str, query: str
) -> tuple[bool, float]:
    """Conservative factual gate for the optional model-summary strategy."""
    source_fold = source.casefold()
    summary_fold = summary.casefold()
    # Perf (v1.4.0, E2): `required` stays a list (order is part of the
    # contract) but membership is answered by a set — `token not in list` made
    # this loop quadratic (92 s on a 3.7 MB history).
    required: list[str] = []
    required_set: set[str] = set()
    candidates = (
        _SUMMARY_STRUCTURED_TOKEN_RE.findall(query or "")
        + _extract_entities(query or "")
        + _extract_terms(query or "")
    )
    for item in candidates:
        token = str(item).strip().casefold()
        if token and token in source_fold and token not in required_set:
            required.append(token)
            required_set.add(token)

    # Values answering the question often appear only in the matching source
    # line, not in the question itself (for example query host db-prod-01 and
    # answer port 5432). Preserve structured values from source segments tied
    # to a query identifier, or to at least two lexical query terms.
    query_ids = {
        token.casefold()
        for token in _SUMMARY_STRUCTURED_TOKEN_RE.findall(query or "")
    }
    query_terms = {
        token.casefold()
        for token in (_extract_entities(query or "") + _extract_terms(query or ""))
        if token
    }
    for segment in re.split(r"[\r\n]+|(?<=[.!?])\s+", source):
        segment_fold = segment.casefold()
        id_match = bool(query_ids) and any(
            token in segment_fold for token in query_ids
        )
        term_hits = sum(1 for token in query_terms if token in segment_fold)
        if not id_match and term_hits < 2:
            continue
        for item in _SUMMARY_STRUCTURED_TOKEN_RE.findall(segment):
            token = item.casefold()
            if token not in required_set:
                required.append(token)
                required_set.add(token)
        # Plain-text scalar answers are not necessarily identifiers (for
        # example "paint color is ultraviolet"). Require the first content
        # term after a queried field and a simple relation verb; do not require
        # every adjective in a long source segment.
        for query_term in sorted(query_terms, key=len, reverse=True):
            match = re.search(
                rf"(?<!\w){re.escape(query_term)}(?!\w)\s+"
                r"(?:is|are|was|were|equals?|uses?|=)\s+(.+)$",
                segment,
                re.IGNORECASE,
            )
            if not match:
                continue
            answer_terms = _extract_terms(match.group(1))
            if answer_terms:
                token = answer_terms[0].casefold()
                if token not in query_terms and token not in required_set:
                    required.append(token)
                    required_set.add(token)
            break
    source_ids = {
        token.casefold() for token in _SUMMARY_STRUCTURED_TOKEN_RE.findall(source)
    }
    summary_ids = {
        token.casefold() for token in _SUMMARY_STRUCTURED_TOKEN_RE.findall(summary)
    }
    # Perf (v1.4.0): a required token that is itself a token of the summary is
    # found by a set lookup; only the others pay the substring scan (which is
    # what decides the same question, since a token of the summary is a
    # substring of it). Same answer, linear when the summary kept its facts.
    kept = sum(
        1 for token in required if token in summary_ids or token in summary_fold
    )
    recall = kept / len(required) if required else 1.0
    no_novel_ids = summary_ids.issubset(source_ids)
    return recall == 1.0 and no_novel_ids, recall


_CCR_MAX_RECORD_BYTES = 128 * 1024 * 1024  # exceeds 8M input chars at 12 JSON bytes per char


def _read_ccr_record(fp: Path) -> Any:
    info = fp.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError("CCR record must be a regular file")
    if info.st_size > _CCR_MAX_RECORD_BYTES:
        raise OSError("CCR record exceeds size limit")
    with fp.open("rb") as fh:
        raw = fh.read(_CCR_MAX_RECORD_BYTES + 1)
    if len(raw) > _CCR_MAX_RECORD_BYTES:
        raise OSError("CCR record exceeds size limit")
    return json.loads(raw.decode("utf-8-sig"))


def _ccr_original(data: Any, digest: str) -> str | None:
    if not isinstance(data, dict) or data.get("hash") != digest:
        return None
    original = data.get("original")
    if not isinstance(original, str):
        return None
    actual = hashlib.sha256(original.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
    return original if actual == digest else None


def retrieve(
    ccr_hash: str,
    ccr_dir: str | Path = DEFAULT_CCR_DIR,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> Optional[str]:
    """Fetch a CCR record's original text. offset/limit paginate large
    records (pi-lcm lcm_expand-style partial recall)."""
    if not isinstance(ccr_hash, str) or not _CCR_HASH_RE.fullmatch(ccr_hash):
        return None
    root = Path(ccr_dir)
    if root.is_symlink() or not root.is_dir():
        return None
    fp = root / f"{ccr_hash}.json"
    try:
        data = _read_ccr_record(fp)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("hash") != ccr_hash:
        return None
    metadata = _ccr_metadata(data)
    current = time.time()
    if (
        metadata is None
        or metadata[0] > current + CCR_MAX_CLOCK_SKEW_SECONDS
        or current - metadata[0] > metadata[1]
    ):
        try:
            fp.unlink()
        except OSError:
            pass
        return None
    original = _ccr_original(data, ccr_hash)
    if original is None:
        return None
    if offset or limit is not None:
        start = max(0, int(offset))
        return original[start:] if limit is None else original[start:start + max(0, int(limit))]
    return original


def list_ccr(
    ccr_dir: str | Path = DEFAULT_CCR_DIR,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List live CCR records newest-first (pi-lcm lcm_grep/describe analog).

    Returns metadata only — hash, stored_at, ttl, chars, and a short
    preview — so callers can discover records without loading full
    originals. Expired or malformed records are skipped.
    """
    root = Path(ccr_dir)
    if root.is_symlink() or not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    current = time.time()
    for fp in root.glob("*.json"):
        if not fp.name.startswith(".") and _CCR_HASH_RE.fullmatch(fp.stem):
            try:
                data = _read_ccr_record(fp)
            except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(data, dict):
                continue
            metadata = _ccr_metadata(data)
            if (
                metadata is None
                or metadata[0] > current + CCR_MAX_CLOCK_SKEW_SECONDS
                or current - metadata[0] > metadata[1]
            ):
                continue
            record_hash = data.get("hash")
            original = _ccr_original(data, fp.stem)
            if (
                not isinstance(record_hash, str)
                or record_hash != fp.stem
                or not isinstance(original, str)
            ):
                continue
            out.append({
                "hash": record_hash,
                "stored_at": metadata[0],
                "ttl": metadata[1],
                "chars": len(original),
                "preview": original[:80],
            })
    out.sort(key=lambda r: (-r["stored_at"], r["hash"]))
    start = max(0, int(offset))
    if limit is None:
        return out[start:]
    return out[start:start + max(0, int(limit))]


# ---------------------------------------------------------------------------
# JSON preprocessor (Baseline RAG-inspired)
#
# Detects JSON payloads in the context and crushes redundant array items.
# Keeps only query-relevant items + a bounded sample of the rest, preserving
# the top-level structure. This is the "JSON policy" from Baseline RAG's
# type-specific policy system.
# ---------------------------------------------------------------------------

_JSON_OPENER_RE = re.compile(r"[{\[]")
_JSON_SCAN_RE = re.compile(r'[\\"{}\[\]]')


def _detect_json_payloads(text: str) -> list[tuple[int, int, str]]:
    """Find JSON object/array spans in the text.

    Returns a list of (start, end, json_string) tuples where start/end are
    character offsets into the original text.

    Perf (v1.5.0): the scanners jump between the characters that can change
    their state (openers; quotes, backslashes and brackets) instead of
    stepping through every character; the spans are unchanged.
    """
    payloads = []
    i = 0
    n = len(text)
    find_opener = _JSON_OPENER_RE.search
    find_special = _JSON_SCAN_RE.search
    while i < n:
        opener = find_opener(text, i)
        if opener is None:
            break
        i = opener.start()
        # Try to find the matching close
        depth = 0
        in_string = False
        j = i
        while True:
            hit = find_special(text, j)
            if hit is None:
                j = n
                break
            j = hit.start()
            c = text[j]
            if c == "\\":
                if in_string:
                    j += 2  # the escaped character is skipped, whatever it is
                    continue
            elif c == '"':
                in_string = not in_string
            elif not in_string:
                if c in "{[":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        if j < n and depth == 0:
            candidate = text[i:j + 1]
            # Only count if it's a reasonable JSON payload (> 200 chars)
            if len(candidate) > 200:
                payloads.append((i, j + 1, candidate))
            i = j + 1
        else:
            # The first unmatched opener already scanned the remaining
            # suffix. Restarting at every later opener makes malformed
            # input quadratic. Stop and preserve the original text; the
            # caller's fail-open path is safer than speculative recovery.
            break
    return payloads


def _crush_json_items(payload: str, query: str, max_keep: int = 50) -> str | None:
    """Crush redundant array items in a JSON payload.

    Only arrays longer than max_keep and consisting entirely of objects
    are eligible. An eligible array is reduced to its query matches only
    if at least one item matches. Return None if rewriting does not help.
    """
    try:
        data = loads_for_rewrite(payload)
    except (ValueError, RecursionError):  # JSONDecodeError + the 4300-digit int limit
        return None

    # Find arrays to crush: top-level list, or dicts with list values
    # whose items are dicts (the "catalog" pattern).
    arrays_to_crush: list[list] = []
    pending = [data]
    while pending:
        obj = pending.pop()
        if isinstance(obj, list) and len(obj) > max_keep:
            if all(isinstance(item, dict) for item in obj):
                arrays_to_crush.append(obj)
        elif isinstance(obj, dict):
            pending.extend(reversed(obj.values()))

    if not arrays_to_crush:
        return None

    if not query_has_distinctive_selectors(query):
        return None
    query_terms = set(_json_query_needles(query))
    if not query_terms:
        return None
    query_selectors = _selector_patterns(query_terms)

    total_crushed = 0
    for arr in arrays_to_crush:
        kept_items = []
        for item in arr:
            try:
                item_str = json.dumps(item, ensure_ascii=False)
            except RecursionError:
                return None
            if any(selector.search(item_str) for selector in query_selectors):
                kept_items.append(item)
        if not kept_items or len(kept_items) == len(arr):
            continue

        total_crushed += len(arr) - len(kept_items)

        arr[:] = kept_items

    if total_crushed == 0:
        return None

    try:
        result = json.dumps(data, indent=2, ensure_ascii=False)
    except RecursionError:
        return None
    # Only use the crushed version if it's actually shorter
    if len(result) < len(payload):
        return result
    return None


def _preprocess_json(text: str, query: str) -> str:
    """Detect and crush JSON payloads in the text. 1.10.0 (S5): protected fact lines are restored
    verbatim — the crush may shorten them but may not delete them."""
    return _restore_fact_lines(text, _crush_embedded_json(text, query))


def _crush_embedded_json(text: str, query: str) -> str:
    """Find JSON spans, crush redundant array items, and splice the crushed versions back into the
    text. Falls back to the original text if no JSON is found or crushing doesn't help."""
    payloads = _detect_json_payloads(text)
    if not payloads:
        return text

    parts: list[str] = []
    cursor = 0
    for start, end, payload in payloads:
        crushed = _crush_json_items(payload, query)
        if crushed is not None:
            parts.extend((text[cursor:start], crushed))
            cursor = end

    if not parts:
        return text
    parts.append(text[cursor:])
    return "".join(parts)


def inspect_compressibility(text: str, query: str) -> dict[str, Any]:
    """Pre-compression check (PAKT-inspired): is compression worth running?

    Returns {"worth_it": bool, "repetition_ratio": float, "reason": str}.
    Cheap heuristics only — no compression is performed.
    """
    tokens = estimate_tokens(text)
    if tokens < 200:
        return {
            "worth_it": False,
            "repetition_ratio": 0.0,
            "guaranteed_savings_pct": 0.0,
            "ceiling_class": "n/a",
            "reason": f"too small ({tokens} tokens < 200)",
        }
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return {
            "worth_it": False,
            "repetition_ratio": 0.0,
            "guaranteed_savings_pct": 0.0,
            "ceiling_class": "n/a",
            "reason": "empty",
        }
    # Repetition ratio: fraction of duplicate lines (exact + normalised runs).
    from collections import Counter

    norm = [_DIGITS_RE.sub("#", ln) for ln in lines]
    counts = Counter(norm)
    dup_lines = sum(c for c in counts.values() if c > 1)
    repetition_ratio = dup_lines / len(lines)
    # Context-calibrated ceiling (Compactor): not every context compresses
    # the same. The guaranteed-safe bound is the surplus share of duplicated
    # normalised lines — bytes a dedupe pass removes with zero judgement.
    # Beyond it, savings depend on relevance selection, not redundancy.
    total_chars = sum(len(ln) + 1 for ln in lines)
    surplus_chars = sum((c - 1) * (len(ln) + 1) for ln, c in counts.items() if c > 1)
    guaranteed = surplus_chars / max(1, total_chars)
    ceiling_class = (
        "dedupe-heavy" if guaranteed >= 0.40
        else "moderate" if guaranteed >= 0.15
        else "sparse"
    )
    # Distinct-line ratio as a secondary signal: highly unique prose with no
    # query hits rarely compresses extractively without damage.
    worth = repetition_ratio >= 0.3 or tokens >= 5000
    return {
        "worth_it": worth,
        "repetition_ratio": round(repetition_ratio, 3),
        "guaranteed_savings_pct": round(guaranteed, 3),
        "ceiling_class": ceiling_class,
        "reason": (
            f"repetition {repetition_ratio:.0%}, {tokens} tokens"
            if worth
            else f"low repetition ({repetition_ratio:.0%}) and moderate size"
        ),
    }


# ---------------------------------------------------------------------------
# v1.4.0 public helpers: brief_context / extract_evidence_lines
#
# Deterministic, stdlib-only, query-optional "what is in here" views for hosts
# that need a small, honest stand-in for a big tool result (a plugin's last
# rung after the query-aware extract was rejected or too big). Both return
# ORIGINAL lines only — nothing is paraphrased — and both treat a level-tagged
# error as the most important thing in a log.
# ---------------------------------------------------------------------------

_WARN_LEVEL_RE = re.compile(r"\b(?:WARN|WARNING)\b")
_EVID_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)+\b")
_EVID_SHA_RE = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
_EVID_KV_RE = re.compile(r"\b[A-Za-z_][\w.-]{0,63}=\S")
_EVID_FILE_RE = re.compile(
    r"\b[\w-]{1,64}\.(?:py|js|ts|tsx|go|rs|java|c|h|cpp|json|ya?ml|toml|md|txt|log|sh|sql|cfg|ini)\b"
)
_EVIDENCE_LINE_CAP = 2000


def _query_hit_terms(query: str) -> list[str]:
    """Lowercase, deduplicated query terms worth searching lines for."""
    if not query or _is_filler_query(query):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for term in [
        t for t in distinctive_query_terms(query) if not t.startswith("script:")
    ] + _topic_terms(query):
        key = term.casefold()
        if key and key not in seen:
            seen.add(key)
            terms.append(key)
    return terms


def _rank_query_hits(
    candidates: Iterable[tuple[int, str]], terms: list[str]
) -> list[tuple[int, int]]:
    tests = [_term_test(term) for term in terms]
    ranked = []
    for i, line in candidates:
        low = line[:_RX_LINE_CAP].casefold()
        hits = sum(1 for test in tests if test(low))
        if hits:
            ranked.append((-hits, i))
    ranked.sort()
    return ranked


def _brief_scan(
    text: str, query: str
) -> tuple[tuple[str, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """The budget-independent part of :func:`brief_context`: the lines, the
    running count of non-blank lines, and the indices of the error, warning
    and query-hit exemplar lines (original order)."""
    lines = text.split("\n")
    nonblank = [0] * (len(lines) + 1)
    # Candidate lines by priority class (indices, original order).
    err_idx: list[int] = []
    warn_idx: list[int] = []
    seen_err: set[str] = set()
    seen_warn: set[str] = set()
    for i, line in enumerate(lines):
        has_text = bool(line.strip())
        nonblank[i + 1] = nonblank[i] + has_text
        if not has_text:
            continue
        if _is_error_line(line):
            fp = _error_fp(line)
            if fp not in seen_err:
                seen_err.add(fp)
                err_idx.append(i)
        elif _WARN_LEVEL_RE.search(line[:_RX_LINE_CAP]):
            fp = _error_fp(line)
            if fp not in seen_warn:
                seen_warn.add(fp)
                warn_idx.append(i)
    hit_idx: list[int] = []
    terms = _query_hit_terms(query)
    if terms:
        ranked = _rank_query_hits(
            ((i, line) for i, line in enumerate(lines) if nonblank[i + 1] != nonblank[i]),
            terms,
        )
        seen_hit: set[str] = set()
        for _, i in ranked:
            fp = _error_fp(lines[i])
            if fp not in seen_hit:
                seen_hit.add(fp)
                hit_idx.append(i)
    return tuple(lines), tuple(nonblank), tuple(err_idx), tuple(warn_idx), tuple(hit_idx)


@functools.lru_cache(maxsize=_MEMO_ENTRIES)
def _brief_scan_cached(text: str, query: str):
    return _brief_scan(text, query)


def _brief_scan_memo(text: str, query: str):
    # Perf (v1.5.0): a host asks for the same output's brief at growing budgets;
    # the scan does not depend on the budget. Everything returned is a tuple.
    if (
        type(text) is str
        and type(query) is str
        and len(query) <= _MEMO_MAX_QUERY_CHARS
        and _MEMO_MIN_CHARS <= len(text) <= _MEMO_MAX_CHARS
    ):
        return _brief_scan_cached(text, query)
    return _brief_scan(text, query)


def brief_context(
    text: str,
    *,
    budget_chars: int = 1200,
    query: str = "",
    gap_marker: Callable[[int, int], str] | None = None,
) -> str:
    """Deterministic, query-independent structural brief of ``text`` (v1.4.0).

    Keeps ORIGINAL lines, in original order, within ``budget_chars`` (newlines
    and gap markers included):

    1. the first ``h`` lines;
    2. every error-fingerprint exemplar line (one per fingerprint, see
       :func:`error_fingerprints`);
    3. warning (WARN/WARNING) exemplars, one per template, if they fit;
    4. lines holding distinctive terms of ``query``, if one is given;
    5. the last ``t`` lines.

    Head and tail are given about 30% of the budget each and the rest goes to
    the exemplars; if the errors do not fit that way the head/tail shrink so
    they do, and whatever budget the exemplars leave over goes back to the
    head and tail. When the budget cannot hold everything, errors outrank
    query-term lines, which outrank warnings.

    Each omitted span is marked with ``gap_marker(omitted_chars, total_chars)``
    — or ``[… N chars omitted …]`` when it is ``None`` — and a span of blank
    lines only is not marked. ``gap_marker`` is called once per marker that is
    emitted, plus one probe with ``(total_chars, total_chars)`` that sizes the
    widest marker for the budget. A line is never cut, except one that is
    itself as long as the budget: it is truncated, with a marker. ``text`` is
    returned unchanged when it already fits. A ``gap_marker`` wrapped in
    :class:`InliningGapMarker` keeps a dropped span verbatim instead when its
    marker would not be shorter than the span (1.4.1).
    """
    text = text if isinstance(text, str) else str(text or "")
    budget = max(1, int(budget_chars))
    if len(text) <= budget:
        return text
    # v1.4.0 (E11): JSON arrays of objects get a valid-JSON brief, not a
    # line-cut that would leave unparseable fragments.
    if text.lstrip()[:1] in ("[", "{"):
        briefed = json_brief(text, budget_chars=budget, query=query)
        if briefed is not None:
            return briefed
    total = len(text)
    lines, nonblank, err_idx, warn_idx, hit_idx = _brief_scan_memo(text, query)
    n = len(lines)

    def mark(omitted: int) -> str:
        if gap_marker is not None:
            made = call_gap_marker(gap_marker, omitted, total, "lines")
            return str(made) if made else ""
        return f"[… {omitted} chars omitted …]"

    # Markers are sized at the widest count a span can have: ONE probe call,
    # gap_marker(total, total), before any real span is known. (Every later call
    # is for a span that is actually emitted.)
    marker_len = len(mark(total))

    eff_cache: dict[int, str] = {}

    def eff(i: int) -> str:
        cached = eff_cache.get(i)
        if cached is None:
            line = lines[i]
            if len(line) + 1 >= budget:
                cut = max(1, budget // 3)
                line = line[:cut] + mark(len(lines[i]) - cut)
            eff_cache[i] = cached = line
        return cached

    def has_content(lo: int, hi: int) -> int:
        return 1 if nonblank[hi] - nonblank[lo] > 0 else 0

    def build(head_cap: int, tail_cap: int, errors_first: bool) -> tuple[list[int], bool]:
        sel: list[int] = []
        chosen_set: set[int] = set()
        state = {"raw": 0, "gaps": 0}

        def gap_delta(p: int | None, q: int | None, i: int) -> int:
            lo = 0 if p is None else p + 1
            hi = n if q is None else q
            previous = 0 if p is None and q is None else has_content(lo, hi)
            return has_content(lo, i) + has_content(i + 1, hi) - previous

        def try_add(i: int) -> bool:
            if i in chosen_set:
                return True
            pos = bisect.bisect_left(sel, i)
            p = sel[pos - 1] if pos > 0 else None
            q = sel[pos] if pos < len(sel) else None
            raw = state["raw"] + len(eff(i)) + 1
            gaps = state["gaps"] + gap_delta(p, q, i)
            if raw - 1 + gaps * (marker_len + 1) > budget:
                return False
            sel.insert(pos, i)
            chosen_set.add(i)
            state["raw"], state["gaps"] = raw, gaps
            return True

        def add_head() -> None:
            used = 0
            for i in range(n):
                if not has_content(i, i + 1):
                    continue
                c = len(eff(i)) + 1
                if i > 0 and used + c > head_cap:
                    break
                if not try_add(i):
                    break
                used += c

        def add_tail() -> None:
            used = 0
            for i in range(n - 1, -1, -1):
                if i in chosen_set and used:  # met the head
                    break
                if not has_content(i, i + 1):
                    continue
                c = len(eff(i)) + 1
                if used + c > tail_cap:
                    break
                if not try_add(i):
                    break
                used += c

        def add_exemplars() -> bool:
            all_errors = True
            for i in err_idx:
                if not try_add(i):
                    all_errors = False
            # When the budget cannot hold everything, lines that answer the
            # caller's query outrank warning exemplars.
            for group in (hit_idx, warn_idx):
                for i in group:
                    try_add(i)
            return all_errors

        def fill_edges() -> None:
            """Spend what is left on more head and tail, alternately."""
            hi, ti = 0, n - 1
            head_open = tail_open = True
            while (head_open or tail_open) and hi <= ti:
                if head_open:
                    while hi < n and (hi in chosen_set or not has_content(hi, hi + 1)):
                        hi += 1
                    if hi >= n or not try_add(hi):
                        head_open = False
                if tail_open:
                    while ti >= 0 and (ti in chosen_set or not has_content(ti, ti + 1)):
                        ti -= 1
                    if ti < 0 or not try_add(ti):
                        tail_open = False

        if errors_first:
            all_errors = add_exemplars()
            add_head()
            add_tail()
        else:
            add_head()
            add_tail()
            all_errors = add_exemplars()
        fill_edges()
        return sel, all_errors

    chosen: list[int] = []
    for share, errors_first in ((0.30, False), (0.15, False), (0.0, True)):
        cap = int(budget * share)
        chosen, all_errors = build(cap, cap, errors_first)
        if all_errors:
            break

    # 1.4.1 (fix-all): an InliningGapMarker gets the dropped lines verbatim
    # when its marker would not be shorter than them, as in compress_context.
    inline_short = _inlines_short(gap_marker)

    def gap_parts(lo: int, hi: int) -> list[str]:
        if not has_content(lo, hi):
            return []
        span_chars = _span_chars(lines, lo, hi)
        made = mark(span_chars)
        if not made:
            return []
        if inline_short and len(made) >= span_chars:
            return lines[lo:hi]
        return [made]

    parts: list[str] = []
    prev = -1
    for i in chosen:
        lo = prev + 1
        if lo < i:
            parts.extend(gap_parts(lo, i))
        parts.append(eff(i))
        prev = i
    if chosen and prev < n - 1:
        parts.extend(gap_parts(prev + 1, n))
    out = "\n".join(parts)
    if not out:
        # Not even one line (with its marker) fits a budget this small: the
        # plain prefix is the only honest brief left.
        return text[:budget]
    if len(out) > budget:  # only a gap_marker that outgrew its probe can get here
        out = out[:budget]
    return out


def extract_evidence_lines(text: str, query: str = "", limit: int = 20) -> list[str]:
    """Exact original lines most likely to matter, deduplicated, capped (v1.4.0).

    Ranking, most important first:

    1. error exemplars — one line per :func:`error_fingerprints` fingerprint;
    2. lines holding terms of ``query`` (more distinct terms first);
    3. identifier-dense lines — at least two of: file paths, versions, SHAs,
       ``key=value`` pairs.

    Lines are returned unmodified, in original order, at most ``limit`` of
    them. Lines that differ only in volatile fields (ids, numbers, timestamps)
    count as duplicates, so a thousand repeats cannot fill the list. Blank
    lines are never returned. Deterministic.
    """
    if not text or limit <= 0:
        return []
    lines = _norm_newlines(text).split("\n")
    picked: set[int] = set()
    seen_tpl: set[str] = set()

    def take(i: int) -> bool:
        fp = _error_fp(lines[i])
        if fp not in seen_tpl and i not in picked:
            seen_tpl.add(fp)
            picked.add(i)
        return len(picked) >= limit

    for i, line in enumerate(lines):
        if line.strip() and _is_error_line(line):
            if take(i):
                return [lines[j] for j in sorted(picked)]
    terms = _query_hit_terms(query)
    if terms and len(picked) < limit:
        ranked = _rank_query_hits(
            ((i, line) for i, line in enumerate(lines) if i not in picked and line.strip()),
            terms,
        )
        for _, i in ranked:
            if take(i):
                return [lines[j] for j in sorted(picked)]
    if len(picked) < limit:
        dense = []
        for i, line in enumerate(lines):
            if not line.strip() or i in picked or len(line) > _EVIDENCE_LINE_CAP:
                continue
            score = (
                len(_PATH_RE.findall(line))
                + len(_EVID_FILE_RE.findall(line))
                + len(_EVID_VERSION_RE.findall(line))
                + len(_EVID_SHA_RE.findall(line))
                + len(_EVID_KV_RE.findall(line))
            )
            if score >= 2:
                dense.append((-score, i))
        for _, i in sorted(dense):
            if take(i):
                break
    return [lines[i] for i in sorted(picked)]


_ANCHOR_REGION_BEFORE = 8
_ANCHOR_REGION_AFTER = 12

_GO_STACK_LINE_RE = re.compile(
    r"^(?:goroutine \d+ \[[^\]]*\]:"
    r"|\[signal [^\]]*\]"
    r"|created by \S+.*"
    r"|[\w.\-/]+(?:\.\(\*?\w+\))?(?:\.\w+)?\(.*\))$"
)
_ANCHOR_GO_TAIL_LINES = 2  # the last frame (function line + its file:line) of a Go stack longer than the region


# Log-record prefix: ISO-ish timestamp, level word, optional [thread], optional
# logger token followed by " - " or ": ". The level word is captured (group 1)
# so it can be kept when the rest of the prefix is stripped from an anchor line.
# WARNING is listed before WARN so "WARNING" is not truncated to "WARN".
_ANCHOR_LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:?\d\d)?"
    r"\s+(EMERGENCY|CRITICAL|WARNING|VERBOSE|SEVERE|NOTICE|FINEST|FINER|EMERG|ALERT|TRACE|DEBUG|ERROR|FATAL|WARN|INFO|CRIT|FINE|ERR)\b"
    r"(?:\s*\[[^\]]+\])?"
    r"(?:\s+[A-Za-z0-9_.$]+\s*(?:-\s+|:\s+))?"
)


_ANCHOR_JVM_LINE_RE = re.compile(r"\((\w[\w$]*\.(?:java|kt|scala|groovy|clj)):\d+\)")
_ANCHOR_JS_FRAME_RE = re.compile(r"\((node:[\w/]+|[\w./@\\-]*node_modules/[\w./@\\-]*\.(?:js|mjs|cjs|ts|tsx|jsx|mts|cts)):\d+(?::\d+)?\)")
_ANCHOR_JS_BARE_FRAME_RE = re.compile(r"^(\s*at\s+)(node:[\w/]+|[\w./@\\-]*node_modules/[\w./@\\-]*\.(?:js|mjs|cjs|ts|tsx|jsx|mts|cts)):\d+(?::\d+)?\s*$")
_ANCHOR_LOGFMT_PAIR_RE = re.compile(r'(\w[\w.]*)=("(?:[^"\\]|\\.)*"|\S+)')


def _rare_anchor_extras(line: str, lines: list[str]) -> list[str]:
    stripped = line.strip()
    current = next((i for i, other in enumerate(lines) if other.strip() == stripped), -1)

    def unique(marker: str) -> bool:
        return not any(i != current and marker in other for i, other in enumerate(lines))

    extras: list[str] = []

    if stripped.startswith("{"):
        try:
            obj = loads_for_rewrite(stripped)
        except ValueError:
            obj = None

        if isinstance(obj, dict):
            for key, value in obj.items():
                if unique(f'"{key}"'):
                    extras.append(f"{key}={value}")
                if len(extras) >= 4:
                    break
            return extras

    pairs = _ANCHOR_LOGFMT_PAIR_RE.findall(stripped)
    if len(pairs) >= 3:
        for key, value in pairs:
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            if unique(f"{key}="):
                extras.append(f"{key}={value}")
            if len(extras) >= 4:
                break

    return extras

class _StructuredAnchorDepthFailure(Exception):
    pass


_STRUCTURED_ANCHOR_ACTIVE = contextvars.ContextVar("tameru_structured_anchor_active", default=False)


def _structured_anchor_depth_noop_result(text, mode):
    return dataclasses.replace(
        _recursion_noop_result(caller_text=text, requested_mode=mode),
        policy_name="local-noop-anchor-depth", compression_risk="high", confidence=0.0,
        reasons=["structured anchor depth limit"],
    )


def _strip_structured_anchor(line):
    try:
        return _strip_structured_anchor_record(line)
    except (RecursionError, OverflowError) as exc:
        if _STRUCTURED_ANCHOR_ACTIVE.get():
            raise _StructuredAnchorDepthFailure from exc
        return line


def _strip_structured_anchor_record(line):
    if line.lstrip().startswith("{"):
        try:
            record = loads_for_rewrite(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            level = None
            for key in ("level", "lvl", "severity"):
                value = record.get(key)
                if isinstance(value, str) and value:
                    level = value
                    break
            parts = []
            for key in ("msg", "message", "error", "err", "reason", "exception", "status", "code"):
                if key in record:
                    value = str(record[key])
                    if value:
                        parts.append(value)
            if level is not None and parts:
                return " ".join([level.upper()] + parts)
            return None
    pairs = _ANCHOR_LOGFMT_PAIR_RE.findall(line)
    if len(pairs) >= 3:
        fields = {}
        for key, value in pairs:
            if key not in fields:
                if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                fields[key] = value
        level = None
        for key in ("level", "lvl", "severity"):
            if key in fields:
                level = fields[key]
                break
        parts = []
        for key in ("msg", "message", "error", "err", "reason", "exception", "status", "code"):
            value = fields.get(key)
            if value:
                parts.append(value)
        if level is not None and parts:
            return " ".join([level.upper()] + parts)
    return None


_ANCHOR_ACCESS_LOG_RE = re.compile(
    r'^\S+ \S+ \S+ \[[^\]]*\] '
    r'"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) '
    r'(?P<path>[^\s?]+)(?:\?[^\s]*)? HTTP/\d+(?:\.\d+)?" '
    r'(?P<status>\d{3})(?=\s|$)'
)


_PHP_LOG_PREFIX_RE = re.compile(r"^\[\d{1,2}-[A-Z][a-z]{2}-\d{4} \d\d:\d\d:\d\d(?: [A-Za-z_/+-]+)?\]\s+(?:PHP\s+)?")
_NGINX_ERR_PREFIX_RE = re.compile(r"^20\d\d/\d\d/\d\d \d\d:\d\d:\d\d \[([a-z]+)\] \d+#\d+: (?:\*\d+ )?")
_MYSQL_ERR_PREFIX_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)? \d+ \[(System|Warning|Note|ERROR|Error)\] (?:\[MY-\d+\] )?(?:\[\w+\] )?")
_HAPROXY_HTTP_RE = re.compile(r'^\S+:\d+ \[\d\d/[A-Z][a-z]{2}/\d{4}:\d\d:\d\d:\d\d(?:\.\d+)?\] \S+ (\S+/\S+) -?\d+/-?\d+/-?\d+/-?\d+/\+?-?\d+ (\d{3}) \+?\d+ \S+ \S+ (\S{4}) ')
_APACHE_ERR_PREFIX_RE = re.compile(r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d(?:\.\d+)? \d{4}\] \[(?:[\w-]+:)?([a-z]+\d?)\](?: \[pid \d+(?::tid \d+)?\])?(?: \[client [^\]]+\])? ")
_PHP_BARE_PREFIX_RE = re.compile(r"^PHP\s+(?=(?:Fatal error|Parse error|Warning|Notice|Deprecated|Catchable fatal error):)")
_PHP_STACK_FRAME_RE = re.compile(r"^#\d+ ")


def _strip_anchor_prefix(line: str) -> str:
    """Drop the log-record prefix from an anchor line, keeping the level word.

    ``"2026-10-18 11:59:00.001 ERROR [t] o.e.billing.Api - request failed"``
    becomes ``"ERROR request failed"`` so the anchored query no longer carries
    the thread/logger/timestamp entities that appear on every INFO line.
    JVM frame line numbers are rewritten to the file name so anchors do not carry bare numbers.
    Syslog, ISO-8601, and kernel timestamp prefixes are removed when a message remains.
    Returns the line unchanged when it is not a log record, or when stripping
    would leave no message (e.g. a bare ``"… ERROR"`` line).
    """
    m = _ANCHOR_ACCESS_LOG_RE.match(line)
    if m is not None:
        return f"{m.group('method')} {m.group('path')} {m.group('status')}"
    syslog_m = _SYSLOG_PREFIX_RE.match(line)
    if syslog_m is not None:
        syslog_remainder = line[syslog_m.end():]
        if syslog_remainder.strip():
            line = syslog_remainder
    php_m = _PHP_LOG_PREFIX_RE.match(line)
    if php_m is not None:
        php_remainder = line[php_m.end():]
        if php_remainder.strip():
            line = php_remainder
    php_bare_m = _PHP_BARE_PREFIX_RE.match(line)
    if php_bare_m is not None:
        php_bare_remainder = line[php_bare_m.end():]
        if php_bare_remainder.strip():
            line = php_bare_remainder

    nginx_err_m = _NGINX_ERR_PREFIX_RE.match(line)
    if nginx_err_m is not None:
        nginx_err_remainder = line[nginx_err_m.end():]
        if nginx_err_remainder.strip():
            line = nginx_err_m.group(1) + " " + nginx_err_remainder

    apache_err_m = _APACHE_ERR_PREFIX_RE.match(line)
    if apache_err_m is not None:
        apache_err_remainder = line[apache_err_m.end():]
        if apache_err_remainder.strip():
            line = apache_err_m.group(1) + " " + apache_err_remainder
    mysql_err_m = _MYSQL_ERR_PREFIX_RE.match(line)
    if mysql_err_m is not None:
        mysql_err_remainder = line[mysql_err_m.end():]
        if mysql_err_remainder.strip():
            line = mysql_err_m.group(1).upper() + " " + mysql_err_remainder
    redis_m = _REDIS_LINE_RE.match(line)
    if redis_m:
        remainder = line[redis_m.end():].strip()
        if remainder:
            line = ("WARNING " if redis_m.group(1) == "#" else "") + remainder
    m = _HAPROXY_HTTP_RE.match(line)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    stripped = _strip_structured_anchor(line)
    if stripped == line:
        return line
    if stripped is not None:
        line = stripped
    m = _ANCHOR_LOG_PREFIX_RE.match(line)
    if m is not None:
        out = _ANCHOR_LOG_PREFIX_RE.sub(r"\1 ", line, count=1).strip()
        if out != m.group(1):
            line = out
    line = _ANCHOR_JVM_LINE_RE.sub(r"(\1)", line)
    line = _ANCHOR_JS_FRAME_RE.sub(r"(\1)", line)
    return _ANCHOR_JS_BARE_FRAME_RE.sub(r"\1\2", line)


# Weak failure anchors: a fallback for the no-query error-anchored objective when a log carries
# its only failure as a non-ERROR line. A cheap literal prefilter lets ~99% of lines skip the rest
# (perf: must not slow the 9000-line INFO log bench).
_WEAK_LINE_HINT_RE = re.compile(
    r"WARN|warn|Failed|exited with|status=|code=|HTTP/"
)
_WEAK_STRUCT_LEVEL_RE = re.compile(
    r"(?i)\b(?:level|lvl|severity)\s*[\"']?\s*[=:]\s*[\"']?(?:warn|warning)\b"
)
_WEAK_FAILURE_WORD_RE = re.compile(
    r"\b(?:failed|failure|failing|fails|timeout|timed\s+out|refused|denied|"
    r"unreachable|rejected|aborted|unavailable|unauthorized|forbidden|crashed|"
    r"exhausted|could\s+not|unable\s+to)\b",
    re.IGNORECASE,
)
_WEAK_FAILED_TO_RE = re.compile(r"[fF]ailed to [a-z]")
_WEAK_EXITED_RE = re.compile(r"[eE]xited with (?:code|status) [1-9]\d*\b")
_WEAK_STATUS_RE = re.compile(r"[sS]tatus=[1-9]\d*/")
_WEAK_CODE_RE = re.compile(r"[cC]ode=(?:killed|dumped)")
_WEAK_HTTP_5XX_RE = re.compile(r'HTTP/\d(?:\.\d)?"\s5\d\d\s\d+')
_WEAK_EXCLUDE_RE = re.compile(
    r"succeeded|recovered|resolved|no longer|0 failed|without fail",
    re.IGNORECASE,
)


def _is_weak_failure_line(line: str) -> bool:
    """Weak failure anchor: a non-error line that still signals a failure, used only as a fallback
    inside ``_anchor_regions`` when there are no error-fingerprint exemplars. True when the line
    (after ``_without_zero_counts``) has a warning level token AND a failure word, or a level-less
    strong failure shape (systemd ``Failed to``/``status=N/``, ``exited with code/status N``,
    ``code=killed|dumped``, or an HTTP access-log 5xx status), and is not excluded by a
    recovery/zero-count phrase."""
    line = line[:_RX_LINE_CAP]
    if "PHP Warning:" in line:
        line = _without_zero_counts(line)
        return not _WEAK_EXCLUDE_RE.search(line)
    if not _WEAK_LINE_HINT_RE.search(line):
        return False
    line = _without_zero_counts(line)
    if _WEAK_EXCLUDE_RE.search(line):
        return False
    if (
        _WARN_LEVEL_RE.search(line) or _WEAK_STRUCT_LEVEL_RE.search(line)
    ) and _WEAK_FAILURE_WORD_RE.search(line):
        return True
    return bool(
        _WEAK_FAILED_TO_RE.search(line)
        or _WEAK_EXITED_RE.search(line)
        or _WEAK_STATUS_RE.search(line)
        or _WEAK_CODE_RE.search(line)
        or _WEAK_HTTP_5XX_RE.search(line)
    )


_ISO_LEVEL_TOKEN_RE = re.compile(r"\b(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING)\b")
_ISO_STRUCT_LEVEL_RE = re.compile(r"(?i)(?:\blevel\s*=|\"level\"\s*:\s*\"?)(?:trace|debug|info|notice|warn|warning)\b")
_ISO_STRUCT_WARN_RE = re.compile(r"(?i)(?:\blevel\s*=|\"level\"\s*:\s*\"?)warn(?:ing)?\b")


def _isolated_warn_lines(lines: list[str], max_regions: int) -> list[str]:
    """Last-resort anchors: isolated WARN lines in a mostly leveled log.

    Returns at most ``max_regions`` WARN lines in original order when all strict guards pass:
    at least 20 non-blank lines, at least 90% of non-blank lines carry a level token, at most
    two WARN-level lines and at most 5% of non-blank lines, and each chosen WARN fingerprint
    occurs only once among all non-blank lines.
    """
    if max_regions <= 0:
        return []

    def _redis_warn(line: str) -> bool:
        m = _REDIS_LINE_RE.match(line)
        return bool(m and m.group(1) == "#")

    if not any(
        "WARN" in line or "warn" in line.lower() or _redis_warn(line)
        for line in lines
    ):
        return []
    nonblank = [line for line in lines if line.strip()]
    if len(nonblank) < 20:
        return []

    level_count = 0
    warn_lines: list[str] = []
    for line in nonblank:
        if _ISO_LEVEL_TOKEN_RE.search(line) or _ISO_STRUCT_LEVEL_RE.search(line) or _REDIS_LINE_RE.match(line):
            level_count += 1
        if _WARN_LEVEL_RE.search(line) or _ISO_STRUCT_WARN_RE.search(line) or _redis_warn(line):
            warn_lines.append(line)

    if level_count * 100 < len(nonblank) * 90:
        return []
    if len(warn_lines) > 2 or len(warn_lines) * 100 > len(nonblank) * 5:
        return []
    if not warn_lines:
        return []

    fp_counts: dict[str, int] = {}
    for line in nonblank:
        fp = _error_fp(line.strip())
        fp_counts[fp] = fp_counts.get(fp, 0) + 1

    out: list[str] = []
    for line in warn_lines:
        if fp_counts.get(_error_fp(line.strip()), 0) != 1:
            return []
        out.append(line)
        if len(out) >= max_regions:
            break
    return out


_STATE_CHANGE_PREFILTER = (
    "marked",
    "is now",
    "became",
    "went",
    "transition",
    "changed",
    "set to",
    "state",
    "->",
    "circuit",
    "fail",
    "promot",
    "leader",
    "primary",
    "evict",
    "cordon",
    "drain",
    "recover",
    "online",
    "restored",
)
_STATE_CHANGE_RE = re.compile(
    r"\b(?:marked|is now|became|went|transitioned to|changed to|set to)\s+(?:down|degraded|unhealthy|unavailable|offline|read-only|readonly|not ?ready|unreachable|suspended|quarantined)\b"
    r"|\bstate changed\b"
    r"|\b(?:CLOSED|OPEN|HALF_OPEN|HALF-OPEN)\s*->\s*(?:CLOSED|OPEN|HALF_OPEN|HALF-OPEN)\b"
    r"|\bcircuit\b[^\n]{0,60}\b(?:opened|open|half-open|tripped|closed again)\b"
    r"|\bfail\s?over\s+(?:started|initiated|triggered|completed|in progress)\b"
    r"|\bpromot(?:ing|ed)\b[^\n]{0,40}\b(?:leader|primary|master)\b"
    r"|\b(?:leader|primary)\s+(?:changed|lost|elected)\b"
    r"|\b(?:evicted|cordoned|drained)\b"
    r"|\b(?:recovered|back online|restored)\b",
    re.IGNORECASE,
)


_STATE_SUMMARY_RE = re.compile(
    r"\b(\d+\s*/\s*\d+)\s+(?:services?\s+|nodes?\s+|pods?\s+|checks?\s+|targets?\s+)?(?:degraded|down|unhealthy|failed|failing|not\s+ready|unavailable|offline|unreachable|critical)\b"
    r"|\b(\d+\s+(?:of|out of)\s+\d+)\s+(?:services?\s+|nodes?\s+|pods?\s+|checks?\s+|targets?\s+)?(?:are\s+|is\s+)?(?:degraded|down|unhealthy|failed|failing|not\s+ready|unavailable|offline|unreachable|critical)\b",
    re.IGNORECASE,
)


def _summary_anchor_region(line: str) -> str | None:

    """Region text for a summary-tier exemplar: the summary line without timestamp/level.

    Returns ``None`` when the result is empty.
    """
    s = _strip_anchor_prefix(line.strip())
    s = re.sub(r"^\s*(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING)\b\s*", "", s, flags=re.IGNORECASE)
    s = " ".join(s.split())
    return s or None


def _state_summary_lines(lines: list[str], max_regions: int) -> list[str]:
    """Last-resort anchors: dashboard summary-count lines.

    Returns at most ``max_regions`` matching lines in original order when all strict guards pass:
    at least 20 non-blank lines, one or two matching lines, a positive numerator,
    each chosen line's error fingerprint occurs only once among all lines, and each
    chosen line's summary region is non-empty and not too common in the text.
    """
    if max_regions <= 0:
        return []

    nonblank = [line for line in lines if line.strip()]
    if len(nonblank) < 20:
        return []

    matches: list[str] = []
    for line in nonblank:
        low = line.lower()
        if "/" not in low and " of " not in low:
            continue

        matched = False
        for m in _STATE_SUMMARY_RE.finditer(line):
            numerator = int(re.match(r"\d+", line[m.start():]).group())
            if numerator > 0:
                matched = True
                break
        if matched:
            matches.append(line)

    if not matches or len(matches) > 2:
        return []

    for line in matches:
        if _summary_anchor_region(line) is None:
            return []

    fp_counts: dict[str, int] = {}
    for line in lines:
        fp = _error_fp(line.strip())
        fp_counts[fp] = fp_counts.get(fp, 0) + 1

    out: list[str] = []
    for line in matches:
        if fp_counts.get(_error_fp(line.strip()), 0) != 1:
            return []
        out.append(line)
        if len(out) >= max_regions:
            break
    return out


def _state_change_lines(lines: list[str], max_regions: int) -> list[str]:
    """Last-resort anchors: rare INFO/NOTICE state-change lines.

    Returns at most ``max_regions`` matching lines in original order when all strict guards pass:
    at least 20 non-blank lines, at most two matching lines and at most 5% of non-blank lines,
    and each chosen line's error fingerprint occurs only once among all lines.

    If the state-change tier declines, falls back to dashboard summary-count anchors.
    """
    if max_regions <= 0:
        return []

    nonblank = [line for line in lines if line.strip()]
    if len(nonblank) < 20:
        return []

    matches: list[str] = []
    match_limit = min(2, len(nonblank) // 20)
    for line in nonblank:
        low = line.lower()
        if not any(token in low for token in _STATE_CHANGE_PREFILTER):
            continue
        if _STATE_CHANGE_RE.search(line):
            matches.append(line)
            if len(matches) > match_limit:
                return _state_summary_lines(lines, max_regions)

    if not matches:
        return _state_summary_lines(lines, max_regions)

    chosen = matches[:max_regions]
    fp_counts = dict.fromkeys((_error_fp(line.strip()) for line in chosen), 0)
    for line in lines:
        fp = _error_fp(line.strip())
        if fp in fp_counts:
            if fp_counts[fp]:
                return _state_summary_lines(lines, max_regions)
            fp_counts[fp] += 1
    return chosen


def _rare_template_lines(lines: list[str], max_regions: int) -> list[str]:
    """Last-resort anchors: one or two lines whose template is unique in an otherwise uniform log.

    Guards:
    - max_regions > 0
    - at least 30 non-blank lines (15 for the syslog-shaped path)
    - at least 90% of non-blank lines carry a level token, or at least 90% match _SYSLOG_PREFIX_RE
    - dominant templates: count >= 5 for leveled path, >= 3 for syslog-shaped path
    """
    if max_regions <= 0:
        return []

    nonblank = [line for line in lines if line.strip()]
    if len(nonblank) < 15:
        return []

    leveled = sum(
        1
        for line in nonblank
        if _ISO_LEVEL_TOKEN_RE.search(line) or _ISO_STRUCT_LEVEL_RE.search(line)
    )
    if leveled * 10 < len(nonblank) * 9:
        syslog_shaped = sum(
            1
            for line in nonblank
            if _SYSLOG_PREFIX_RE.match(line.strip())
        )
        if syslog_shaped * 10 < len(nonblank) * 9:
            return []
        min_count = 3
    else:
        if len(nonblank) < 30:
            return []
        min_count = 5

    counts: dict[str, int] = {}
    first_lines: dict[str, str] = {}
    for line in nonblank:
        fp = _error_fp(line.strip())
        counts[fp] = counts.get(fp, 0) + 1
        if fp not in first_lines:
            first_lines[fp] = line

    dominant = [fp for fp, count in counts.items() if count >= min_count]
    if not 1 <= len(dominant) <= 3:
        return []

    dominant_cover = sum(counts[fp] for fp in dominant)
    if dominant_cover * 10 < len(nonblank) * 9:
        return []

    rare = [first_lines[fp] for fp, count in counts.items() if count == 1]
    if not 1 <= len(rare) <= 2:
        return []

    dominant_words: set[str] = set()
    for fp in dominant:
        dominant_words.update(re.findall(r"[A-Za-z]{4,}", first_lines[fp].lower()))

    for line in rare:
        words = set(re.findall(r"[A-Za-z]{4,}", line.lower()))
        if not words - dominant_words:
            return []

    return rare[:max_regions]


def _anchor_regions(text: str, max_regions: int) -> list[str]:
    token = _STRUCTURED_ANCHOR_ACTIVE.set(True)
    try:
        return _structured_anchor_regions(text, max_regions)
    except (RecursionError, OverflowError) as exc:
        raise _StructuredAnchorDepthFailure from exc
    finally:
        _STRUCTURED_ANCHOR_ACTIVE.reset(token)


def _structured_anchor_regions(text: str, max_regions: int) -> list[str]:
    """Error regions for the error-anchored objective: for each of the first ``max_regions`` error
    fingerprint exemplars, the exemplar line plus the contiguous frame-like lines around it (up to
    ``_ANCHOR_REGION_BEFORE`` before and ``_ANCHOR_REGION_AFTER`` after). A neighbour line is frame-like
    when it is non-blank and either starts with whitespace, starts with "Caused by" or "Traceback", or is
    itself an error/diagnostic line (``_is_error_line``). Each line is stripped and capped at
    ``_ANCHOR_LINE_CHARS``; a region is the lines joined with "\n". A neighbour whose masked shape equals the next line further out (a repetitive run such as PASS rows) is context noise, not a frame."""
    lines = _norm_newlines(text).split("\n")
    summary_exemplars: set[str] = set()
    rare_exemplars: set[str] = set()
    exemplars = set(error_fingerprints(text).values())
    if not exemplars:
        # No error-fingerprint exemplars: fall back to weak failure anchors. Keep the first line
        # per fingerprint, at most ``max_regions``; the region loop below is reused unchanged.
        weak: set[str] = set()
        seen_fp: set[str] = set()
        for line in lines:
            if len(weak) >= max_regions:
                break
            if _is_weak_failure_line(line):
                fp = _error_fp(line.strip())
                if fp not in seen_fp:
                    seen_fp.add(fp)
                    weak.add(line)
        exemplars = weak
    if not exemplars:
        # Last resort: isolated WARN anchors in a strictly leveled log.
        exemplars = set(_isolated_warn_lines(lines, max_regions))
        rare_exemplars = set(exemplars)
    if not exemplars:
        # Final fallback: rare state-change anchors in otherwise healthy logs.
        state_change = _state_change_lines(lines, max_regions)
        exemplars = set(state_change)
        # The summary tier is active only when the state-change tier declined, in
        # which case _state_change_lines returns the summary lines. Remember those
        # so their region text is the count phrase (e.g. "20/40"), not the whole
        # line — the state word in the line would otherwise anchor every
        # per-service "state=degraded" row and defeat the savings gate.
        summary_exemplars = set(state_change) & set(_state_summary_lines(lines, max_regions))
        rare_exemplars = set(state_change) - summary_exemplars
    if not exemplars:
        # Last resort: the one or two lines that break an otherwise uniform log.
        exemplars = set(_rare_template_lines(lines, max_regions))
        rare_exemplars = set(exemplars)
    # 1.10.0: injection-shaped (trust-risk) lines are never anchors, whatever tier found them.
    exemplars = {line for line in exemplars if not _is_trust_risk_line(line)}
    regions: list[str] = []
    seen_rows: set[int] = set()



    def frame_like(s: str) -> bool:
        if s.strip() and _GO_STACK_LINE_RE.match(s):
            return True
        if s.strip() == "Stack trace:":
            return True
        if _PHP_STACK_FRAME_RE.match(s):
            return True
        if s.lstrip().startswith("thrown in "):
            return True
        return bool(s.strip()) and (
            s[:1] in " \t"
            or s.lstrip().startswith(("Caused by", "Traceback"))
            or _is_error_line(s)
        )

    def repetitive(j: int, step: int, anchor_fp=None) -> bool:
        # lines[j] repeats the template of the next line further out (same masked
        # shape, e.g. a run of " PASS  x.test.ts (12 ms)" rows): context noise.
        # A candidate that repeats the anchor's fingerprint is a repeat of the
        # anchor, not frame context, so it also stops region growth.
        if anchor_fp is not None and _error_fp(lines[j].strip()) == anchor_fp:
            return True
        k = j + step
        if not (0 <= k < len(lines)):
            return False
        if _is_error_line(lines[j]) and not _is_error_line(lines[k]):
            return False
        return _error_fp(lines[j].strip()) == _error_fp(lines[k].strip())

    for i, line in enumerate(lines):
        if len(regions) >= max_regions:
            break
        if i in seen_rows or line not in exemplars:
            continue
        exemplars.discard(line)
        if line in summary_exemplars:
            # Summary-tier anchor: keep the summary line with timestamp and level
            # removed (e.g. "health: summary 20/40 degraded"), so the count phrase
            # remains available as the anchor region.
            region = _summary_anchor_region(line)
            seen_rows.add(i)
            if region:
                regions.append(region[:_ANCHOR_LINE_CHARS])
            continue
        if line in rare_exemplars:
            stripped = line.strip()
            base = _strip_anchor_prefix(stripped)
            extras = _rare_anchor_extras(stripped, lines)
            if stripped.startswith("{"):
                try:
                    obj = loads_for_rewrite(stripped)
                except ValueError:
                    obj = None

                if isinstance(obj, dict) and base == stripped:
                    level = str(obj.get("level", "")).upper()
                    region = " ".join([level, *extras]) if level else " ".join(extras)
                else:
                    region = " ".join([base, *extras])
            else:
                region = " ".join([base, *extras])
            seen_rows.add(i)
            if region:
                regions.append(region[:_ANCHOR_LINE_CHARS])
            continue
        lo = i
        anchor_fp = _error_fp(lines[i].strip())
        while lo > 0 and i - lo < _ANCHOR_REGION_BEFORE and frame_like(lines[lo - 1]) and not repetitive(lo - 1, -1, anchor_fp):
            lo -= 1
        hi = i
        while hi + 1 < len(lines) and hi - i < _ANCHOR_REGION_AFTER:
            nxt = hi + 1
            # bridge one blank line when a frame-like line follows it (assertion
            # detail after a blank, as jest/pytest/cargo print it)
            if not lines[nxt].strip() and nxt + 1 < len(lines) and lines[nxt + 1].strip():
                nxt += 1
            if not (frame_like(lines[nxt]) and not repetitive(nxt, 1, anchor_fp)):
                break
            hi = nxt
        if line.startswith("panic: "):
            nxt = hi + 1
            if nxt < len(lines):
                if not lines[nxt].strip() and nxt + 1 < len(lines) and lines[nxt + 1].strip():
                    nxt += 1
                if frame_like(lines[nxt]):
                    end = nxt
                    while end + 1 < len(lines):
                        cand = end + 1
                        if not lines[cand].strip() and cand + 1 < len(lines) and lines[cand + 1].strip():
                            cand += 1
                        if frame_like(lines[cand]):
                            end = cand
                        else:
                            break
                    start = max(hi + 1, end - _ANCHOR_GO_TAIL_LINES + 1)
                    tail = [j for j in range(start, end + 1) if lines[j].strip()]
                    rows = list(range(lo, hi + 1)) + tail
                    seen_rows.update(rows)
                    regions.append(
                        "\n".join(_strip_anchor_prefix(lines[j].strip())[:_ANCHOR_LINE_CHARS] for j in rows
                                  if lines[j].strip() and not _is_trust_risk_line(lines[j]))
                    )
                    continue
        seen_rows.update(range(lo, hi + 1))
        regions.append(
            "\n".join(_strip_anchor_prefix(ln.strip())[:_ANCHOR_LINE_CHARS] for ln in lines[lo : hi + 1]
                      if ln.strip() and not _is_trust_risk_line(ln))
        )
    return regions


_ANCHOR_MAX_LINES = 8
_ANCHOR_LINE_CHARS = 200


# Small logs whose plain objective fails open still get one error-anchored retry
# probe; large logs never pay the second pass.
_ANCHOR_RETRY_MAX_CHARS = 20000


def _resolve_objective(
    *,
    ambiguity_fail_open,
    anchor_errors,
    budget_ratio,
    caller_text,
    ccr,
    ccr_dir,
    citations,
    content_hint,
    degraded_view,
    derive_query,
    gap_marker,
    inline_short_gaps,
    limits,
    min_savings_ratio,
    mode,
    pin_patterns,
    pin_recent,
    prose_brief,
    query,
    recursion_markers,
    reorder_best,
    semantic_tier,
    strategy,
):
    """Settle what the compression is steered by: the caller's words, a derived objective, or the regions around the errors.

    Returns ``(query, query_as_given, derived_terms, anchor_lines, chosen_probe)``. ``chosen_probe`` is the result of a
    side-effect-free trial run when the error-anchored objective had to be compared with the plain one (the caller may reuse
    it); otherwise None."""
    # v1.4.0 (E6): a reply made only of conversational filler ("continue",
    # "thanks", "go ahead", "fix it", "OK") is an EMPTY query on every path.
    # The receipt/cache wrapper still show the caller's words.
    query_as_given = query
    if _is_filler_query(query):
        query = ""
    # TPC-style derived objective (opt-in): an empty/generic query normally
    # fails open. With derive_query=True the engine first tries to infer a
    # conservative task descriptor from the document's own recurring rare
    # terms; when no stable term structure exists the original empty query
    # stands and the usual fail-open applies. Receipts mark derived
    # objectives via query_source/derived_terms and the risk floor is
    # medium — an inferred intent never earns a "low" rating.
    derived_terms: list[str] = []
    if (
        derive_query
        and not query_has_distinctive_selectors(query or "")
        and not _topic_terms(query or "")
    ):
        derived_terms = _derive_query_terms(caller_text)
        if derived_terms:
            query = " ".join(derived_terms)
    # v1.6.0 (multilang): error-anchored objective (opt-in). With no usable query, tool output that carries
    # errors/diagnostics is compressed around them: the error region of each fingerprint's first exemplar
    # (head line plus adjacent frame lines, up to _ANCHOR_MAX_LINES regions) becomes the query. Receipts mark it
    # query_source="error-anchored"; the risk floor is medium, like a derived objective.
    # A generic query with no informative topic word (absent, or on >80% of lines) also gets the error regions,
    # appended after the caller's words when a side-effect-free probe shows that keeps every error fingerprint in less text.
    anchor_lines: list[str] = []
    chosen_probe = None
    if (
        anchor_errors
        and not derived_terms
        and not query_has_distinctive_selectors(query or "")
    ):
        topic = _topic_terms(query or "")
        if topic:
            # A generic query whose topic words are absent from the text or on
            # nearly every line carries no signal: anchor on the errors too,
            # keeping the caller's words in front.
            originals = [ln for ln in caller_text.split("\n", 4000)[:4000] if ln.strip()]
            sample = [ln.casefold() for ln in originals]
            tests = [_term_test(t.casefold()) for t in topic]
            uninformative = bool(sample) and all(
                (hits := sum(1 for ln in sample if test(ln))) == 0 or hits > 0.8 * len(sample)
                for test in tests
            )
            # A small erroring log is worth the same side-effect-free anchored
            # probe as an uninformative query; large logs never pay the second pass.
            small_erroring_log = (
                not uninformative
                and len(caller_text) <= _ANCHOR_RETRY_MAX_CHARS
                and bool(error_fingerprints(caller_text))
            )
            rare_topic_lines = []
            if (
                not uninformative
                and not small_erroring_log
                and len(sample) >= 20
                and len(caller_text) <= _ANCHOR_RETRY_MAX_CHARS
                and route_content_type(caller_text.split("\n", 50)[:50]) == "log"
            ):
                rare_hits = []
                seen_rare_lines = set()
                rare_hit_limit = max(2, len(sample) // 50)
                for test in tests:
                    hit_idx = [k for k, ln in enumerate(sample) if test(ln)]
                    if 1 <= len(hit_idx) <= rare_hit_limit:
                        for k in hit_idx:
                            line = originals[k]
                            if line not in seen_rare_lines and not _is_trust_risk_line(line):
                                seen_rare_lines.add(line)
                                rare_hits.append(line)
                if rare_hits and len(rare_hits) <= _ANCHOR_MAX_LINES:
                    rare_topic_lines = rare_hits
            if uninformative or small_erroring_log or rare_topic_lines:
                anchor_lines = _anchor_regions(caller_text, _ANCHOR_MAX_LINES)
                if not anchor_lines and rare_topic_lines:
                    anchor_lines = [
                        _strip_anchor_prefix(line.strip())[:_ANCHOR_LINE_CHARS]
                        for line in rare_topic_lines
                    ]
                if anchor_lines:
                    anchored_query = (query or "") + "\n" + "\n".join(anchor_lines)
                    if len(caller_text) > _ANCHOR_RETRY_MAX_CHARS:
                        return anchored_query, query_as_given, derived_terms, anchor_lines, None
                    # Probe both objectives side-effect free (no CCR archive, log or
                    # decision cache); keep the anchored one only when it compresses successfully,
                    # retains every error fingerprint and is smaller than the plain one.
                    probe_ccr = bool(ccr) and (strategy or "extract").strip().lower() == "extract"
                    probe = dict(
                        mode=mode, budget_ratio=budget_ratio, ccr=probe_ccr, cache_prefix=False,
                        citations=citations, ccr_dir=ccr_dir, decision_cache=None, strategy="extract",
                        ambiguity_fail_open=ambiguity_fail_open, reorder_best=reorder_best,
                        semantic_tier=semantic_tier, log_dir=None, pin_patterns=pin_patterns,
                        pin_recent=pin_recent, min_savings_ratio=min_savings_ratio,
                        degraded_view=degraded_view, summary_endpoint=None, limits=limits,
                        derive_query=False, anchor_errors=False, gap_marker=gap_marker,
                        recursion_markers=recursion_markers, content_hint=content_hint,
                        inline_short_gaps=inline_short_gaps, prose_brief=prose_brief,
                        _ccr_defer=True,
                    )
                    want = set(error_fingerprints(caller_text))

                    def _probe_ok(res: CompressResult) -> bool:
                        return not res.fail_open and want <= set(error_fingerprints(res.compressed_text))

                    def _keeps_error_context(anchored: CompressResult, plain: CompressResult) -> bool:
                        def _output_lines(text):
                            lines = set()
                            for raw in text.splitlines():
                                line = raw.strip()
                                if not line:
                                    continue
                                if line.startswith("[×") or line.startswith("[last]"):
                                    continue
                                lines.add(line)
                            return lines

                        plain_lines = _output_lines(plain.compressed_text)
                        anchored_lines = _output_lines(anchored.compressed_text)
                        original_lines = caller_text.splitlines()
                        template_counts = None
                        error_flags = [_is_error_line(line.strip()) for line in original_lines]
                        total = len(original_lines)
                        for index, raw in enumerate(original_lines):
                            line = raw.strip()
                            if not line:
                                continue
                            if not any(error_flags[max(0, index - 2):min(total, index + 3)]):
                                continue
                            if line in plain_lines and line not in anchored_lines:
                                if template_counts is None:
                                    template_counts = collections.Counter(
                                        mask_template(original.strip().lower()) for original in original_lines
                                    )
                                if template_counts.get(mask_template(line.lower()), 0) >= 3:
                                    continue
                                return False
                        return True

                    anchored_probe = compress_context(caller_text, anchored_query, **probe)
                    if _probe_ok(anchored_probe):
                        plain_probe = compress_context(caller_text, query or "", **probe)
                        if (
                            not _probe_ok(plain_probe)
                            or (
                                len(anchored_probe.compressed_text) < len(plain_probe.compressed_text)
                                and _keeps_error_context(anchored_probe, plain_probe)
                            )
                        ):
                            query = anchored_query
                            chosen_probe = anchored_probe
                        else:
                            anchor_lines = []
                            chosen_probe = plain_probe
                    else:
                        anchor_lines = []
        else:
            anchor_lines = _anchor_regions(caller_text, _ANCHOR_MAX_LINES)
            if anchor_lines:
                query = "\n".join(anchor_lines)
    return query, query_as_given, derived_terms, anchor_lines, chosen_probe


def _normalise_options(
    *,
    min_savings_ratio,
    mode,
    pin_recent,
):
    """Check and normalise the mode and the savings threshold. Raises ValueError for a mode or ratio the engine does not know.

    Returns ``(requested_mode, mode_norm, pin_recent, min_savings_ratio)``."""
    requested_mode = (mode or "adaptive").strip().lower()
    if requested_mode not in {"adaptive", "fixed", "compiler", "precision"}:
        raise ValueError(
            f"unknown mode {mode!r} (expected adaptive/fixed/compiler/precision)"
        )
    mode_norm = (
        "adaptive" if requested_mode in {"compiler", "precision"} else requested_mode
    )
    try:
        pin_recent_num = float(pin_recent or 0)
        huge_int = False
    except OverflowError:
        # An int too large to represent as a float is still a valid count —
        # the pre-float conversion accepted it.
        huge_int = True
    except (TypeError, ValueError):
        pin_recent_num = math.nan
        huge_int = False
    if huge_int:
        pin_recent = max(0, int(pin_recent))
    elif not math.isfinite(pin_recent_num):
        raise ValueError(
            f"pin_recent must be a finite non-negative integer, got {pin_recent!r}"
        )
    else:
        pin_recent = max(0, int(pin_recent_num))
    if min_savings_ratio is None:
        min_savings_ratio = 0.10
    min_savings_ratio = float(min_savings_ratio)
    if not 0.0 <= min_savings_ratio < 1.0:
        raise ValueError(
            f"min_savings_ratio must be in [0, 1), got {min_savings_ratio!r}"
        )
    return requested_mode, mode_norm, pin_recent, min_savings_ratio


def _build_receipt(
    *,
    adapter_info,
    anchor_lines,
    budget_ratio,
    caller_text,
    citations,
    content_hint,
    degraded,
    derived_terms,
    fact_dense,
    fact_lines_dropped,
    fail_open,
    industrial,
    kept,
    log_error_retention,
    policy,
    query_as_given,
    requested_mode,
    result_text,
    risk,
    savings,
    scored,
    selection,
    strategy,
    structural_collapse_only,
    verifier,
):
    """The receipt that travels with a result: what ran, on what, and how the result was judged. Returns ``(receipt, query_hash)``."""
    # v0.10.0 (G5 memorix receipt): machine-readable provenance.
    query_hash = hashlib.sha256((query_as_given or "").encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    receipt = {
        "schema_version": "1",
        "engine": "tameru",
        "policy": policy,
        "kept_ids": _bounded_id_manifest(
            (i for i in kept if i < len(scored)),
            industrial.limits.max_receipt_ids,
        ),
        "dropped_ids": _bounded_id_manifest(
            (b["id"] for b in scored if b["id"] not in kept),
            industrial.limits.max_receipt_ids,
        ),
        "query_hash": query_hash,
        "savings_pct": savings,
        "risk": risk,
        "verifier": verifier,
        "degraded_view": degraded,
        # dsh-jev-prune lesson: never degrade silently — report which
        # selector path decided the keep-set.
        "selection": selection.get("path"),
        # lcc sufficiency lesson: blocks restored because a kept block's
        # rare terms were qualified or defined there.
        "sufficiency_restored": selection.get("sufficiency_restored") or [],
        # TPC lesson: callers must see when the objective was inferred,
        # not supplied — a derived query is advisory context, not intent.
        "query_source": "derived" if derived_terms else (
            "error-anchored" if anchor_lines else (
                "prose-brief" if selection.get("path") == "prose-brief" else "caller"
            )
        ),
        "derived_terms": derived_terms,
        "anchor_lines": anchor_lines,
        # v1.4.0: E7 — the keep-set came from structural collapse alone.
        "structural_collapse_only": bool(structural_collapse_only and not fail_open),
        # v1.4.0: E8 — the caller's routing hint, always recorded.
        "content_hint": content_hint,
        # v1.4.0: E5 — which diff/grep adapter shaped the text (None: none did).
        "adapter": adapter_info,
        # v1.4.0: E3 — level-tagged error fingerprints kept/total (logs only).
        "log_error_fingerprints": log_error_retention,
        # 1.10.0 (S5): protected fact lines absent from the output.
        "fact_lines_dropped": fact_lines_dropped,
        # 1.10.0 (S5, E4): fact-dense text — the S5 machinery stayed off.
        "fact_dense": fact_dense,
        "industrial": industrial.to_dict(),
    }
    receipt.update(
        _receipt_hashes(
            caller_text,
            result_text,
            industrial,
            mode=requested_mode,
            strategy=strategy,
            budget_ratio=budget_ratio,
            citations=citations,
        )
    )
    return receipt, query_hash


def _write_audit_log(
    *,
    fail_open,
    industrial,
    kept,
    log_dir,
    policy,
    query_hash,
    risk,
    savings,
    scored,
):
    """Append one line about this call to the audit log when a log directory was given. A file error is ignored."""
    # v0.10.0 (G1 memorix checkpoints): append-only audit log, opt-in.
    if log_dir:
        try:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                log_path.chmod(0o700)
            except OSError:
                pass
            top_dropped = sorted(
                (
                    {"id": b["id"], "score": round(float(b.get("score", 0.0)), 2)}
                    for b in scored
                    if b["id"] not in kept
                ),
                key=lambda d: -d["score"],
            )[:5]
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "query_hash": query_hash,
                "policy": policy,
                "kept": len(kept),
                "total": len(scored),
                "savings_pct": savings,
                "risk": risk,
                "fail_open": fail_open,
                "top_dropped": top_dropped,
                "industrial_format": industrial.profile.format,
                "industrial_applied": industrial.applied,
                "direction": industrial.profile.direction,
                "scripts": industrial.profile.scripts,
                "input_chars": industrial.profile.characters,
                "input_lines": industrial.profile.lines,
                "profile_truncated": industrial.profile.profile_truncated,
            }
            if log_path.is_symlink():
                raise OSError("log directory must be a real directory")
            log_file = log_path / "compactions.jsonl"
            if log_file.is_symlink():
                raise OSError("audit log must not be a symlink")
            open_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            if hasattr(os, "O_NOFOLLOW"):
                open_flags |= os.O_NOFOLLOW
            fd = os.open(log_file, open_flags, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise OSError("audit log must be a regular file")
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fd = None
                    if hasattr(os, "fchmod"):
                        os.fchmod(fh.fileno(), 0o600)
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            finally:
                if fd is not None:
                    os.close(fd)
        except OSError:
            pass  # logging must never break compression
    return 


def _finalize_result_text_and_ccr(
    *,
    _ccr_defer,
    cache_prefix,
    caller_text,
    ccr,
    ccr_dir,
    compressed,
    fail_open,
    kept,
    line_keep,
    original_text,
    original_tokens,
    query_as_given,
    risk,
    scored,
    secret_in_input,
    trust_filtered,
):
    """Wrap the compressed text for the cache prefix, append and store the CCR pointer, and apply the final size guard. Returns ``(result_text, ccr_info, compressed, kept, fail_open, risk, cache_applied, line_keep)``."""
    result_text = compressed
    cache_applied = False
    if cache_prefix and not fail_open:
        # Kept text that already carries a wrapper delimiter would make the
        # real closing tags ambiguous — a forged ``</compressed_context>``
        # lets trailing tool text sit outside the extract frame. Emit the
        # extract unwrapped rather than give that text the engine's framing.
        if not any(
            delimiter in compressed
            for delimiter in ("<compressed_context", "</compressed_context", "--- end context ---")
        ):
            result_text = cache_wrap(compressed, query_as_given or "")
            cache_applied = True

    ccr_info = None
    pending_ccr_hash = None
    candidate_text = result_text
    if ccr and not fail_open and compressed != original_text and not secret_in_input:
        pending_ccr_hash = hashlib.sha256(caller_text.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
        # A pointer-shaped line inside the kept text must not suppress the
        # real record reference — withhold only when this exact pointer is
        # already present.
        real_pointer = f"[CC-Retrieve: {pending_ccr_hash}]"
        if real_pointer not in candidate_text:
            candidate_text = candidate_text.rstrip() + f"\n{real_pointer}\n"

    if not fail_open and not trust_filtered and estimate_tokens(candidate_text) > original_tokens:
        result_text = caller_text
        compressed = caller_text
        kept = {b["id"] for b in scored}
        fail_open = True
        risk = "high"
        cache_applied = False
        line_keep = 1.0
    else:
        result_text = candidate_text
        if pending_ccr_hash is not None:
            if _ccr_defer:
                # Probe path: keep the marker; the caller stores once at reuse.
                ccr_info = {"hash": pending_ccr_hash, "path": None, "deferred": True}
            else:
                try:
                    # Recovery means the caller's exact bytes, not a preprocessed view.
                    ccr_info = _ccr_store(caller_text, ccr_dir)
                except OSError:
                    ccr_info = None
                if ccr_info is None:
                    # Store refused (secret screen) or failed — never emit a
                    # dangling retrieval pointer.
                    result_text = result_text.replace(
                        f"\n[CC-Retrieve: {pending_ccr_hash}]\n", ""
                    )
    return result_text, ccr_info, compressed, kept, fail_open, risk, cache_applied, line_keep


def _collect_reasons(
    *,
    adapter_info,
    ccr,
    degraded,
    fail_open,
    freeze_cache_saturated,
    industrial,
    kept,
    log_error_retention,
    risk,
    savings_gate,
    scored,
    secret_in_input,
    source_pin_loss,
    structural_collapse_only,
):
    """Human-readable reasons for the result, and the risk after the degraded-view adjustment. Returns ``(reasons, risk)``."""
    reasons = sorted({scored[i]["reason"] for i in kept if i < len(scored)})
    # A kept exemplar-flagged block means the exemplar mechanism contributed to
    # retention even when the block's primary reason was something else (for
    # example a query-term hit) — the relabel at score time only covers
    # context/log-error/critical-lines reasons.
    if any(scored[i].get("error_exemplar") for i in kept if i < len(scored)):
        reasons.append("error exemplar")
    if source_pin_loss:
        reasons.append("original pinned blocks could not be preserved")
    if industrial.applied:
        reasons.append(f"industrial adapter: {industrial.profile.format}")
    if adapter_info is not None and not fail_open:
        reasons.append(f"format adapter: {adapter_info['name']}")
    if freeze_cache_saturated:
        reasons.append("freeze cache capacity reached")
    if savings_gate:
        reasons.append("savings below min_savings_ratio")
    if structural_collapse_only and not fail_open:
        reasons.append("structural collapse only (query terms absent)")
    if log_error_retention and log_error_retention["kept"] < log_error_retention["total"]:
        reasons.append(
            f"log error fingerprints lost: {log_error_retention['kept']}"
            f"/{log_error_retention['total']} kept"
        )
    if degraded:
        reasons.append("degraded scoring view")
        if risk == "low":
            risk = "medium"
    if ccr and secret_in_input:
        # dsh-jev-pre-compaction lesson: scan for secrets BEFORE archiving.
        reasons.append("ccr skipped: secret material detected")
    return reasons, risk


def _objective_is_empty_or_absent(query: str, original_text: str) -> bool:
    """The guards of :func:`_apply_query_guards`, read before scoring: an empty or filler query, or one whose
    distinctive terms occur nowhere in the text."""
    q = query or ""
    if not q.strip():
        return True
    if not query_has_distinctive_selectors(q) and not _topic_terms(q):
        return True
    terms = [t for t in distinctive_query_terms(q) if not t.startswith("script:")]
    if terms:
        blob = original_text.casefold() if original_text.isascii() else _match_fold(original_text)
        return not any(t in blob for t in terms)
    return query_profile(q, original_text).basis == "cross_lingual"


def _structural_exit_lines(
    *,
    adapter_info,
    ambiguity_fail_open,
    code_hint,
    content_type,
    decision_cache,
    degraded,
    lines,
    min_savings_ratio,
    mode_norm,
    no_table,
    original_text,
    prose_brief,
    query,
    route_hint,
    text,
):
    """The structural fold to return when scoring may be skipped, else None. Only for an empty, filler or absent
    objective, never for adapter output, source code, a prose brief, a CSV, a frozen decision cache, a
    non-adaptive mode or text carrying injection-shaped (trust-risk) lines, and only when the fold clears
    ``min_savings_ratio`` (otherwise the normal path runs and fails open exactly as before)."""
    if (
        _PINNED_LINES.get() or adapter_info is not None or ambiguity_fail_open or degraded or mode_norm != "adaptive"
        or decision_cache is not None or code_hint or route_hint == "numbered_code"
        or content_type not in ("log", "text")
    ):
        return None
    q = query or ""
    if prose_brief and not q.strip() and content_type == "text":
        return None
    if not _objective_is_empty_or_absent(q, original_text):
        return None
    if not query_has_distinctive_selectors(q) and not no_table and _looks_like_csv(original_text):
        return None
    folded = "\n".join(lines)
    if folded == original_text:
        return None
    if _TRUST_RISK_RE.search(_normalise_instruction_text(folded)) is not None:
        return None
    original_tokens = estimate_tokens(original_text)
    kept_tokens = estimate_tokens(folded)
    if original_tokens > 200:
        clears = 1.0 - kept_tokens / max(1, original_tokens) >= min_savings_ratio
    else:
        clears = kept_tokens < original_tokens
    return lines if clears else None


def _builtin_anchor_lines(
    *,
    adapter_info,
    anchor_lines,
    code_hint,
    content_type,
    degraded,
    derived_terms,
    mode_norm,
    query,
    route_hint,
    text,
):
    """Error regions as the built-in objective of a generic or absent query on a log (existing error fingerprints,
    trust-risk lines excluded, no probe run). Empty when the caller already chose an objective or no real error exists."""
    if (
        _PINNED_LINES.get() or adapter_info is not None or anchor_lines or derived_terms or code_hint or degraded
        or mode_norm != "adaptive" or content_type != "log" or route_hint == "numbered_code"
    ):
        return []
    if not _objective_is_empty_or_absent(query, text):
        return []
    if "[\u00d7" in text or "frames omitted" in text or "[\u2026" in text or "[last] " in text:
        return []  # already folded or cut by the engine: anchoring again would not be idempotent
    if not any(not _is_trust_risk_line(example) for example in error_fingerprints(text).values()):
        return []
    return _anchor_regions(text, _ANCHOR_MAX_LINES)


def _score_select_render(
    *,
    adapter_info,
    ambiguity_fail_open,
    blocks,
    budget_ratio,
    caller_text,
    citations,
    code_hint,
    content_type,
    decision_cache,
    degraded,
    gap_marker,
    lines,
    mode_norm,
    no_table,
    original_text,
    pin_patterns,
    pin_recent,
    prose_brief,
    query,
    recall_base,
    reorder_best,
    score_lines,
    semantic_tier,
    text,
):
    """Score the blocks, apply pins and frozen decisions, select, reconcile, apply the query guards and render. Returns ``(scored, decision_cache, kept, fail_open, risk, selection, compressed, recall, structural_collapse_only)``."""
    scored = _score_with_degraded_view(
        blocks=blocks,
        content_type=content_type,
        degraded=degraded,
        query=query,
        score_lines=score_lines,
    )

    pin_recent_ids = _apply_pins(
        pin_patterns=pin_patterns,
        pin_recent=pin_recent,
        scored=scored,
    )

    # Freeze-on-first-sight: if a decision_cache is provided and the block
    # fingerprints match prior turns, replay the stored keep/drop decisions
    # byte-identically. This keeps the provider prompt cache warm across a
    # multi-turn session (the prefix doesn't churn when new turns arrive).
    if decision_cache is not None and not isinstance(decision_cache, dict):
        decision_cache = None
    if decision_cache is not None:
        scored = _apply_freeze(decision_cache, scored, text, query or "")
    _reorder = bool(reorder_best) and adapter_info is None
    kept, fail_open, risk, selection = _select_blocks(
        budget_ratio=budget_ratio, caller_text=caller_text, citations=citations,
        code_hint=code_hint, content_type=content_type, gap_marker=gap_marker, lines=lines,
        mode_norm=mode_norm, prose_brief=prose_brief, query=query, score_lines=score_lines,
        scored=scored, semantic_tier=semantic_tier,
    )
    kept, fail_open, risk = _reconcile_selection(
        adapter_info=adapter_info, ambiguity_fail_open=ambiguity_fail_open, code_hint=code_hint,
        decision_cache=decision_cache, fail_open=fail_open, kept=kept,
        pin_recent_ids=pin_recent_ids, query=query, risk=risk, scored=scored,
    )

    fail_open, risk = _apply_query_guards(
        adapter_info=adapter_info,
        fail_open=fail_open,
        no_table=no_table,
        original_text=original_text,
        query=query,
        risk=risk,
        selection=selection,
    )

    compressed, kept, fail_open, risk, recall, structural_collapse_only = _render_and_check_recall(
        adapter_info=adapter_info, ambiguity_fail_open=ambiguity_fail_open, caller_text=caller_text,
        citations=citations, decision_cache=decision_cache, fail_open=fail_open,
        gap_marker=gap_marker, kept=kept, lines=lines, original_text=original_text, query=query,
        recall_base=recall_base, _reorder=_reorder, risk=risk, score_lines=score_lines,
        scored=scored,
    )
    return scored, decision_cache, kept, fail_open, risk, selection, compressed, recall, structural_collapse_only


def _apply_cost_gates(
    *,
    adapter_info,
    caller_text,
    compressed,
    fail_open,
    kept,
    min_savings_ratio,
    original_text,
    recall,
    risk,
    savings_gate,
    scored,
    source_pin_texts,
):
    """Token counts and the fail-open gates on the result: net-negative size, too little savings, and lost pinned source text. Returns ``(original_tokens, kept_tokens, trust_filtered, compressed, kept, fail_open, risk, savings_gate, source_pin_loss, recall)``."""
    original_tokens = estimate_tokens(original_text)
    kept_tokens = estimate_tokens(compressed)
    trust_filtered = any(
        b.get("trust_risk") and not b.get("pinned") and b["id"] not in kept
        for b in scored
    )

    # Cost gate: if the compressed output is LARGER than the original
    # (net-negative savings), fail open. This happens when citations and
    # the CCR marker add more tokens than the dropped blocks saved.
    #
    # Provider cache pricing makes this more nuanced: Anthropic charges
    # 1.25× for cache writes and 0.1× for cache reads. If the context is
    # already cached (repeated session), the original is cheap to re-send
    # and the compression overhead may not be worth it. We model this
    # with a simple heuristic: if the savings are < 10%, the overhead of
    # citations + CCR marker likely exceeds the cache-read savings.
    if (
        not fail_open
        and (
            kept_tokens > original_tokens
            or (kept_tokens >= original_tokens and len(compressed) > len(original_text))
        )
        and not trust_filtered
    ):
        compressed = original_text
        kept = {b["id"] for b in scored}
        fail_open = True
        risk = "high"
        kept_tokens = estimate_tokens(compressed)
    elif not fail_open and original_tokens > 200:
        # For substantial contexts, check if the savings justify the
        # compression overhead. If we're saving less than 10%, the
        # citation/CCR overhead likely exceeds the benefit, especially
        # when the provider cache makes the original cheap to re-send.
        if adapter_info is not None:
            # Estimator undercounts identifier-like dropped lines, so use char savings as a floor.
            token_savings = 1.0 - kept_tokens / max(1, original_tokens)
            char_savings = 1.0 - len(compressed) / max(1, len(original_text))
            savings_ratio = max(token_savings, char_savings)
        else:
            savings_ratio = 1.0 - (kept_tokens / max(1, original_tokens))
        if savings_ratio < min_savings_ratio and not trust_filtered:
            compressed = original_text
            kept = {b["id"] for b in scored}
            fail_open = True
            risk = "high"
            savings_gate = True
            kept_tokens = estimate_tokens(compressed)

    source_pin_loss = not fail_open and any(part not in compressed for part in source_pin_texts)
    if source_pin_loss:
        compressed = caller_text
        kept = {block['id'] for block in scored}
        fail_open = True
        risk = 'high'
        recall = 0.0
        kept_tokens = estimate_tokens(compressed)

    if fail_open and compressed != caller_text:
        compressed = caller_text
        kept_tokens = estimate_tokens(compressed)
    return original_tokens, kept_tokens, trust_filtered, compressed, kept, fail_open, risk, savings_gate, source_pin_loss, recall


def _render_and_check_recall(
    *,
    adapter_info,
    ambiguity_fail_open,
    caller_text,
    citations,
    decision_cache,
    fail_open,
    gap_marker,
    kept,
    lines,
    original_text,
    query,
    recall_base,
    _reorder,
    risk,
    score_lines,
    scored,
):
    """Render the kept blocks (or restore the original when failing open), then widen the selection once if query entities were lost. Returns ``(compressed, kept, fail_open, risk, recall, structural_collapse_only)``."""
    collapsed = "\n".join(lines)
    structural_collapse_only = False
    if fail_open:
        annotated_ids = {
            b["id"] for b in scored if b.get("trust_risk") and not b.get("pinned")
        }
        if annotated_ids:
            # Restore ordinary data when uncertain, but never undo a block
            # annotation. Explicitly pinned blocks remain eligible.
            kept = {b["id"] for b in scored if b["id"] not in annotated_ids}
            compressed = _render(
                lines, scored, kept, citations=citations, reorder_best=_reorder,
                gap_marker=gap_marker, total_chars=len(caller_text),
                content_lines=score_lines, query=query,
            )
            fail_open = False
            risk = "high"
        # Do not undo a useful structured collapse (repeated INFO lines).
        # Baseline RAG wins on JP/KO heartbeats by keeping the error and
        # dropping repeats; restoring original bytes here threw that away.
        elif (
            not ambiguity_fail_open
            and collapsed != original_text
            and len(collapsed) < 0.7 * max(1, len(original_text))
        ):
            fail_open = False
            compressed = collapsed
            kept = {b["id"] for b in scored}
            # v1.4.0 (E7): the query never selected anything here; what is
            # returned is the structural collapse alone (repeat folding,
            # frame runs), not an answer-driven extract. Say so.
            structural_collapse_only = True
        else:
            compressed = original_text
            kept = {b["id"] for b in scored}
    else:
        compressed = _render(
            lines, scored, kept, citations=citations, reorder_best=_reorder,
            gap_marker=gap_marker, total_chars=len(caller_text),
            content_lines=score_lines, query=query,
        )

    if (adapter_info is not None and not fail_open
            and all(block["id"] in kept for block in scored)):
        # Selection is already final: preserve whitespace inside complete records,
        # including blank diff context lines, instead of manufacturing new gaps.
        compressed = collapsed
    recall = _entity_recall(recall_base, compressed, query or "")
    if recall < 0.66 and not fail_open:
        # One expansion pass: add any dropped block that still holds a query key.
        keys = _extract_entities(query or "") + _extract_terms(query or "")
        for b in scored:
            if b["id"] in kept or b.get("trust_risk"):
                continue
            if any(_soft_has(b["text"], k) for k in keys):
                kept.add(b["id"])
        if decision_cache is not None:
            kept = _enforce_frozen_decisions(scored, kept)
        compressed = _render(
            lines, scored, kept, citations=citations, reorder_best=_reorder,
            gap_marker=gap_marker, total_chars=len(caller_text),
            content_lines=score_lines, query=query,
        )
        recall = _entity_recall(recall_base, compressed, query or "")
        trust_risks = {
            b["id"]
            for b in scored
            if b.get("trust_risk") and not b.get("pinned")
        }
        if trust_risks:
            # Filter the CURRENT selection down by trust risks — do not
            # rebuild it as "everything except risks". Rebuilding discards
            # the selector's careful small keep-set and re-inflates the
            # payload to near-original size (v0.5.19 production QA finding).
            kept = {bid for bid in kept if bid not in trust_risks}
            if decision_cache is not None:
                kept = _enforce_frozen_decisions(scored, kept)
            compressed = _render(
                lines, scored, kept, citations=citations, reorder_best=_reorder,
                gap_marker=gap_marker, total_chars=len(caller_text),
                content_lines=score_lines, query=query,
            )
            risk = "high"
        elif recall < 0.5:
            compressed = original_text
            fail_open = True
            risk = "high"
            kept = {b["id"] for b in scored}
    return compressed, kept, fail_open, risk, recall, structural_collapse_only


def _apply_query_guards(
    *,
    adapter_info,
    fail_open,
    no_table,
    original_text,
    query,
    risk,
    selection,
):
    """Fail open when the query is empty or filler, names nothing present in the text, or the text is a CSV without a selector. Returns ``(fail_open, risk)``."""
    q = query or ""
    prose_brief_used = selection.get("path") == "prose-brief" and not fail_open
    # Structural test-runner output is query-independent; skip the empty/filler guard.
    test_output_adapter = adapter_info is not None and adapter_info.get("name") == "test_output"
    if not prose_brief_used and not test_output_adapter and (
        not q.strip()
        or (not query_has_distinctive_selectors(q) and not _topic_terms(q))
    ):
        fail_open = True
        risk = "high"
    else:
        latin_terms = [
            t
            for t in distinctive_query_terms(q)
            if not t.startswith("script:")
        ]
        if latin_terms:
            blob = original_text.casefold() if original_text.isascii() else _match_fold(original_text)
            if not any(t in blob for t in latin_terms):
                fail_open = True
                risk = "high"
        elif query_profile(q, original_text).basis == "cross_lingual":
            # 1.10.0: a query that names only non-Latin units (a Chinese question about an English log) and
            # none of them is in the text says nothing about this text: the same fail-open as an absent Latin term.
            fail_open = True
            risk = "high"
    if (
        not query_has_distinctive_selectors(q)
        and not no_table
        and _looks_like_csv(original_text)
    ):
        fail_open = True
        risk = "high"
    return fail_open, risk


def _reconcile_selection(
    *,
    adapter_info,
    ambiguity_fail_open,
    code_hint,
    decision_cache,
    fail_open,
    kept,
    pin_recent_ids,
    query,
    risk,
    scored,
):
    """Re-apply frozen decisions, supersession, error exemplars and pins to the keep-set, let a format adapter keep everything, and honour ambiguity_fail_open. Returns ``(kept, fail_open, risk)``."""
    if not fail_open:
        if decision_cache is not None:
            kept = _enforce_frozen_decisions(scored, kept)
        # Temporal supersession: a later kept block that explicitly marks an
        # earlier kept block stale (now/obsolete/override/newer date) prunes
        # it after cache replay, so a frozen keep cannot revive stale data.
        # v1.4.0: not for content the caller says is source code. The markers
        # are prose ("override", "deprecated", " disabled" are ordinary code
        # words) and two functions share identifiers by construction, so a
        # comment in a LATER function would evict the very function asked
        # about — and the hint exists so function bodies survive.
        if not code_hint:
            kept = apply_supersession(scored, kept)
        # v1.4.0 (E3) safety net: neither a frozen drop nor supersession may
        # evict the one exemplar block of a level-tagged log error.
        kept |= {
            b["id"]
            for b in scored
            if b.get("error_exemplar") and not b.get("trust_risk")
        }
        if pin_recent_ids:
            # Pins are never touched: a score-999 boost alone cannot reach
            # kept when a selector path ignores raw scores (needle-only),
            # and neither freeze nor supersession may evict a pin.
            kept |= pin_recent_ids
    if adapter_info is not None and scored and not ambiguity_fail_open:
        # v1.4.0 (E5): the format adapter already chose what to keep (every
        # header, whole hunks, grouped matches); block scoring must not drop a
        # file header or half a hunk. Risk reflects how the adapter chose.
        kept = {b["id"] for b in scored}
        fail_open = False
        risk = "low" if query_has_distinctive_selectors(query or "") else "medium"
    if ambiguity_fail_open:
        fail_open = True
        risk = "high"
    return kept, fail_open, risk


def _select_blocks(
    *,
    budget_ratio,
    caller_text,
    citations,
    code_hint,
    content_type,
    gap_marker,
    lines,
    mode_norm,
    prose_brief,
    query,
    score_lines,
    scored,
    semantic_tier,
):
    """Run the fixed-ratio or adaptive selector over the scored blocks. Returns ``(kept, fail_open, risk, selection)``; ``selection`` is the selector's own report."""
    selection: dict[str, Any] = {}
    if mode_norm == "fixed":
        ratio = 0.35 if budget_ratio is None else float(budget_ratio)
        if not (0.0 < ratio <= 1.0):
            raise ValueError(f"budget_ratio must be in (0, 1], got {ratio!r}")
        kept, fail_open, risk = select_fixed(scored, ratio, out=selection)
        if gap_marker is not None and not citations and not fail_open:
            # Marker text costs tokens too: reserve them out of the budget and
            # select once more (gap count may shift slightly; one pass is
            # enough to keep the rendered output near the requested ratio).
            reserve = _gap_marker_reserve(
                lines, scored, kept, gap_marker, len(caller_text), content_lines=score_lines
            )
            if reserve:
                kept, fail_open, risk = select_fixed(
                    scored, ratio, out=selection, reserve_tokens=reserve
                )
    else:
        if (
            prose_brief
            and not (query or "").strip()
            and content_type == "text"
            and not code_hint
        ):
            kept, fail_open, risk = select_prose_brief(scored, out=selection)
        else:
            kept, fail_open, risk = select_adaptive(
                scored,
                needle_only=query_has_distinctive_selectors(query or ""),
                query=query or "",
                semantic_tier=resolve_tier(semantic_tier) if semantic_tier is not None else None,
                out=selection,
            )
        ratio = budget_ratio if budget_ratio is not None else 0.0
    return kept, fail_open, risk, selection


def _apply_pins(
    *,
    pin_patterns,
    pin_recent,
    scored,
):
    """Boost and mark the blocks that pin_patterns or pin_recent protect from dropping (mutates ``scored``). Returns ``pin_recent_ids``."""
    # v0.10.0 (G2, KVzip sink semantics): pinned blocks are exempt from
    # dropping in every selector path. Applied by boosting score and marking;
    # the floor/important/needle paths all respect score, and trust-risk is
    # bypassed for pins (a caller-pinned line outranks injection heuristics).
    if pin_patterns:
        _pin_res = compile_pin_patterns(pin_patterns)
        for b in scored:
            if _pin_res is None or any(rx.search(b["text"]) for rx in _pin_res):
                b["score"] = max(b["score"], 999.0)
                b["pinned"] = True

    # JEV-style positional pinning: the opening block and the newest N
    # blocks are unconditional keeps — the caller's working-context floor.
    # Same trust semantics as pin_patterns: pins outrank drop and risk paths.
    pin_recent_ids: set[int] = set()
    if pin_recent and scored:
        pin_recent_ids = {scored[0]["id"]}
        pin_recent_ids.update(b["id"] for b in scored[-pin_recent:])
        for b in scored:
            if b["id"] in pin_recent_ids:
                b["score"] = max(b["score"], 999.0)
                b["pinned"] = True
    return pin_recent_ids


def _block_limit_fail_open_result(
    *,
    blocks,
    budget_ratio,
    caller_text,
    citations,
    content_hint,
    industrial,
    query_as_given,
    requested_mode,
    strategy,
):
    """The fail-open result for input with more blocks than the limit allows."""
    tokens = estimate_tokens(caller_text)
    reason = (
        f"block limit exceeded: {len(blocks)} > "
        f"{industrial.limits.max_blocks}"
    )
    receipt = {
        "schema_version": "1",
        "engine": "tameru",
        "policy": "local-fail-open",
        "query_hash": hashlib.sha256(
            (query_as_given or "").encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:12],
        "savings_pct": 0.0,
        "risk": "high",
        "content_hint": content_hint,
        "industrial": industrial.to_dict(),
    }
    receipt.update(
        _receipt_hashes(
            caller_text,
            caller_text,
            industrial,
            mode=requested_mode,
            strategy=strategy,
            budget_ratio=budget_ratio,
            citations=citations,
        )
    )
    return CompressResult(
        compressed_text=caller_text,
        original_tokens=tokens,
        kept_tokens=tokens,
        tokens_saved_pct=0.0,
        policy_name="local-fail-open",
        mode=requested_mode,
        keep_ratio=1.0,
        tokens_saved=0,
        kept_line_ratio=1.0,
        compression_risk="high",
        confidence=0.0,
        content_type=industrial.profile.format,
        fail_open=True,
        reasons=[reason],
        receipt=receipt,
    )


def _split_into_lines(
    *,
    adapter_info,
    code_hint,
    industrial,
    prose_brief,
    query,
    route_hint,
    text,
):
    """Split the working text into lines and decide the content type; ``recall_base`` is the text recall is measured against. Returns ``(lines, content_type, recall_base)``."""
    if adapter_info is not None:
        # Adapters already choose complete records. Do not crush/fold inside them.
        lines = text.split("\n")
        content_type = _HINT_ROUTES.get(route_hint) or route_content_type(lines)
        recall_base = text
    elif query_has_distinctive_selectors(query or ""):
        lines, content_type = preprocess(text, query or "", content_hint=route_hint)
        if industrial.applied:
            content_type = industrial.profile.format
        # Recall must be measured against the text the selector actually saw.
        recall_base = "\n".join(lines) if content_type == "log" else text
    else:
        # Do not fingerprint-collapse logs or crush JSON on a generic query.
        # (Perf, v1.4.0: preprocess() output was computed and then discarded
        # on this path — ~0.4 s of log collapsing per 650 KB — so it is not
        # run at all; the result is identical.)
        lines = _compact_progress_lines(text.split("\n"))
        content_type = _HINT_ROUTES.get(route_hint) or route_content_type(lines)
        recall_base = text
        if content_type == "log" and not _PINNED_LINES.get():
            # (pins active: the caller's pinned blocks are located in the ORIGINAL line structure, so nothing is folded)
            # 1.10.0: the STRUCTURAL pass (progress removal, [×N] template collapse, per-cause frame folding)
            # runs for every log/trace route whatever the query; only query-driven selection is skipped.
            folded = structural_log_pass(lines)
            if folded != lines:
                lines = folded
                recall_base = "\n".join(lines)
        if content_type == "json":
            summarized = preprocess_json(text, query or "")
            if summarized != text:
                lines = _compact_progress_lines(summarized.split("\n"))
        elif content_type == "text":
            lines = _fold_repeated_sentences(lines)
            # 1.10.0: compile / resolve / download / passing-test noise in text-routed tool output is
            # folded the same way a log route folds it (counts, never the failures).
            folded = _fold_build_noise(lines) if not _PINNED_LINES.get() else lines
            if folded != lines:
                lines = folded
                recall_base = "\n".join(lines)
            # Split long multi-sentence prose lines into sentence blocks so the
            # no-query prose brief can reach the minimum block count.
            if (
                prose_brief
                and not (query or "").strip()
                and not code_hint
                and len(_segment_blocks_memo(lines)) < _PROSE_MIN_BLOCKS
            ):
                split = _split_prose_sentences(lines)
                if (
                    split is not lines
                    and len(_segment_blocks_memo(split)) >= _PROSE_MIN_BLOCKS
                ):
                    lines = split
    return lines, content_type, recall_base


def _preprocess_for_selectors(
    *,
    adapter_gap,
    adapter_info,
    code_hint,
    no_table,
    query,
    text,
):
    """Crush embedded JSON, CSV rows and filler comments, but only when the query names something specific. Returns ``(text, adapter_info)``."""
    # Destructive preprocess (JSON crush / later log collapse) only when
    # the query names something specific. Generic/empty queries must not
    # delete array tails or fingerprint-collapse logs before scoring.
    if query_has_distinctive_selectors(query or "") and not code_hint and not adapter_info:
        # (content_hint code/numbered_code: source code with commas or JSON
        # literals is not a table to crush; function bodies must survive.)
        if route_content_type(_norm_newlines(text).split("\n")) != "json":
            before_json = text
            text = _preprocess_json(text, query or "")
            if text != before_json:
                adapter_info = {
                    "name": "embedded_json",
                    "total_records": None,
                    "kept_records": None,
                    "reason": "complete JSON payloads selected; envelope preserved",
                }
        if adapter_info is None:
            if not no_table:
                text = preprocess_csv(text, query or "", gap_marker=adapter_gap)
            text = preprocess_filler_comments(text, query or "")
    return text, adapter_info


def _select_format_adapter(
    *,
    adapter_gap,
    caller_text,
    content_hint,
    industrial,
    payload_industrial,
    query,
    route_hint,
    text,
):
    """Let the diff, grep, test-runner, YAML-document and agent adapters claim the text. Returns ``(text, adapter_info)``; ``adapter_info`` is None when none did."""
    adapter_info: dict[str, Any] | None = None
    report_result = (payload_industrial.format_result if payload_industrial is not None
                     and payload_industrial.format_result is not None else industrial.format_result)
    if report_result is not None and report_result.format in REPORT_FORMATS:
        adapter_info = {
            "name": report_result.format, "total_records": report_result.total_records,
            "kept_records": report_result.kept_records,
            "reason": report_result.reason,
        }
    _pre_test_text = text
    if adapter_info is None:
        text = preprocess_test_runner(
            text, query or "", content_hint=content_hint, gap_marker=adapter_gap
        )
    if adapter_info is None and (
        text is not _pre_test_text
        and content_hint in (None, "test")
        and len(text) <= _TEST_REDUCTION_FINAL_CHARS
        and detect_test_runner(_pre_test_text) is not None
    ):
        # Same for a reduced test run (v1.4.0): block scoring must not drop
        # the failing test's name/file line that the reduction kept (jest
        # "FAIL f.test.js" / "● suite › case" vs "which tests failed?").
        # Larger reductions still go through scoring and its budget.
        adapter_info = {
            "name": "test_output",
            "total_records": None,
            "kept_records": None,
            "reason": "failure blocks and summaries kept",
        }
    if (
        adapter_info is None
        and industrial.profile.format == "yaml"
        and route_hint not in _CODE_HINTS
        and route_hint not in ("log", "json", "text")
        and any(line.rstrip() == "---" for line in caller_text.splitlines())
    ):
        # Whole YAML documents are the selection, including a declined/no-hit
        # selection: generic block scoring must not detach names from status.
        format_result = industrial.format_result
        adapter_info = {
            "name": "yaml_documents",
            "total_records": format_result.total_records if format_result else None,
            "kept_records": format_result.kept_records if format_result and format_result.applied else None,
            "reason": format_result.reason if format_result else "whole documents preserved",
        }
    if (
        adapter_info is None
        and route_hint not in _CODE_HINTS
        and route_hint not in ("log", "json", "text")
    ):
        text, adapter_info = apply_agent_adapters(
            text,
            query or "",
            hint=content_hint,
            gap_marker=adapter_gap,
            weak_query=not query_has_distinctive_selectors(query or ""),
        )
    return text, adapter_info


def _summarise_result_or_none(
    *,
    budget_ratio,
    caller_text,
    ccr,
    ccr_dir,
    citations,
    content_hint,
    industrial,
    original_text,
    query,
    query_as_given,
    requested_mode,
    secret_in_input,
    source_pin_texts,
    strategy,
    summary_allow_remote,
    summary_endpoint,
    summary_models,
    summary_timeout,
    text,
    tool_meta_line,
):
    """Summarise with the configured LLM. Returns the finished ``CompressResult`` when the summary is valid and shorter, else None so the caller falls back to extraction."""
    summary = _summarise_with_llm(
        text,
        query or "",
        endpoint=summary_endpoint,
        model_candidates=summary_models,
        timeout=summary_timeout,
        allow_remote=summary_allow_remote,
    )
    summary_valid = False
    summary_recall = 0.0
    if summary is not None:
        summary_valid, summary_recall = _summary_preserves_required_facts(
            text, summary, query or ""
        )
    if (
        summary is not None
        and summary_valid
        and estimate_tokens(summary) < estimate_tokens(text)
        and all(part in tool_meta_line + summary for part in source_pin_texts)
    ):
        # LLM summary is shorter than the original — use it.
        # Store the original in CCR for reversibility.
        ccr_info = None
        ccr_marker = ""
        if ccr:
            try:
                ccr_info = _ccr_store(caller_text, ccr_dir)
            except OSError:
                ccr_info = None
            if ccr_info is not None:
                ccr_marker = f"\n[CC-Retrieve: {ccr_info['hash']}]"
        result_text = tool_meta_line + summary + ccr_marker
        original_tokens = estimate_tokens(original_text)
        kept_tokens = estimate_tokens(result_text)
        keep_ratio = kept_tokens / max(1, original_tokens)
        summary_verifier = {
            "query_fact_recall": round(summary_recall, 3),
            "structured_ids_grounded": True,
            "risk": "medium",
            "score": round(summary_recall, 3),
        }
        summary_risk = "medium"
        return CompressResult(
            compressed_text=result_text,
            original_tokens=original_tokens,
            kept_tokens=kept_tokens,
            tokens_saved_pct=(1.0 - keep_ratio) * 100.0,
            policy_name="summarise-llm",
            mode=requested_mode,
            keep_ratio=keep_ratio,
            tokens_saved=original_tokens - kept_tokens,
            kept_line_ratio=1.0,
            cache_prefix_applied=False,
            compression_risk=(
                summary_risk if summary_risk in {"medium", "high"} else "medium"
            ),
            confidence=round(
                min(summary_recall, float(summary_verifier.get("score", 0.0))),
                3,
            ),
            ccr=ccr_info,
            content_type="text",
            fail_open=False,
            frozen_blocks=0,
            reasons=(
                ["llm summary", "query facts verified"]
                + (["ccr skipped: secret material detected"] if ccr and secret_in_input else [])
            ),
            verifier=summary_verifier,
            receipt={
                "schema_version": "1",
                "engine": "tameru",
                "policy": "summarise-llm",
                "query_hash": hashlib.sha256(
                    (query_as_given or "").encode("utf-8", errors="surrogatepass")
                ).hexdigest()[:12],
                "savings_pct": round((1.0 - keep_ratio) * 100.0, 2),
                "risk": summary_risk,
                "content_hint": content_hint,
                "industrial": industrial.to_dict(),
                **_receipt_hashes(
                    caller_text,
                    result_text,
                    industrial,
                    mode=requested_mode,
                    strategy=strategy,
                    budget_ratio=budget_ratio,
                    citations=citations,
                ),
            },
        )
    return None


def _compress_auto_ladder(
    *,
    ambiguity_fail_open,
    anchor_errors,
    prose_brief=False,
    inline_short_gaps=False,
    budget_ratio,
    cache_prefix,
    caller_text,
    ccr,
    ccr_dir,
    citations,
    content_hint,
    decision_cache,
    degraded_view,
    derive_query,
    gap_marker,
    limits,
    log_dir,
    min_savings_ratio,
    pin_patterns,
    pin_recent,
    query_as_given,
    recursion_markers,
    reorder_best,
    requested_mode,
    semantic_tier,
    summary_allow_remote,
    summary_endpoint,
    summary_models,
    summary_timeout,
):
    """The 'auto' strategy: extract first, escalate to the LLM summariser only if extraction failed open."""
    # Progressive ladder (Claude Code tiers / JEV hook fallback):
    # run the cheap deterministic tier first, then escalate to the
    # LLM summariser only when extraction fails open (ambiguity,
    # saturated floors, min_savings undershoot). 'summarise' itself
    # falls back to 'extract' on any LLM failure, so the worst case
    # here is one extra deterministic pass.
    ladder_kwargs = dict(
        mode=requested_mode,
        budget_ratio=budget_ratio,
        ccr=ccr,
        cache_prefix=cache_prefix,
        citations=citations,
        ccr_dir=ccr_dir,
        decision_cache=decision_cache,
        ambiguity_fail_open=ambiguity_fail_open,
        reorder_best=reorder_best,
        semantic_tier=semantic_tier,
        log_dir=log_dir,
        pin_patterns=pin_patterns,
        pin_recent=pin_recent,
        min_savings_ratio=min_savings_ratio,
        degraded_view=degraded_view,
        limits=limits,
        derive_query=derive_query,
        anchor_errors=anchor_errors,
        gap_marker=gap_marker,
        recursion_markers=recursion_markers,
        content_hint=content_hint,
        prose_brief=prose_brief,
        inline_short_gaps=inline_short_gaps,
    )
    base = compress_context(caller_text, query_as_given, strategy="extract", **ladder_kwargs)
    if not base.fail_open:
        return base
    return compress_context(
        caller_text,
        query_as_given,
        strategy="summarise",
        summary_endpoint=summary_endpoint,
        summary_models=summary_models,
        summary_timeout=summary_timeout,
        summary_allow_remote=summary_allow_remote,
        **ladder_kwargs,
    )


def _preflight_fail_open_result(
    *,
    budget_ratio,
    caller_text,
    citations,
    content_hint,
    industrial,
    query_as_given,
    requested_mode,
    strategy,
):
    """The fail-open result for input the industrial preflight refused."""
    tokens = estimate_tokens(caller_text)
    reason = industrial.reason or "industrial preflight failed open"
    fail_result = CompressResult(
        compressed_text=caller_text,
        original_tokens=tokens,
        kept_tokens=tokens,
        tokens_saved_pct=0.0,
        policy_name="local-fail-open",
        mode=requested_mode,
        keep_ratio=1.0,
        tokens_saved=0,
        kept_line_ratio=1.0,
        compression_risk="high",
        confidence=0.0,
        content_type=industrial.profile.format,
        fail_open=True,
        reasons=[reason],
        receipt={
            "schema_version": "1",
            "engine": "tameru",
            "policy": "local-fail-open",
            "query_hash": hashlib.sha256(
                (query_as_given or "").encode("utf-8", errors="surrogatepass")
            ).hexdigest()[:12],
            "savings_pct": 0.0,
            "risk": "high",
            "content_hint": content_hint,
            "industrial": industrial.to_dict(),
        },
    )
    assert fail_result.receipt is not None
    fail_result.receipt.update(
        _receipt_hashes(
            caller_text,
            caller_text,
            industrial,
            mode=requested_mode,
            strategy=strategy,
            budget_ratio=budget_ratio,
            citations=citations,
        )
    )
    return fail_result


def _industrial_preflight(
    *,
    adapter_gap,
    caller_text,
    degraded,
    degraded_view,
    industrial_query,
    limits,
    no_table,
    query,
):
    """Run the industrial preflight (size and safety limits, format adapters), degrading to a bounded scoring view when allowed, and preflight any wrapped tool payload. Returns ``(industrial, degraded, payload_industrial)``."""
    industrial = industrial_preprocess(
        caller_text, industrial_query, limits, gap_marker=adapter_gap,
        allow_reports=not no_table,
    )
    if (
        industrial.hard_fail_open
        and degraded_view
        and industrial.profile.limit_reason.startswith(
            ("character limit", "line limit")
        )
        and len(caller_text)
        <= industrial.limits.max_input_chars * _DEGRADED_OVERSIZE_FACTOR
        and industrial.profile.lines
        <= industrial.limits.max_lines * _DEGRADED_OVERSIZE_FACTOR
        and len(query or "") <= industrial.limits.max_query_chars
    ):
        # JEV-style degrade: keep size limits as a throughput guard, but let
        # the scorer see a bounded per-block view instead of refusing.
        # Safety gates preflight skipped (bidi controls, malformed
        # surrogates, oversize query) are re-verified here and stay hard.
        controls, overrides, malformed = unicode_safety_counts(caller_text)
        lim = industrial.limits
        if (
            not malformed
            and controls <= lim.max_bidi_controls
            and overrides <= lim.max_bidi_overrides
        ):
            industrial = replace(
                industrial,
                hard_fail_open=False,
                reason=f"degraded scoring view: {industrial.reason}",
            )
            degraded = True
    payload_industrial = None
    if not industrial.hard_fail_open:
        candidate_payload = unwrap_tool_payload(caller_text)
        if candidate_payload.wrapped:
            payload_industrial = industrial_preprocess(
                candidate_payload.inner, industrial_query, industrial.limits,
                gap_marker=adapter_gap, allow_reports=not no_table, reports_only=True,
            )
            if payload_industrial.hard_fail_open:
                industrial = replace(
                    industrial, hard_fail_open=True,
                    reason='tool payload: ' + payload_industrial.reason,
                    format_result=payload_industrial.format_result,
                )
    return industrial, degraded, payload_industrial


def _verify_and_adjust_risk(
    *,
    anchor_lines,
    compressed,
    derived_terms,
    fail_open,
    original_tokens,
    query,
    recall,
    risk,
    route_hint,
    structural_exit=False,
    text,
):
    """Run the post-compression verifier (diagnostic only) and fold its risk and score in; a derived or error-anchored objective never rates 'low'. Returns (verifier, risk, recall).

    ``structural_exit`` (1.10.0): the result is the structural fold, which counts repeats instead of dropping them; the verifier's
    critical-line tally cannot read ``[×N]`` and would rate every folded log "high", so its risk does not raise the fold's own."""
    verifier = None
    if not fail_open and compressed and original_tokens > 50:
        if route_hint == "numbered_code":
            # the gutter ("12: ") is not content: it must not read as key: value
            verifier = verify_compression(
                "\n".join(_GUTTER_RE.sub("", ln, count=1) for ln in text.split("\n")),
                "\n".join(_GUTTER_RE.sub("", ln, count=1) for ln in compressed.split("\n")),
                query or "",
            )
        else:
            verifier = verify_compression(text, compressed, query or "")
        risk_order = {"low": 0, "medium": 1, "high": 2}
        verifier_risk = str(verifier.get("risk", "high"))
        if risk_order.get(verifier_risk, 2) > risk_order.get(risk, 2) and not structural_exit:
            risk = verifier_risk
        recall = min(recall, float(verifier.get("score", 0.0)))
    # An inferred objective is advisory context, not caller intent — a
    # derived query never earns a "low" compression-risk rating.
    if (derived_terms or anchor_lines) and risk == "low":
        risk = "medium"
    return verifier, risk, recall


def _log_error_retention(
    *,
    compressed,
    content_type,
    fail_open,
    risk,
    text,
):
    """For content routed as a log, count the level-tagged error fingerprints that survive and raise the risk when any are lost. Returns (log_error_retention, risk)."""
    log_error_retention: dict[str, int] | None = None
    if content_type == "log" and not fail_open and compressed:
        want = {
            fp for fp, ex in error_fingerprints(text).items() if _is_level_error_line(ex)
        }
        if want:
            have = set(error_fingerprints(compressed))
            log_error_retention = {"total": len(want), "kept": len(want & have)}
            if log_error_retention["kept"] < log_error_retention["total"]:
                lost_all = log_error_retention["kept"] == 0
                risk = "high" if lost_all else (risk if risk == "high" else "medium")
    return log_error_retention, risk


def _kept_line_ratio(
    *,
    kept,
    lines,
    scored,
):
    """The share of lines covered by kept blocks. Returns line_keep."""
    line_keep = 0
    if lines:
        kept_line_idx = set()
        for b in scored:
            if b["id"] in kept:
                for i in range(b["start"], b["end"] + 1):
                    kept_line_idx.add(i)
        line_keep = len(kept_line_idx) / max(1, len(lines))
    return line_keep


def _score_with_degraded_view(
    *,
    blocks,
    content_type,
    degraded,
    query,
    score_lines,
):
    """Optionally replace each block's scoring text with a bounded head+tail view (output stays byte-exact), then score the blocks. Returns scored."""
    if degraded:
        # Score a bounded head+tail view per block. _render emits exact
        # spans from `lines`, and citation digests use `full_text`, so the
        # judge sees the shrink while output stays byte-exact.
        for b in blocks:
            full = b["text"]
            if len(full) > _DEGRADED_VIEW_HEAD + _DEGRADED_VIEW_TAIL + 64:
                b["full_text"] = full
                omitted = len(full) - _DEGRADED_VIEW_HEAD - _DEGRADED_VIEW_TAIL
                b["text"] = (
                    f"{full[:_DEGRADED_VIEW_HEAD]}\n"
                    f"[… {omitted} chars omitted …]\n"
                    f"{full[-_DEGRADED_VIEW_TAIL:]}"
                )
    scored = _score_blocks_memo(
        score_lines, blocks, query or "", content_type, degraded=degraded
    )
    return scored


def _recursion_noop_result(
    *,
    caller_text,
    requested_mode,
):
    """The no-op result for input that is already compressed (recursion guard)."""
    tokens = estimate_tokens(caller_text)
    return CompressResult(
        compressed_text=caller_text,
        original_tokens=tokens,
        kept_tokens=tokens,
        tokens_saved_pct=0.0,
        policy_name="local-noop-recursion",
        mode=requested_mode,
        keep_ratio=1.0,
        tokens_saved=0,
        kept_line_ratio=1.0,
        compression_risk="low",
        confidence=1.0,
        fail_open=True,
        reasons=["input already compressed (recursion guard)"],
    )


def _reuse_probe_or_none(
    *,
    anchor_lines,
    caller_query="",
    cache_prefix,
    caller_text,
    ccr,
    ccr_dir,
    chosen_probe,
    decision_cache,
    log_dir,
    query_as_given,
    strategy,
    summary_endpoint,
):
    """Reuse the result of the probe that chose the objective when the call allows it. Returns None when the normal path must run."""
    probe_ccr = bool(ccr) and (strategy or "extract").strip().lower() == "extract"
    if (
        _REUSE_PROBE_RESULT
        and chosen_probe is not None
        and (not ccr or probe_ccr)
        and not cache_prefix
        and decision_cache is None
        and log_dir is None
        and summary_endpoint is None
    ):
        reused = _finalize_reused_probe(chosen_probe, query_as_given, anchor_lines)
        if anchor_lines:
            reused = _rebase_anchored(reused, caller_text, caller_query)
        if ccr and isinstance(chosen_probe.ccr, dict) and chosen_probe.ccr.get("deferred"):
            try:
                info = _ccr_store(caller_text, ccr_dir)
            except OSError:
                info = None
            if info is not None:
                return dataclasses.replace(reused, ccr=info)
            # Store refused/failed — fall through to the normal path, which
            # retries the store and strips the marker on failure.
        else:
            return reused
    return None


def _compress_context_impl(
    context: str,
    query: str | Iterable[str],
    *,
    mode: str = "adaptive",
    budget_ratio: Optional[float] = None,
    ccr: bool = True,
    cache_prefix: bool = False,
    citations: bool = True,
    ccr_dir: str | Path = DEFAULT_CCR_DIR,
    decision_cache: Optional[dict] = None,
    strategy: str = "extract",
    ambiguity_fail_open: bool = False,
    reorder_best: bool = False,
    semantic_tier: Any = None,
    log_dir: str | Path | None = None,
    pin_patterns: Optional[list[str]] = None,
    pin_recent: int = 0,
    min_savings_ratio: float = 0.10,
    degraded_view: bool = False,
    summary_endpoint: str | None = None,
    summary_models: Iterable[str] | str | None = None,
    summary_timeout: float | None = None,
    summary_allow_remote: bool | None = None,
    limits: IndustrialLimits | None = None,
    derive_query: bool = False,
    anchor_errors: bool = False,
    prose_brief: bool = False,
    gap_marker: Callable[[int, int], str] | None = None,
    recursion_markers: Iterable[str] = (),
    content_hint: str | None = None,
    inline_short_gaps: bool = False,
    selector_query: str | None = None,
    _ccr_defer: bool = False,
    _internal_sample: bool = False,
) -> CompressResult:
    """Query-aware extractive compression of ``context``.

    New in 1.4.0 (all optional, defaults keep 1.3.x behaviour):
    ``prose_brief`` (1.6.0, opt-in)
        With no usable query (empty or filler, no derived or error-anchored objective) on content routed
        as ``text``, keep a structure-preserving extractive brief instead of failing open: the first and
        last block, the first paragraph of every repeat group (exact repeats modulo digits, case and whitespace — script-agnostic, so CJK needs no word segmentation; a paragraph differing by any word is never collapsed) and any repeat that carries data
        (amounts, percentages, ids, long numbers, decimals, dates). Risk is at least ``medium``;
        receipts mark ``query_source="prose-brief"``. Over 90% kept still fails open.

    ``gap_marker(omitted_chars, total_chars) -> str``
        Replaces every gap marker the renderer emits when ``citations=False``
        — including a leading gap (kept text starts after line 0) and a
        trailing gap — with the caller's own marker text. ``omitted_chars`` is
        the length of the dropped span (its lines joined with ``"\\n"``),
        ``total_chars`` the length of ``context``. Adjacent dropped blocks
        yield exactly one marker. ``None`` keeps the historical ``[…]``.
    ``recursion_markers``
        Extra strings that mark input as already compressed: if any line of
        the input starts with one (after ``lstrip``) the call is a no-op with
        ``policy_name="local-noop-recursion"``. Matching is explicit and
        anchored; nothing is guessed (a host's own marker text only counts if
        the caller passes it).
    ``content_hint``
        One of ``None, "code", "numbered_code", "log", "json", "text",
        "diff", "grep", "test"`` (anything else raises ``ValueError``).
        ``"code"``/``"numbered_code"`` skip the CSV/TSV/YAML paths and route
        as code so function bodies survive (``"log"`` skips them too: a log is
        never a table); ``"numbered_code"`` additionally
        means each line carries a ``N\\t`` or ``N|`` gutter, which stays in the
        output and is ignored for scoring. ``"log"``/``"json"``/``"text"``
        force that routing. ``"diff"``/``"grep"``/``"test"`` are recorded in
        the receipt and otherwise behave like ``None``. The hint is always
        recorded in ``receipt["content_hint"]``.

    ``inline_short_gaps`` (1.4.1)
        With ``gap_marker`` set, a dropped span whose marker would not be
        shorter than the span itself is kept verbatim instead. Off by
        default: 1.4.0 output is unchanged byte for byte.
    """
    caller_text = str(context or "")
    if not isinstance(query, str):
        # PAACE-style plan awareness: a sequence of upcoming-task strings is
        # scored as a union — a term from any planned step counts. A scalar
        # (a lone int, a datetime, 0/False) is coerced rather than iterated:
        # the generator form would exhaust on the second join downstream.
        # The iter() probe separates non-iterables from a broken iterator —
        # whose mid-iteration TypeError must reach the caller, not silently
        # produce a compaction for the iterator's repr. Steps join with a
        # space so a one-word step ('build') never starts a line and reads
        # as a tool-call command downstream.
        try:
            _q_it = iter(query) if query is not None else iter(())
        except TypeError:
            query = str(query)
        else:
            query = " ".join(str(part) for part in _q_it if part)
    if limits is not None and not isinstance(limits, IndustrialLimits):
        raise TypeError(
            f"limits must be an IndustrialLimits instance, got {type(limits).__name__}"
        )
    if content_hint is not None and (
        not isinstance(content_hint, str) or content_hint not in _CONTENT_HINTS
    ):
        raise ValueError(
            f"unknown content_hint {content_hint!r} "
            f"(expected None or one of {', '.join(sorted(_CONTENT_HINTS))})"
        )
    if gap_marker is not None and not callable(gap_marker):
        raise TypeError("gap_marker must be callable as gap_marker(omitted_chars, total_chars)")
    if inline_short_gaps and gap_marker is not None and not _inlines_short(gap_marker):
        gap_marker = InliningGapMarker(gap_marker)
    code_hint = content_hint in _CODE_HINTS
    no_table = content_hint in _NO_TABLE_HINTS
    recursion_markers = _marker_tuple(recursion_markers)  # a generator is read once
    query, query_as_given, derived_terms, anchor_lines, chosen_probe = _resolve_objective(
        ambiguity_fail_open=ambiguity_fail_open, anchor_errors=anchor_errors,
        budget_ratio=budget_ratio, caller_text=caller_text, ccr=ccr, ccr_dir=ccr_dir,
        citations=citations, content_hint=content_hint, degraded_view=degraded_view,
        derive_query=derive_query, gap_marker=gap_marker, inline_short_gaps=inline_short_gaps,
        limits=limits, min_savings_ratio=min_savings_ratio, mode=mode, pin_patterns=pin_patterns,
        pin_recent=pin_recent, prose_brief=prose_brief, query=query,
        recursion_markers=recursion_markers, reorder_best=reorder_best, semantic_tier=semantic_tier,
        strategy=strategy,
    )
    # 1.10.0: the caller's own words, as the confidence basis reads them (before anchors or derived terms), and the
    # query cut to the terms the text contains when it has many (a tool call plus a long user message).
    caller_query = "" if _is_filler_query(query_as_given) else (query_as_given or "")
    if not anchor_lines and not derived_terms and caller_query:
        caller_query = _prune_query(caller_query, caller_text)
        query = caller_query
    # 1.10.0 (S5, E4): ``selector_query`` is the GATE for the destructive selector pre-filters
    # (CSV rows, flat records, JSON crush, filler comments, log template selection): when the
    # caller supplies one that carries no distinctive selectors, none of those stages runs — a
    # producing call's terms alone never delete a line. When they do run they select on the FULL
    # ``query`` (user terms and the producing call's terms), so a line that only matches a call
    # term is kept. ``selector_query=None`` gates on ``query`` itself, as before. Scoring,
    # selection and confidence always use ``query``.
    gated_query = query if selector_query is None or query_has_distinctive_selectors(selector_query) else ""
    reused_result = _reuse_probe_or_none(
        anchor_lines=anchor_lines, caller_query=caller_query, cache_prefix=cache_prefix, caller_text=caller_text, ccr=ccr,
        ccr_dir=ccr_dir, chosen_probe=chosen_probe, decision_cache=decision_cache, log_dir=log_dir,
        query_as_given=query_as_given, strategy=strategy, summary_endpoint=summary_endpoint,
    )
    if reused_result is not None:
        return reused_result
    requested_mode, mode_norm, pin_recent, min_savings_ratio = _normalise_options(
        min_savings_ratio=min_savings_ratio,
        mode=mode,
        pin_recent=pin_recent,
    )
    # Recursion guard (Claude Code teardown inspired): Tameru output fed
    # back as input would nest wrappers and could drop the CCR pointer
    # that makes earlier drops recoverable. Refuse to compact our own
    # output — the caller already has the compacted form.
    # Recursion and secret screens also judge the unwrapped payload: inside a
    # JSON tool envelope a marker can hide behind a ``[`` escape and a
    # line-start credential behind a ``\n`` escape.
    unwrapped_payload = unwrap_tool_payload(caller_text).inner
    if (
        any(marker in caller_text for marker in _RECURSION_MARKERS)
        or (
            unwrapped_payload != caller_text
            and any(marker in unwrapped_payload for marker in _RECURSION_MARKERS)
        )
        or (_DEFAULT_ELISION_LINE.search(caller_text) is not None and not _internal_sample)
        or (_has_anchored_marker(caller_text, recursion_markers))
    ):
        return _recursion_noop_result(
            caller_text=caller_text,
            requested_mode=requested_mode,
        )
    secret_in_input = _contains_secret(caller_text) or (
        unwrapped_payload != caller_text and _contains_secret(unwrapped_payload)
    )
    savings_gate = False
    degraded = False
    # content_hint code/numbered_code (and log): the caller says what this is,
    # so the format adapters (CSV/TSV/YAML row and subtree selection, which
    # treat code with commas or colons — or a log with "12:00:00,123"
    # timestamps — as a table) must not run. An empty selector query makes the
    # adapter decline; the query-size limit is still enforced by passing the
    # real query when it is over the limit.
    industrial_query = gated_query or ""
    if no_table and len(industrial_query) <= (limits or IndustrialLimits()).max_query_chars:
        industrial_query = ""
    # v1.4.0 (E8 completion): adapter cuts carry the caller's marker; the
    # total they report is always the caller's original length.
    adapter_gap = (
        None
        if gap_marker is None
        else (
            InliningGapMarker(lambda omitted, _total, kind="other": call_gap_marker(
                gap_marker, omitted, len(caller_text), kind))
            if _inlines_short(gap_marker)
            else (lambda omitted, _total, kind="other": call_gap_marker(
                gap_marker, omitted, len(caller_text), kind))
        )
    )
    original_text = _norm_newlines(caller_text)
    # 1.10.0 (S5, E5): the protected fact lines and the density flag are computed on the caller's
    # original text — the unwrapped payload when the caller wrapped it — BEFORE the industrial and
    # format adapters below may delete a line, so protection knows every fact before any stage can
    # drop one. Density (sparsity rule B) is decided once here; ``_FACT_OFF`` keeps the machinery
    # off through every later stage on a dense original.
    protected_source = unwrap_tool_payload(original_text).inner
    # One split shared by both protection passes (S7): the fact memo and the break
    # scan each used to split the same text — a second line-objects copy at 1M.
    protected_lines = protected_source.split("\n")
    n_protected_chars = len(protected_source)
    fact_lines, fact_dense = (
        _fact_summary_lines(protected_lines)
        if n_protected_chars <= _MEMO_MAX_CHARS
        else _fact_lines_uncached(protected_lines)
    )
    _FACT_OFF.set(fact_dense)
    # Stream-break lines (a trailing status/footer of a templated dump, its one or two
    # anomalous rows) get the same selection-floor protection as S5 facts: they are not
    # fact-shaped, so the floor pool below merges them in explicitly.
    break_lines = _stream_break_lines(protected_lines, n_protected_chars)
    outcome_lines = _outcome_lines(protected_lines, n_protected_chars)
    del protected_lines
    # 1.10.0 (S5, E6): protected error exemplars — first line per error fingerprint of the same
    # original text, before any destructive stage — are exempt from the selector pre-filters and
    # adapters below (independent of ``fact_dense``). Kept as a position-ordered tuple so the
    # restores append in original line order, deterministically.
    _ERR_PROTECTED.set(tuple(
        _protected_error_exemplars(protected_source)
    ))
    # 1.10.0 (E12): outcome/landmark lines get the same stage exemption — the
    # selector pre-filters, flat-records, filler-comments and log folds below
    # consult ``_outcome_protected_set`` and keep a protected line verbatim.
    _OUTCOME_PROTECTED.set(frozenset(f[3] for f in outcome_lines))
    industrial, degraded, payload_industrial = _industrial_preflight(
        adapter_gap=adapter_gap, caller_text=caller_text, degraded=degraded,
        degraded_view=degraded_view, industrial_query=industrial_query, limits=limits,
        no_table=no_table, query=query,
    )
    if industrial.hard_fail_open:
        return _preflight_fail_open_result(
            budget_ratio=budget_ratio, caller_text=caller_text, citations=citations,
            content_hint=content_hint, industrial=industrial, query_as_given=query_as_given,
            requested_mode=requested_mode, strategy=strategy,
        )
    source_pin_texts = _source_pin_texts(caller_text, pin_patterns, pin_recent)
    _PINNED_LINES.set(frozenset(
        form for part in source_pin_texts for ln in part.split("\n") if ln.strip()
        for form in (ln, strip_ansi(ln))
    ))
    industrial_text = industrial.text if industrial.applied else caller_text
    text = strip_ansi(_norm_newlines(industrial_text))
    # v1.4.0 (G9): keep the wrapper's scalar metadata (exit_code, error,
    # total_lines, ...) so it can be re-emitted ahead of the compressed body.
    tool_payload = unwrap_tool_payload(text)
    text = tool_payload.inner
    if payload_industrial is not None and payload_industrial.applied:
        text = payload_industrial.text
    tool_meta_line = ""
    if tool_payload.wrapped and tool_payload.meta:
        tool_meta_line = _compact_json(tool_payload.meta) + "\n"
    # v1.4.0 (E4): an un-hinted numbered read (`cat -n`, Hermes `N|`) is code,
    # judged on the unwrapped payload: no table detector, no supersession, the
    # gutter kept in the output but out of the scorer's view. `route_hint` is
    # what the engine routes by; the receipt still records the caller's hint.
    # A "code" hint on a numbered read means the same thing: the gutter must
    # not count as code (it made blank source lines non-blank and split
    # function bodies at the cut).
    route_hint = content_hint
    if route_hint in (None, "code") and is_numbered_code(text):
        route_hint = "numbered_code"
        code_hint = True
        no_table = True
    # 1.10.0 (S5, E5): the industrial and payload adapters above ran before detection could see
    # the original — any protected fact line they deleted goes back now, verbatim.
    text = _restore_facts(fact_lines, text, before=protected_source)
    # v1.4.0 (E5): diff and grep/rg output get their own adapters (whole hunks,
    # grouped matches) ahead of generic segmentation. The adapter's output is
    # the selection: scoring below must not undo it (see `adapter_info`).
    text, adapter_info = _select_format_adapter(
        adapter_gap=adapter_gap, caller_text=caller_text, content_hint=content_hint,
        industrial=industrial, payload_industrial=payload_industrial, query=gated_query,
        route_hint=route_hint, text=text,
    )
    # 1.10.0 (S5, E5): the format-adapter path is also a destructive stage — a protected fact
    # line it cut goes back here too, so it can reach selection and the floor. When a record
    # adapter (diff hunks, grep groups, whole YAML documents, report formats) claimed the text
    # its whole-record cut stands: splicing a single fact line back would corrupt the records,
    # so only the still line-structured outcomes get the line-level restore.
    if adapter_info is None or adapter_info.get("name") == "test_output":
        text = _restore_facts(fact_lines, text, before=protected_source)
    if not text.strip():
        return CompressResult(
            compressed_text="", policy_name="noop", mode=requested_mode
        )
    ambiguity_fail_open = bool(ambiguity_fail_open)

    text, adapter_info = _preprocess_for_selectors(
        adapter_gap=adapter_gap,
        adapter_info=adapter_info,
        code_hint=code_hint,
        no_table=no_table,
        query=gated_query,
        text=text,
    )

    # Strategy ladder:
    #   'clear'     — drops tool-result payloads before scoring (regex-only,
    #                 zero LLM cost). Cheapest.
    #   'extract'   — default. Query-aware block scoring.
    #   'summarise' — calls a configurable OpenAI-compatible local LLM to
    #                 produce a faithful summary. Falls back to 'extract'
    #                 on any LLM failure (model down, timeout, empty response).
    #                 Highest quality, highest cost.
    strategy_norm = (strategy or "extract").strip().lower()
    if strategy_norm not in {"clear", "extract", "summarise", "auto"}:
        raise ValueError(
            f"unknown strategy {strategy!r} (expected clear/extract/summarise/auto)"
        )

    if strategy_norm == "auto":
        return _compress_auto_ladder(
            ambiguity_fail_open=ambiguity_fail_open, anchor_errors=anchor_errors,
            budget_ratio=budget_ratio, cache_prefix=cache_prefix, caller_text=caller_text, ccr=ccr,
            ccr_dir=ccr_dir, citations=citations, content_hint=content_hint,
            decision_cache=decision_cache, degraded_view=degraded_view, derive_query=derive_query,
            gap_marker=gap_marker, limits=limits, log_dir=log_dir,
            min_savings_ratio=min_savings_ratio, pin_patterns=pin_patterns, pin_recent=pin_recent,
            prose_brief=prose_brief, inline_short_gaps=inline_short_gaps,
            query_as_given=query_as_given, recursion_markers=recursion_markers,
            reorder_best=reorder_best, requested_mode=requested_mode, semantic_tier=semantic_tier,
            summary_allow_remote=summary_allow_remote, summary_endpoint=summary_endpoint,
            summary_models=summary_models, summary_timeout=summary_timeout,
        )

    if strategy_norm == "clear":
        text = _clear_tool_payloads(text)
    elif strategy_norm == "summarise":
        summary_result = _summarise_result_or_none(
            budget_ratio=budget_ratio, caller_text=caller_text, ccr=ccr, ccr_dir=ccr_dir,
            citations=citations, content_hint=content_hint, industrial=industrial,
            original_text=original_text, query=query, query_as_given=query_as_given,
            requested_mode=requested_mode, secret_in_input=secret_in_input,
            source_pin_texts=source_pin_texts, strategy=strategy,
            summary_allow_remote=summary_allow_remote, summary_endpoint=summary_endpoint,
            summary_models=summary_models, summary_timeout=summary_timeout, text=text,
            tool_meta_line=tool_meta_line,
        )
        if summary_result is not None:
            return summary_result
        # LLM failed or returned a longer result — fall through to extract.
        strategy_norm = "extract"

    lines, content_type, recall_base = _split_into_lines(
        adapter_info=adapter_info,
        code_hint=code_hint,
        industrial=industrial,
        prose_brief=prose_brief,
        query=gated_query,
        route_hint=route_hint,
        text=text,
    )
    # 1.10.0: the structural pass has run (inside _split_into_lines). When the objective is empty, filler or
    # absent from the text and the fold alone clears min_savings_ratio, scoring is skipped (early exit).
    if (
        not _PINNED_LINES.get()
        and adapter_info is None and content_type == "log" and not code_hint and route_hint != "numbered_code"
        and query_has_distinctive_selectors(query or "") and _objective_is_empty_or_absent(query, original_text)
    ):
        # An objective that names nothing present in the text selects nothing: the log is read through the
        # structural pass alone (the query-driven collapse would only guess), so the fold is the same one the
        # early exit returns and a second run over its own output changes nothing.
        lines = structural_log_pass(_compact_progress_lines(text.split("\n")))
        recall_base = "\n".join(lines)
    exit_lines = _structural_exit_lines(
        adapter_info=adapter_info, ambiguity_fail_open=ambiguity_fail_open, code_hint=code_hint,
        content_type=content_type, decision_cache=decision_cache, degraded=degraded, lines=lines,
        min_savings_ratio=min_savings_ratio, mode_norm=mode_norm, no_table=no_table,
        original_text=original_text, prose_brief=prose_brief, query=query, route_hint=route_hint,
        text=text,
    )
    structural_exit = exit_lines is not None
    if structural_exit:
        lines = exit_lines
    else:
        # Built-in anchors: a generic or absent objective on a log that carries errors is steered by the
        # error regions themselves (existing error fingerprints; no extra probe run).
        built_in = _builtin_anchor_lines(
            adapter_info=adapter_info, anchor_lines=anchor_lines, code_hint=code_hint,
            content_type=content_type, degraded=degraded, derived_terms=derived_terms,
            mode_norm=mode_norm, query=query, route_hint=route_hint, text=text,
        )
        if built_in:
            anchor_lines = built_in
            query = "\n".join(built_in)
            # 1.10.0 (S5, E4): ``query`` just became the built-in anchors — re-gate so the
            # second pre-filter pass sees the same query it would have without
            # ``selector_query`` (the anchor text), instead of the stale original.
            gated_query = query if selector_query is None or query_has_distinctive_selectors(selector_query) else ""
            lines, content_type, recall_base = _split_into_lines(
                adapter_info=adapter_info,
                code_hint=code_hint,
                industrial=industrial,
                prose_brief=prose_brief,
                query=gated_query,
                route_hint=route_hint,
                text=text,
            )
    # numbered_code: the "N\t" / "N|" gutter stays in the output (_render emits
    # `lines`) but is not part of the code the scorer should read.
    score_lines = lines
    if route_hint == "numbered_code":
        score_lines = [_GUTTER_RE.sub("", ln, count=1) for ln in lines]
    blocks = _segment_blocks_memo(score_lines)
    if len(blocks) > industrial.limits.max_blocks:
        return _block_limit_fail_open_result(
            blocks=blocks, budget_ratio=budget_ratio, caller_text=caller_text, citations=citations,
            content_hint=content_hint, industrial=industrial, query_as_given=query_as_given,
            requested_mode=requested_mode, strategy=strategy,
        )
    if structural_exit:
        # 1.10.0 early exit: the objective is empty, filler or absent from the text and the structural fold
        # already clears min_savings_ratio, so scoring cannot add anything: the fold IS the result.
        scored = [
            dict(b, score=0.0, reason="structural fold", entity_hits=0, term_hits=0, rare_term_hits=0,
                 trust_risk=False, error_exemplar=False)
            for b in blocks
        ]
        kept = {b["id"] for b in scored}
        fail_open, risk, selection = False, "medium", {"path": "structural-exit"}
        compressed, recall, structural_collapse_only = "\n".join(lines), 1.0, True
    else:
        (scored, decision_cache, kept, fail_open, risk, selection, compressed, recall,
         structural_collapse_only) = _score_select_render(
            adapter_info=adapter_info, ambiguity_fail_open=ambiguity_fail_open, blocks=blocks,
            budget_ratio=budget_ratio, caller_text=caller_text, citations=citations, code_hint=code_hint,
            content_type=content_type, decision_cache=decision_cache, degraded=degraded,
            gap_marker=gap_marker, lines=lines, mode_norm=mode_norm, no_table=no_table,
            original_text=original_text, pin_patterns=pin_patterns, pin_recent=pin_recent,
            prose_brief=prose_brief, query=query, recall_base=recall_base, reorder_best=reorder_best,
            score_lines=score_lines, semantic_tier=semantic_tier, text=text,
        )

    if fail_open:
        risk = "high"
        compressed = caller_text

    # 1.10.0 (S5): the selection floor — protected fact lines that survived preprocessing but missed
    # the selection go back as whole original lines. A fact line that never reached `lines` (a stage
    # outside the S5 exemptions removed it — e.g. the env-dump reducer stripping a secret-keyed
    # assignment) is not restored: the floor fixes selection losses, never safety deletions.
    # Never on a fail-open (the floor alone never decides the verdict): the cost gates below still
    # judge the result, so an extract plus the floor that misses min_savings_ratio fails open under
    # the existing rule.
    if not fail_open and (fact_lines or break_lines or outcome_lines):
        line_set = set(lines)
        floor_facts = [
            f for f in fact_lines
            if f[3] in line_set and not _is_trust_risk_line(f[3])
        ]
        floor_seen = {f[3] for f in floor_facts}
        floor_pool = floor_facts + [
            f for f in break_lines
            if f[3] in line_set and f[3] not in floor_seen
        ]
        floor_seen.update(f[3] for f in floor_pool)
        floor_pool += [
            f for f in outcome_lines
            if f[3] in line_set and f[3] not in floor_seen
        ]
        if floor_pool:
            budget_chars = int(budget_ratio * len(caller_text)) if budget_ratio else None
            compressed = _apply_fact_floor(
                compressed=compressed, facts=floor_pool, query=query or "",
                budget_chars=budget_chars, scored=scored, kept_ids=kept,
                min_savings_ratio=min_savings_ratio, original_text=original_text,
                adapter_info=adapter_info,
            )

    # v1.4.0 (E3): for content routed as a log, report how many level-tagged
    # error fingerprints survive. The engine keeps one exemplar per
    # fingerprint, so a loss means something upstream broke the invariant:
    # say so in the risk instead of leaving the verifier blind to it.
    log_error_retention, risk = _log_error_retention(
        compressed=compressed,
        content_type=content_type,
        fail_open=fail_open,
        risk=risk,
        text=text,
    )

    # v1.4.0 (G9): a Hermes tool wrapper ({"output": ..., "exit_code": 1, ...})
    # was reduced to its inner text above; re-emit its scalar metadata as one
    # compact JSON line so exit codes, errors and line counts survive. Only for
    # a compressed (not fail-open) result — fail-open returns the caller's
    # wrapper byte for byte.
    if tool_meta_line and not fail_open:
        compressed = tool_meta_line + compressed

    original_tokens, kept_tokens, trust_filtered, compressed, kept, fail_open, risk, savings_gate, source_pin_loss, recall = _apply_cost_gates(
        adapter_info=adapter_info, caller_text=caller_text, compressed=compressed,
        fail_open=fail_open, kept=kept, min_savings_ratio=min_savings_ratio,
        original_text=original_text, recall=recall, risk=risk, savings_gate=savings_gate,
        scored=scored, source_pin_texts=source_pin_texts,
    )

    freeze_cache_saturated = False
    if decision_cache is not None and not fail_open:
        freeze_cache_saturated = _record_freeze_decisions(decision_cache, scored, kept)

    keep_ratio = kept_tokens / max(1, original_tokens)
    line_keep = _kept_line_ratio(
        kept=kept,
        lines=lines,
        scored=scored,
    )

    reasons, risk = _collect_reasons(
        adapter_info=adapter_info, ccr=ccr, degraded=degraded, fail_open=fail_open,
        freeze_cache_saturated=freeze_cache_saturated, industrial=industrial, kept=kept,
        log_error_retention=log_error_retention, risk=risk, savings_gate=savings_gate,
        scored=scored, secret_in_input=secret_in_input, source_pin_loss=source_pin_loss,
        structural_collapse_only=structural_collapse_only,
    )
    result_text, ccr_info, compressed, kept, fail_open, risk, cache_applied, line_keep = _finalize_result_text_and_ccr(
        _ccr_defer=_ccr_defer, cache_prefix=cache_prefix, caller_text=caller_text, ccr=ccr,
        ccr_dir=ccr_dir, compressed=compressed, fail_open=fail_open, kept=kept, line_keep=line_keep,
        original_text=original_text, original_tokens=original_tokens, query_as_given=query_as_given,
        risk=risk, scored=scored, secret_in_input=secret_in_input, trust_filtered=trust_filtered,
    )

    kept_tokens = estimate_tokens(result_text)
    keep_ratio = kept_tokens / max(1, original_tokens)
    savings = round((1 - keep_ratio) * 100, 2)
    policy = f"local-{content_type}"
    if fail_open:
        policy = "local-fail-open"

    # Post-compression verifier: self-check entity/keyword/critical-line
    # recall. This is diagnostic — it does NOT modify the compressed output.
    # Callers can inspect the verifier to decide whether to re-compress with
    # a different strategy or expand dropped blocks.
    verifier, risk, recall = _verify_and_adjust_risk(
        anchor_lines=anchor_lines, compressed=compressed, derived_terms=derived_terms,
        fail_open=fail_open, original_tokens=original_tokens, query=query, recall=recall, risk=risk,
        route_hint=route_hint, structural_exit=structural_exit and not fail_open, text=text,
    )
    # 1.10.0: the confidence rests on what the objective was (never on the recall of terms the engine took from the
    # text itself, and never 1.0 from zero keys).
    basis = "none" if fail_open else _query_basis(
        caller_query, text, anchored=bool(anchor_lines), derived=bool(derived_terms),
        structural=structural_exit or structural_collapse_only or adapter_info is not None,
    )
    recall = _compute_confidence(basis=basis, compressed=compressed, fail_open=fail_open, original=text, recall=recall)
    # 1.10.0 (S5): how many protected fact lines of the original did not survive. A drop caps the
    # confidence; on an objective with no distinctive selectors each drop costs a further 0.1.
    fact_lines_dropped = _count_fact_lines_dropped(fact_lines, result_text)
    if fact_lines_dropped:
        recall = min(recall, 0.98)
        if not query_has_distinctive_selectors(caller_query):
            recall = min(recall, max(0.0, 1.0 - 0.1 * fact_lines_dropped))
    __cr = CompressResult(
        compressed_text=result_text,
        original_tokens=original_tokens,
        kept_tokens=kept_tokens,
        tokens_saved_pct=savings,
        policy_name=policy,
        mode=requested_mode,
        keep_ratio=keep_ratio,
        tokens_saved=original_tokens - kept_tokens,
        kept_line_ratio=round(line_keep, 4),
        cache_prefix_applied=cache_applied,
        compression_risk=risk,
        confidence=round(recall, 3),
        ccr=ccr_info,
        content_type=content_type,
        fail_open=fail_open,
        frozen_blocks=sum(1 for b in scored if b.get("frozen")),
        reasons=reasons,
        verifier=verifier,
        confidence_basis=basis,
        fact_lines_dropped=fact_lines_dropped,
    )

    receipt, query_hash = _build_receipt(
        adapter_info=adapter_info, anchor_lines=anchor_lines, budget_ratio=budget_ratio,
        caller_text=caller_text, citations=citations, content_hint=content_hint, degraded=degraded,
        derived_terms=derived_terms, fact_dense=fact_dense, fact_lines_dropped=fact_lines_dropped,
        fail_open=fail_open,
        industrial=industrial, kept=kept,
        log_error_retention=log_error_retention, policy=policy, query_as_given=query_as_given,
        requested_mode=requested_mode, result_text=result_text, risk=risk, savings=savings,
        scored=scored, selection=selection, strategy=strategy,
        structural_collapse_only=structural_collapse_only, verifier=verifier,
    )
    __cr.receipt = receipt

    _write_audit_log(
        fail_open=fail_open, industrial=industrial, kept=kept, log_dir=log_dir, policy=policy,
        query_hash=query_hash, risk=risk, savings=savings, scored=scored,
    )

    return __cr



_REDACT_PASSES = 3


def redact_secrets_in(text: str) -> str:
    """Replace every match of the engine's own secret patterns with ``[tameru:redacted]``.

    Deterministic and idempotent. Uses the same literal prefilter as
    :func:`contains_secret`, so text with no credential-shaped content is returned
    untouched (the same object)."""
    for _ in range(_REDACT_PASSES):
        if not _secret_scan(text):
            return text
        text = _SECRETS_RE.sub(REDACTED_MARKER, text)
        text = _SECRETS_EXTRA_RE.sub(REDACTED_MARKER, text)
    return text


def _huge_sample(text: str) -> str:
    """Streaming head/tail + error-line sample for inputs over ``_HUGE_CHARS`` (S7).

    One deterministic pass: fixed-size edges, every middle line matching a cheap
    marker check, thinned evenly to ``_HUGE_ERR_CHARS`` when over budget."""
    edge = _HUGE_EDGE_CHARS
    head, tail = text[:edge], text[-edge:]
    errs: list[str] = []
    total = 0
    for line in text[edge:len(text) - edge].splitlines():
        low = line.lower()
        if any(mark in low for mark in _HUGE_ERR_MARKERS):
            errs.append(line)
            total += len(line) + 1
    if total > _HUGE_ERR_CHARS and errs:
        step = max(1, round(total / _HUGE_ERR_CHARS))
        errs = errs[::step]
    mid = chr(10).join(errs)
    return (chr(10) + chr(91) + chr(8230) + chr(93) + chr(10)).join(part for part in (head, mid, tail) if part)


def compress_context(
    context: str,
    query: str | Iterable[str],
    *,
    mode: str = "adaptive",
    budget_ratio: Optional[float] = None,
    ccr: bool = True,
    cache_prefix: bool = False,
    citations: bool = True,
    ccr_dir: str | Path = DEFAULT_CCR_DIR,
    decision_cache: Optional[dict] = None,
    strategy: str = "extract",
    ambiguity_fail_open: bool = False,
    reorder_best: bool = False,
    semantic_tier: Any = None,
    log_dir: str | Path | None = None,
    pin_patterns: Optional[list[str]] = None,
    pin_recent: int = 0,
    min_savings_ratio: float = 0.10,
    degraded_view: bool = False,
    summary_endpoint: str | None = None,
    summary_models: Iterable[str] | str | None = None,
    summary_timeout: float | None = None,
    summary_allow_remote: bool | None = None,
    limits: IndustrialLimits | None = None,
    derive_query: bool = False,
    anchor_errors: bool = False,
    prose_brief: bool = False,
    gap_marker: Callable[..., str] | None = None,
    recursion_markers: Iterable[str] = (),
    content_hint: str | None = None,
    inline_short_gaps: bool = False,
    redact_secrets: bool = False,
    selector_query: str | None = None,
    _ccr_defer: bool = False,
    _internal_sample: bool = False,
) -> CompressResult:
    full_text = str(context or "")
    if not isinstance(query, str):
        # A scalar query (a lone int, a datetime, 0/False) is coerced, not
        # iterated — a broken iterator's mid-iteration TypeError propagates
        # instead of yielding a compaction for the iterator's repr. The
        # generator form is materialised once so the joins below and the
        # impl's union-scoring both see the same terms. Space join keeps a
        # one-word step off line-start (tool-call misdetection).
        try:
            _q_it = iter(query) if query is not None else iter(())
        except TypeError:
            query = str(query)
        else:
            query = " ".join(str(part) for part in _q_it if part)
    if limits is not None and not isinstance(limits, IndustrialLimits):
        raise TypeError(
            f"limits must be an IndustrialLimits instance, got {type(limits).__name__}"
        )
    if compile_pin_patterns(pin_patterns) is None:
        tokens = estimate_tokens(full_text)
        return _with_schema_fields(CompressResult(
            compressed_text=full_text, original_tokens=tokens, kept_tokens=tokens,
            mode=mode, fail_open=True, reasons=["unsafe_pin_patterns"],
            confidence=0.0, confidence_basis="none",
        ), full_text, query, redact_secrets, selector_query)
    # the caller query's specificity feeds the S6 calibrator through every return path (result schema 4)
    caller_query = query if isinstance(query, str) else "\n".join(str(item) for item in query)
    q_specific = query_has_distinctive_selectors(caller_query)
    if len(full_text) > _HUGE_CHARS:
        if len(full_text) > _HUGE_MAX_CHARS:
            est = _estimate_tokens(full_text)
            return CompressResult(
                compressed_text=full_text, original_tokens=est, kept_tokens=est,
                tokens_saved_pct=0.0, policy_name="huge-too-large", mode=mode,
                keep_ratio=1.0, fail_open=True, reasons=["too_large"],
                confidence=0.0, confidence_basis="none", query_specific=q_specific,
            )
        sample = _huge_sample(full_text)
        res = compress_context(
            sample, query, mode=mode, budget_ratio=budget_ratio, ccr=ccr,
            cache_prefix=cache_prefix, citations=citations, ccr_dir=ccr_dir,
            decision_cache=decision_cache, strategy=strategy,
            ambiguity_fail_open=ambiguity_fail_open, reorder_best=reorder_best,
            semantic_tier=semantic_tier, log_dir=log_dir, pin_patterns=pin_patterns,
            pin_recent=pin_recent, min_savings_ratio=min_savings_ratio,
            degraded_view=degraded_view, summary_endpoint=summary_endpoint,
            summary_models=summary_models, summary_timeout=summary_timeout,
            summary_allow_remote=summary_allow_remote, limits=limits,
            derive_query=derive_query, anchor_errors=anchor_errors,
            prose_brief=prose_brief, gap_marker=gap_marker,
            recursion_markers=recursion_markers, content_hint=content_hint,
            inline_short_gaps=inline_short_gaps, redact_secrets=redact_secrets,
            selector_query=selector_query, _ccr_defer=_ccr_defer,
            _internal_sample=True,
        )
        if res.fail_open:
            # The sampled pass declined: a fail-open's contract is that the output IS
            # the caller's input, and the sample never is — return the whole original.
            est = _estimate_tokens(full_text)
            return CompressResult(
                compressed_text=full_text, original_tokens=est, kept_tokens=est,
                tokens_saved_pct=0.0, policy_name="huge-sample-declined", mode=mode,
                keep_ratio=1.0, fail_open=True, reasons=[*res.reasons, "huge_sampled"],
                confidence=min(0.5, res.confidence) if res.confidence is not None else 0.5,
                confidence_basis="partial", query_specific=q_specific,
            )
        return dataclasses.replace(
            res, original_tokens=_estimate_tokens(full_text),
            confidence_basis="partial",
            confidence=min(0.5, res.confidence) if res.confidence is not None else 0.5,
            reasons=[*res.reasons, "huge_sampled"],
        )
    _pin_token = _PINNED_LINES.set(frozenset())
    _fact_off_token = _FACT_OFF.set(False)
    _err_token = _ERR_PROTECTED.set(())
    _out_token = _OUTCOME_PROTECTED.set(frozenset())
    try:
        result = _compress_context_impl(
        context, query,
        mode=mode, budget_ratio=budget_ratio, ccr=ccr, cache_prefix=cache_prefix,
        citations=citations, ccr_dir=ccr_dir, decision_cache=decision_cache, strategy=strategy,
        ambiguity_fail_open=ambiguity_fail_open, reorder_best=reorder_best,
        semantic_tier=semantic_tier, log_dir=log_dir, pin_patterns=pin_patterns,
        pin_recent=pin_recent, min_savings_ratio=min_savings_ratio, degraded_view=degraded_view,
        summary_endpoint=summary_endpoint, summary_models=summary_models,
        summary_timeout=summary_timeout, summary_allow_remote=summary_allow_remote,
        limits=limits, derive_query=derive_query, anchor_errors=anchor_errors,
        prose_brief=prose_brief, gap_marker=gap_marker, recursion_markers=recursion_markers,
        content_hint=content_hint, inline_short_gaps=inline_short_gaps,
        selector_query=selector_query, _ccr_defer=_ccr_defer,
        _internal_sample=_internal_sample,
        )
    except _StructuredAnchorDepthFailure:
        result = _structured_anchor_depth_noop_result(full_text, mode)
    finally:
        _PINNED_LINES.reset(_pin_token)
        _FACT_OFF.reset(_fact_off_token)
        _ERR_PROTECTED.reset(_err_token)
        _OUTCOME_PROTECTED.reset(_out_token)
    if redact_secrets and not result.fail_open:
        redacted = redact_secrets_in(result.compressed_text)
        if redacted is not result.compressed_text and redacted != result.compressed_text:
            result = replace(
                result, compressed_text=redacted, reasons=[*result.reasons, "redacted_secrets"],
            )
    out = _with_schema_fields(result, context, query, redact_secrets, selector_query)
    out.query_specific = q_specific
    return out


def _stable_key(context: str, query: str, selector_query: Any = None) -> str:
    """Same engine version, text and query: same key. Hashes, so the key leaks nothing.
    ``selector_query`` joins the hash whenever it is not ``None``."""
    digest = hashlib.sha256()
    parts = [ENGINE_VERSION, context, query]
    if selector_query is not None:
        parts.append(selector_query)
    for part in parts:
        digest.update(str(part).encode("utf-8", errors="surrogatepass"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def _with_schema_fields(
    result: CompressResult,
    context: str,
    query: Any,
    redact: bool = False,
    selector_query: Any = None,
) -> CompressResult:
    """Result schema 2+: ``stable_key`` and ``dropped`` (and both in the receipt, with ``confidence_basis``)."""
    try:
        text = context if isinstance(context, str) else str(context)
        q = query if isinstance(query, str) else chr(10).join(str(item) for item in query)
        dropped = () if result.fail_open else _dropped_summary(text, result.compressed_text, redact)
        key = _stable_key(text, q, selector_query)
    except Exception:  # a summary never costs a result
        return result
    receipt = result.receipt
    if receipt is not None:
        receipt = dict(receipt)
        receipt["dropped"] = [list(item) for item in dropped]
        receipt["confidence_basis"] = result.confidence_basis
        receipt["result_schema"] = RESULT_SCHEMA
        receipt["stable_key"] = key
    return replace(result, stable_key=key, dropped=dropped, result_schema=RESULT_SCHEMA, receipt=receipt)


compress_context.__doc__ = (_compress_context_impl.__doc__ or "") + """
    ``redact_secrets`` (1.10.0, opt-in, default False: output bytes are unchanged)
        When True, every match of the engine's own credential patterns (the ones behind
        :func:`contains_secret`) in the OUTPUT text becomes the fixed marker
        ``[tameru:redacted]``. Deterministic. It runs after the engine has decided, so it
        never changes the fail-open decision, the risk or the confidence. On a fail-open
        the original text is returned UNREDACTED (safe only because the caller already
        holds that text); a host that must never forward a credential has to check
        ``fail_open`` itself. A redacted result lists ``"redacted_secrets"`` in
        ``reasons``; counts and the receipt describe the text before redaction.

    ``gap_marker(omitted_chars, total_chars[, kind])`` (kind-aware since 1.10.0)
        A marker that declares a parameter named ``kind`` is also told what the dropped
        span is (one of ``tameru.markers.GAP_KINDS``), passed by keyword. A 2-argument
        marker is called exactly as before, and the default marker text never changes.

    ``selector_query`` (1.10.0, opt-in, default ``None``)
        The query the destructive selector pre-filters (CSV rows, flat records, JSON crush, log
        template selection) and their distinctive-selector gates read, instead of ``query``.
        Pass ``transcript.build_selector_query(...)`` — the task question without the producing
        tool call's name and arguments — so a token that only occurs in the call's arguments
        cannot decide which rows survive. Scoring, selection, and confidence still use ``query``.
        ``None`` keeps previous behaviour. When set, it also joins the ``stable_key`` hash.
    """


def main(argv: Optional[Iterable[str]] = None) -> int:
    from .cli import _parse_args

    return _run_cli(_parse_args(argv))


def _run_cli(args) -> int:
    if args.context_file == "-":
        import sys as _sys
        ctx = _sys.stdin.read()
    else:
        ctx = Path(args.context_file).read_text(encoding="utf-8-sig")
    # Resolve ccr/citations defaults (None = use library default True)
    ccr_val = True if args.ccr is None else args.ccr
    citations_val = True if args.citations is None else args.citations
    limits = IndustrialLimits(
        max_input_chars=args.max_input_chars,
        max_lines=args.max_lines,
        max_records=args.max_records,
        max_record_chars=args.max_record_chars,
        max_fields=args.max_fields,
        max_profile_chars=args.max_profile_chars,
        max_bidi_controls=args.max_bidi_controls,
        max_bidi_overrides=args.max_bidi_overrides,
        max_query_chars=args.max_query_chars,
        max_blocks=args.max_blocks,
        max_receipt_ids=args.max_receipt_ids,
    )
    # Load decision cache if provided
    decision_cache = None
    if args.decision_cache:
        dc_path = Path(args.decision_cache)
        if dc_path.is_file():
            try:
                decision_cache = json.loads(dc_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError, RecursionError):
                decision_cache = {}
            if not isinstance(decision_cache, dict):
                decision_cache = {}
        else:
            decision_cache = {}
    out = compress_context(
        ctx,
        args.query,
        mode=args.mode,
        budget_ratio=args.budget_ratio,
        ccr=ccr_val,
        cache_prefix=args.cache_prefix,
        citations=citations_val,
        decision_cache=decision_cache,
        strategy=args.strategy,
        pin_recent=args.pin_recent,
        min_savings_ratio=args.min_savings_ratio,
        degraded_view=args.degraded_view,
        derive_query=args.derive_query,
        limits=limits,
    )
    if args.stats:
        stats = out.to_dict()
        stats.pop("compressed_text", None)
        print(json.dumps(stats, indent=2))
        print("---")
    print(out.compressed_text)
    # Persist decision cache if provided
    if args.decision_cache and decision_cache is not None:
        dc_path = Path(args.decision_cache)
        _write_private_atomic(
            dc_path,
            json.dumps(decision_cache, ensure_ascii=False),
        )
    return 0
if __name__ == "__main__":
    raise SystemExit(main())