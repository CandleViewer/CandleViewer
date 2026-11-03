"""Report scrubber: no session cookie, token or credential reaches an artefact (Security notes)."""

from __future__ import annotations

import re

_HEADER = re.compile(
    r"(?im)^(\s*(?:set-)?cookie|\s*authorization|\s*x-[a-z0-9-]*(?:api-key|sign|signature|token))"
    r"\s*:.*$"
)
_PAIR = re.compile(
    r"(?i)\b(session(?:[_-]?id)?|csrf[_-]?token|access[_-]?token|refresh[_-]?token|token"
    r"|api[_-]?key|secret|signature|password)\b(\s*[:=]\s*)(\"?)[^\s\",;&]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")

REDACTED = "[REDACTED]"


def scrub(text: str) -> str:
    text = _HEADER.sub(lambda m: f"{m.group(1).strip()}: {REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    return _PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}", text)
