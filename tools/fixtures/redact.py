"""Fixture redactor (E08-T05): strip credential-shaped content from captured frames.

Applied by `capture_fixture.py` to every raw frame *before* it touches disk, so a
capture can never commit an API key, HMAC signature, account/UID id or auth
header (security notes threat 1; C-2.7, C-12.6). Patterns mirror
`scripts/check_secrets_hygiene.py` and `packages/fixtures/scripts/verify.mjs`
(the gates that re-scan the committed corpus) and widen them to identifiers.

It finds a secret by key name and value shape only, so it assumes a public-stream capture
(`capture_fixture.py` dials only Bybit's public stream), whose frames carry no account data.
It is not enough for a private-stream capture (`order`, `execution`, `position`, `wallet`):
those frames carry order and execution ids, balances and sizes under names it does not list.
One would need an allow-list of the fields its tests read instead of this deny-list, stable
fake ids, and a field-by-field review before commit (C-13.5).
"""

from __future__ import annotations

import re

REDACTED = "REDACTED"

#: JSON string fields whose *value* is always dropped, whatever it looks like.
_SENSITIVE_KEYS = (
    "api_key|apiKey|api-key|api_secret|apiSecret|secret|sign|signature|token|password"
    "|uid|userId|user_id|accountId|account_id|subUid|sub_uid|parentUid|memberId"
)
_JSON_FIELD = re.compile(rf'("(?:{_SENSITIVE_KEYS})"\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d+)', re.I)
#: Bybit v5 auth headers and generic auth headers, in `k: v` / `k=v` / JSON form.
_HEADER = re.compile(
    r"((?:X-BAPI-(?:API-KEY|SIGN|SIGN-TYPE|TIMESTAMP|RECV-WINDOW)|Authorization|Cookie)"
    r'["\']?\s*[:=]\s*["\']?)([^"\'\r\n,}]+)',
    re.I,
)
#: Bare query-string credentials (`?api_key=...&sign=...`).
_QUERY = re.compile(r"((?:[?&])(?:api_key|sign|signature|token)=)([^&\s\"']+)", re.I)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
#: A free-standing 64-hex run is the shape of a Bybit HMAC-SHA256 signature.
_HEX_SIG = re.compile(r"\b[a-fA-F0-9]{64}\b")


def redact(text: str) -> str:
    """Return `text` with every credential-shaped value replaced by `REDACTED`."""
    out = _PEM.sub(REDACTED, text)
    out = _JSON_FIELD.sub(lambda m: f'{m.group(1)}"{REDACTED}"', out)
    out = _HEADER.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    out = _QUERY.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    return _HEX_SIG.sub(REDACTED, out)


def find_leaks(text: str) -> list[str]:
    """Names of the patterns still matching `text` (empty == clean)."""
    checks = {
        "pem": _PEM,
        "json-field": _JSON_FIELD,
        "header": _HEADER,
        "query": _QUERY,
        "bearer": _BEARER,
        "hex-signature": _HEX_SIG,
    }
    leaks: list[str] = []
    for name, rx in checks.items():
        for m in rx.finditer(text):
            value = m.group(m.lastindex) if m.lastindex else m.group(0)
            if REDACTED not in value:
                leaks.append(name)
                break
    return leaks
