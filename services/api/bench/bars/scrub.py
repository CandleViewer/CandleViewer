"""Report scrubber: no session cookie, token or credential reaches an artefact (C-12.6)."""

from __future__ import annotations

import re

# Only `[ \t]` separates tokens below: `\s` also matches newlines, which backtracks badly on
# long runs of blank lines (a regression test pins linear time).
_HEADER = re.compile(
    r"(?im)^([ \t]*(?:set-)?cookie|[ \t]*authorization"
    r"|[ \t]*x-[a-z0-9-]*(?:api-key|sign|signature|token))[ \t]*:.*$"
)
_NAMES = (
    r"session(?:[_-]?id)?|sid|csrf[_-]?token|access[_-]?token|refresh[_-]?token|token"
    r"|api[_-]?key|api[_-]?secret|secret|signature|password|passwd|dek|kek|totp|otp"
)
# name, optional closing quote (JSON keys), separator, then a quoted value (escaped quotes
# allowed, single or double; group 3), an unterminated quote, or a bare value. The
# lookbehind (not `\b`) lets `cv_session=` match while `inside=` does not.
_PAIR = re.compile(
    rf"""(?i)(?<![A-Za-z0-9])({_NAMES})(["']?[ \t]*[:=][ \t]*)"""
    r"""(?:("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|["'][^\n]*|[^\s"',;&]+)"""
)
_BEARER = re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL
)

REDACTED = "[REDACTED]"


def _pair(m: re.Match[str]) -> str:
    quoted = m.group(3)  # a quoted value keeps its quote marks, so redacted JSON stays valid
    q = quoted[0] if quoted else ""
    return f"{m.group(1)}{m.group(2)}{q}{REDACTED}{q}"


def scrub(text: str) -> str:
    text = _PEM.sub(REDACTED, text)
    text = _HEADER.sub(lambda m: f"{m.group(1).strip()}: {REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    return _PAIR.sub(_pair, text)
