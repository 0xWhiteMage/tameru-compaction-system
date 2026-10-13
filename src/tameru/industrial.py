"""Industrial preflight, limits, profiling, and format orchestration."""
from __future__ import annotations

import functools
import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Callable

from .format_adapters import FormatLimits, FormatResult, adapt_format, detect_format
from .unicode_profile import profile_text, unicode_safety_counts


@dataclass(frozen=True)
class IndustrialLimits:
    max_input_chars: int = 8_000_000
    max_lines: int = 250_000
    max_records: int = 100_000
    max_record_chars: int = 1_000_000
    max_fields: int = 4_096
    max_profile_chars: int = 16_384
    max_bidi_controls: int = 10_000
    max_bidi_overrides: int = 128
    max_query_chars: int = 32_768
    max_blocks: int = 20_000
    max_receipt_ids: int = 512

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")

    def format_limits(self) -> FormatLimits:
        return FormatLimits(
            max_records=self.max_records,
            max_record_chars=self.max_record_chars,
            max_fields=self.max_fields,
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class InputProfile:
    characters: int
    lines: int
    format: str
    direction: str
    scripts: tuple[str, ...]
    graphemes: int
    bidi_controls: int
    bidi_overrides: int
    vertical_hint: bool
    malformed_surrogates: int
    sampled_chars: int
    profile_truncated: bool
    limit_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IndustrialResult:
    text: str
    applied: bool
    hard_fail_open: bool
    profile: InputProfile
    limits: IndustrialLimits
    format_result: FormatResult | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "hard_fail_open": self.hard_fail_open,
            "reason": self.reason,
            "profile": self.profile.to_dict(),
            "limits": self.limits.to_dict(),
            "format_result": _format_result_summary(self.format_result),
        }


def _format_result_summary(result: FormatResult | None) -> dict[str, object] | None:
    """``FormatResult.to_dict()`` without the text itself.

    The receipt is audit metadata that hosts log and store. The adapter's text
    is the whole input (or its reduction): copying it there duplicated every
    input (up to the 8 MB limit) and put credentials from lines the output had
    dropped into a field nobody screens. The length and digest identify it.
    """
    if result is None:
        return None
    summary = result.to_dict()
    text = str(summary.pop("text", "") or "")
    summary["text_chars"] = len(text)
    summary["text_sha256"] = hashlib.sha256(
        text.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return summary


def _profile_sample(text: str, max_profile_chars: int) -> tuple[str, bool]:
    if len(text) <= max_profile_chars * 2:
        return text, False
    return text[:max_profile_chars] + text[-max_profile_chars:], True


_PROFILE_MEMO_MIN_CHARS = 2048
_PROFILE_MEMO_MAX_CHARS = 1_000_000  # larger texts are not pinned in the cache


@functools.lru_cache(maxsize=6)
def _profile_input_cached(value: str, resolved: IndustrialLimits) -> InputProfile:
    return _profile_input(value, resolved)


def profile_input(text: str, limits: IndustrialLimits | None = None) -> InputProfile:
    # Perf (v1.5.0): the profile (an immutable record) of a large text is
    # computed once per (text, limits); a retry of the same output reuses it.
    if type(text) is str and _PROFILE_MEMO_MIN_CHARS <= len(text) <= _PROFILE_MEMO_MAX_CHARS:
        return _profile_input_cached(text, limits or IndustrialLimits())
    return _profile_input(text, limits)


def _profile_input(text: str, limits: IndustrialLimits | None = None) -> InputProfile:
    value = str(text or "")
    resolved = limits or IndustrialLimits()
    line_count = value.count("\n") + (1 if value else 0)
    limit_reason = ""
    if len(value) > resolved.max_input_chars:
        limit_reason = (
            f"character limit exceeded: {len(value)} > {resolved.max_input_chars}"
        )
    elif line_count > resolved.max_lines:
        limit_reason = f"line limit exceeded: {line_count} > {resolved.max_lines}"
    sample, truncated = _profile_sample(value, resolved.max_profile_chars)
    unicode = profile_text(sample)
    if not limit_reason:
        controls, overrides, malformed = unicode_safety_counts(value)
        unicode = replace(
            unicode,
            bidi_controls=controls,
            bidi_overrides=overrides,
            malformed_surrogates=malformed,
        )
        if controls > resolved.max_bidi_controls:
            limit_reason = (
                f"bidi control limit exceeded: {controls} > "
                f"{resolved.max_bidi_controls}"
            )
        elif overrides > resolved.max_bidi_overrides:
            limit_reason = (
                f"bidi override limit exceeded: {overrides} > "
                f"{resolved.max_bidi_overrides}"
            )
    return InputProfile(
        characters=len(value),
        lines=line_count,
        format=detect_format(sample),
        direction=unicode.direction,
        scripts=tuple(sorted(unicode.scripts)),
        graphemes=unicode.grapheme_count,
        bidi_controls=unicode.bidi_controls,
        bidi_overrides=unicode.bidi_overrides,
        vertical_hint=unicode.vertical_hint,
        malformed_surrogates=unicode.malformed_surrogates,
        sampled_chars=len(sample),
        profile_truncated=truncated,
        limit_reason=limit_reason,
    )


def industrial_preprocess(
    text: str,
    query: str,
    limits: IndustrialLimits | None = None,
    *,
    gap_marker: Callable[[int, int], str] | None = None,
) -> IndustrialResult:
    value = str(text or "")
    resolved = limits or IndustrialLimits()
    profile = profile_input(value, resolved)
    if len(str(query or "")) > resolved.max_query_chars:
        reason = (
            f"query character limit exceeded: {len(str(query or ''))} > "
            f"{resolved.max_query_chars}"
        )
        return IndustrialResult(
            text=value,
            applied=False,
            hard_fail_open=True,
            profile=profile,
            limits=resolved,
            reason=reason,
        )
    if profile.limit_reason:
        return IndustrialResult(
            text=value,
            applied=False,
            hard_fail_open=True,
            profile=profile,
            limits=resolved,
            reason=profile.limit_reason,
        )
    if profile.malformed_surrogates:
        return IndustrialResult(
            text=value,
            applied=False,
            hard_fail_open=True,
            profile=profile,
            limits=resolved,
            reason="malformed surrogate code point detected",
        )
    format_result = adapt_format(
        value,
        query,
        resolved.format_limits(),
        format_name=profile.format,
        gap_marker=gap_marker,
    )
    if not format_result.structurally_valid:
        return IndustrialResult(
            text=value,
            applied=False,
            hard_fail_open=True,
            profile=profile,
            limits=resolved,
            format_result=format_result,
            reason=format_result.reason or "malformed structured input",
        )
    if format_result.applied and len(format_result.text) < len(value):
        return IndustrialResult(
            text=format_result.text,
            applied=True,
            hard_fail_open=False,
            profile=profile,
            limits=resolved,
            format_result=format_result,
            reason=format_result.reason,
        )
    return IndustrialResult(
        text=value,
        applied=False,
        hard_fail_open=False,
        profile=profile,
        limits=resolved,
        format_result=format_result,
        reason=format_result.reason,
    )
