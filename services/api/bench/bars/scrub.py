"""Report scrubber: no session cookie, token or credential reaches an artefact (C-12.6)."""

from __future__ import annotations

import re

_HEADER = re.compile(
    r"(?im)^(\s*(?:set-)?cookie|\s*authorization|\s*x-[a-z0-9-]*(?:api-key|sign|signature|token))"
    r"\s*:.*$"
)
# `name`, optional closing quote (JSON keys), separator, then a quoted or bare value. The
# lookbehind (not `\b`) lets `cv_session=` match while `inside=` does not.
_NAMES = (
    r"session(?:[_-]?id)?|sid|csrf[_-]?token|access[_-]?token|refresh[_-]?token|token"
    r"|api[_-]?key|api[_-]?secret|secret|signature|password|passwd|dek|kek|totp|otp"
)
_PAIR = re.compile(rf"(?i)(?<![A-Za-z0-9])({_NAMES})(\"?\s*[:=]\s*)(?:\"[^\"]*\"|[^\s\",;&]+)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL
)

REDACTED = "[REDACTED]"


def scrub(text: str) -> str:
    text = _PEM.sub(REDACTED, text)
    text = _HEADER.sub(lambda m: f"{m.group(1).strip()}: {REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    return _PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
