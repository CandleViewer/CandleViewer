"""Handler-level redaction filter for structured logging (M24, E04-T01).

Implements SR-120..SR-124 (`docs/plan/04-security-program.md` §6.9) and
mitigates threat K1/U5 (`docs/plan/threat-models/E04-observability.md` row
L4): a secret written to any logger, anywhere, must never reach stdout.

Two layers of defence, both required (belt and braces per the ticket's
Technical notes):

1. `RedactionProcessor` — a `structlog` processor, applied to every
   `structlog` logger's event dict.
2. `RedactionFilter` — a stdlib `logging.Filter` attached directly to the
   root handler, so records from third-party stdlib loggers (`httpx`,
   `websockets`, `sqlalchemy`, `pybit`) that never touch structlog are still
   scrubbed. This is the filter that a new call site cannot bypass, because
   nothing reaches stdout without passing through the root handler.

Both layers share the same matching engine (`_redact_value`/`_redact_mapping`)
so there is exactly one rule set to keep in sync (the ticket's "freezes the
redaction rule set" language in the Context section).
"""

from __future__ import annotations

import re
from typing import Any, Final

from candleviewer.observability.secret_type import Secret

#: Exact key names redacted regardless of value shape (case-insensitive).
#: Frozenset membership test — O(1), no regex, per the ticket's cost-control
#: note.
_REDACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "cookie",
        "set-cookie",
        "authorization",
        "x-bapi-sign",
        "x-bapi-api-key",
        "totp",
        "recovery_code",
        "session",
        "csrf",
    }
)

#: Maximum string length scanned for value-shape patterns. Longer values are
#: truncated with a marker *before* scanning so one huge payload cannot stall
#: the redaction loop (Technical notes cost-control paragraph).
_MAX_SCAN_LEN: Final[int] = 4096

#: Maximum recursion depth into nested dicts/lists. Deeper structures (or a
#: cyclic one) are replaced wholesale rather than recursed into.
_MAX_DEPTH: Final[int] = 6

#: A single pre-compiled alternation covering: Exchange-style API key/secret
#: charsets (long alphanumeric runs), JWT-like `xx.yy.zz` triples, and a
#: 6-digit code (TOTP shape) — all fairly permissive because the *label*
#: (key-name check above) already carries most of the recall.
_JWT_RE = r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
_APIKEY_RE = r"\b[A-Za-z0-9]{18,36}\b"
_TOTP_RE = r"\b\d{6}\b"
#: `secrets.token_urlsafe(32)` invite token (43 chars; sits in URL path `/invites/<token>`; C-12.6).
_INVITE_SHAPE_RE = r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"
_VALUE_PATTERN = re.compile(
    f"(?P<jwt>{_JWT_RE})|(?P<apikey>{_APIKEY_RE})|(?P<invite>{_INVITE_SHAPE_RE})"
    f"|(?P<totp>{_TOTP_RE})"
)

_REASON_BY_GROUP: Final[dict[str, str]] = {
    "jwt": "jwt-shape",
    "apikey": "key-shape",
    "totp": "totp-shape",
    "invite": "invite-token-shape",
}


def _is_redact_key(key: object) -> bool:
    return isinstance(key, str) and key.strip().lower() in _REDACT_KEYS


def _redact_str_value(value: str) -> str:
    """Scan a string for value-shape secrets; return it redacted if matched.

    A 6-digit TOTP is only redacted by shape when found alongside a
    totp-ish neighbour is impractical to detect at this granularity (we do
    not have sibling-key context inside a bare string), so the key-name path
    is the primary control for TOTP and this shape check is a defence-in-
    depth catch for TOTP codes appearing inside free-form text (e.g. an
    exception message that echoes user input).
    """
    if len(value) > _MAX_SCAN_LEN:
        value = value[:_MAX_SCAN_LEN] + "...[truncated:oversize]"

    match = _VALUE_PATTERN.search(value)
    if match is None:
        return value
    group = match.lastgroup
    reason = _REASON_BY_GROUP.get(group or "", "value-shape")
    return f"[redacted:{reason}]"


def _redact_value(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[redacted:depth]"
    if isinstance(value, Secret):  # E27-T02: Secret never renders, whatever it wraps
        return "***"
    if isinstance(value, str):
        return _redact_str_value(value)
    if isinstance(value, dict):
        return _redact_mapping(value, depth + 1)
    if isinstance(value, (list, tuple)):
        redacted = [_redact_value(item, depth + 1) for item in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


def _redact_mapping(mapping: dict[Any, Any], depth: int = 0) -> dict[Any, Any]:
    if depth > _MAX_DEPTH:
        return {"_": "[redacted:depth]"}
    out: dict[Any, Any] = {}
    for key, value in mapping.items():
        if _is_redact_key(key):
            out[key] = "[redacted:key-name]"
        else:
            out[key] = _redact_value(value, depth)
    return out


def redact_text(value: str) -> str:
    """Public: redact a free-form string using the shared rule set."""
    return _redact_str_value(value)


def redact_structure(value: Any) -> Any:
    """Public: redact any JSON-like structure using the shared rule set."""
    return _redact_value(value, 0)
