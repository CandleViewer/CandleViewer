"""Fail-closed redaction of an exchange message before `order_events.payload` stores it (#845).

`21-database-schema.md` Sec.3.3.5 keeps the raw exchange message "redacted of credentials", and
`order_events` is append-only and kept for good (C-5.7), so a credential stored once could never be
removed. This is the fail-closed pass before insert of SR-E29-08 in the E29 STRIDE model (#849;
the adapter's allow-listed record is the other pass, E29-T04): `orders_sqlalchemy` runs it on
every payload before binding it, so no writer can skip it. It only removes or replaces, and it
returns plain JSON.

Replaced by `REDACTED`:

* the value of a credential name (`key`, `sign`, `signature`, `api_key`, `secret`, `token`, `auth`,
  `authorization`, `cookie`, `password`, `passphrase`, `session`, `recv_window`, ...), compared
  lower-cased without separators, so `apiKey`, `API-KEY` and `api_key` are one name;
* every header: the value of `headers` or `header`, and of any key that starts with `x-` or `x_`,
  where request-signing headers live;
* the `args` of an `{"op": "auth"}` frame, where a key, an expiry and a MAC travel by position;
* the query of a URL; a query string naming a credential; and a string holding a credential-shaped
  run, 18 or more ASCII letters and digits with at least one of each (an API key, a secret, a hex
  MAC), outside an `OUR_ID` or `EXT_ID` (24 Sec.8.3). Ids, numbers and words pass, CamelCase enum
  values such as reject reasons included;
* a non-finite number, text `jsonb` refuses (NUL, a lone surrogate) and any value that is not
  JSON (bytes, sets, objects); a `Decimal` becomes its string.

Keys that are not strings, that `jsonb` refuses or that are credential-shaped are dropped. A
string over `MAX_STRING_CHARS`, an integer past 64 bits, a container over `MAX_ITEMS` entries and
nesting past `MAX_DEPTH` become `OVERSIZE`, and a result whose JSON exceeds `MAX_PAYLOAD_CHARS` is
replaced whole by `{"redacted": OVERSIZE}`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final

from candleviewer.domain.order_link import EXT_ID, OUR_ID

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None

REDACTED: Final = "[redacted]"
OVERSIZE: Final = "[redacted:oversize]"
MAX_DEPTH: Final = 8
MAX_ITEMS: Final = 256
MAX_STRING_CHARS: Final = 2048
MAX_PAYLOAD_CHARS: Final = 16384

#: Credential names, compared after `_name()`: exact matches, then fragments anywhere in the name.
_NAMES: Final = frozenset({"key", "sign", "auth", "session", "recvwindow", "headers", "header"})
_FRAGMENTS: Final = (
    "apikey", "secret", "signature", "token", "password", "passphrase", "privatekey",
    "authorization", "cookie", "credential",
)  # fmt: skip
_HEADER_KEY: Final = re.compile(r"[xX][-_]")
_URL_QUERY: Final = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*://|/)[^\s?#]*\?")
_PARAM: Final = re.compile(r"(?:^|[?&;])\s*([A-Za-z0-9_.-]{1,64})=")
#: Both `ord_link_fmt` arms, unanchored: masked before the shape scan, so an id is never a key.
_IDS: Final = re.compile(f"{OUR_ID.pattern[1:-1]}|{EXT_ID.pattern[1:-1]}")
_RUN: Final = re.compile(r"[A-Za-z0-9]{18,}")


def _name(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _credential_name(key: str) -> bool:
    name = _name(key)
    return (
        name in _NAMES or any(f in name for f in _FRAGMENTS) or _HEADER_KEY.match(key) is not None
    )


def _storable(text: str) -> bool:
    """`jsonb` refuses NUL and lone surrogates, and either would fail the whole write."""
    return not any(c == "\x00" or "\ud800" <= c <= "\udfff" for c in text)


def _credential_shaped(text: str) -> bool:
    return any(not run.isalpha() and not run.isdigit() for run in _RUN.findall(_IDS.sub("-", text)))


def _string(text: str) -> str:
    if len(text) > MAX_STRING_CHARS:
        return OVERSIZE
    if not _storable(text):
        return REDACTED
    url = _URL_QUERY.match(text)
    if url is not None:
        text = text[: url.end()] + REDACTED
    if any(_credential_name(p) for p in _PARAM.findall(text)) or _credential_shaped(text):
        return REDACTED
    return text


def _value(value: object, depth: int) -> JsonValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if value.bit_length() <= 64 else OVERSIZE
    if isinstance(value, float):
        return value if math.isfinite(value) else REDACTED
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else REDACTED
    if isinstance(value, str):
        return _string(value)
    if not isinstance(value, Mapping | list | tuple):
        return REDACTED
    if depth >= MAX_DEPTH or len(value) > MAX_ITEMS:
        return OVERSIZE
    if isinstance(value, Mapping):
        return _mapping(value, depth)
    return [_value(item, depth + 1) for item in value]


def _mapping(value: Mapping[Any, object], depth: int) -> dict[str, JsonValue]:
    """`value` sits `depth` containers deep; its entries one deeper."""
    op = value.get("op")
    auth_frame = isinstance(op, str) and _name(op) == "auth"
    out: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _storable(key) or _credential_shaped(key):
            continue
        if _credential_name(key) or (auth_frame and key == "args"):
            out[key] = REDACTED
        else:
            out[key] = _value(item, depth + 1)
    return out


def redact_exchange_payload(raw: Mapping[str, object]) -> dict[str, JsonValue]:
    """A redacted, JSON-safe copy of `raw`; `raw` itself is never changed."""
    if not isinstance(raw, Mapping):
        return {"redacted": REDACTED}
    out: dict[str, JsonValue] = (
        _mapping(raw, 0) if len(raw) <= MAX_ITEMS else {"redacted": OVERSIZE}
    )
    if len(json.dumps(out, allow_nan=False)) > MAX_PAYLOAD_CHARS:
        return {"redacted": OVERSIZE}
    return out
