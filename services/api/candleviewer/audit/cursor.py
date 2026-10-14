"""Opaque keyset cursor for `GET /admin/audit` (contract #2392, design D4).

The cursor names the position of the last entry returned, `(ts, id)` in the
`(event_ts DESC, id DESC)` order: base64url (no padding) of the compact JSON
`{"v":1,"ts":"<UTC, microseconds>","id":n}`, at most `CURSOR_MAX_LEN` characters.

It is not signed and does not expire, because it grants nothing: it carries no
scope and no filters, and the caller's scope and filters are applied again on
every page. A forged cursor can only move the start position. Only the exact
form this module issues is accepted; anything else raises `InvalidAuditCursor`
(`400 invalid_cursor`), whose message never quotes the input.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from candleviewer.audit.errors import AuditError

CURSOR_MAX_LEN = 512
_VERSION = 1
_ID_MAX = 2**63 - 1  # bigint
_ALPHABET = re.compile(r"[A-Za-z0-9_-]+")


class InvalidAuditCursor(AuditError):
    """The cursor is not one this server issued (`400 invalid_cursor`)."""

    def __init__(self) -> None:
        super().__init__("cursor is not one this server issued")


@dataclass(frozen=True, slots=True)
class AuditCursor:
    """Position of the last entry returned: `event_ts` (tz-aware) and `id`."""

    ts: datetime
    id: int


def encode_cursor(position: AuditCursor) -> str:
    ts = position.ts.astimezone(UTC).isoformat(timespec="microseconds")
    body = json.dumps({"v": _VERSION, "ts": ts, "id": position.id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(body.encode("ascii")).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> AuditCursor:
    """The position in `token`, or `InvalidAuditCursor` for anything this module did not
    issue: wrong length, alphabet or JSON, another version, extra keys, a naive or non-UTC
    `ts`, or an `id` outside 1..2^63-1. The issued form is canonical, so a decoded cursor
    must re-encode to the same token."""
    if len(token) > CURSOR_MAX_LEN or not _ALPHABET.fullmatch(token):
        raise InvalidAuditCursor
    try:
        position = _parse(json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))))
        if position is not None and encode_cursor(position) == token:
            return position
    except (binascii.Error, ValueError, OverflowError):
        pass  # the decode error can quote the input; it is not kept (`from None` below)
    raise InvalidAuditCursor from None


def _parse(data: object) -> AuditCursor | None:
    if not isinstance(data, dict) or set(data) != {"v", "ts", "id"}:
        return None
    version, ts, entry_id = data["v"], data["ts"], data["id"]
    if type(version) is not int or version != _VERSION or type(entry_id) is not int:
        return None
    if not 1 <= entry_id <= _ID_MAX or not isinstance(ts, str):
        return None
    parsed = datetime.fromisoformat(ts)
    return AuditCursor(parsed, entry_id) if parsed.tzinfo is not None else None
