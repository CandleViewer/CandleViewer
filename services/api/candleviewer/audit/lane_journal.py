"""Journal-first audit lane: frame codec, parse order and marker (ADR-0037, slice S1a).

`docs/plan/24-internal-schemas.md` §15.6 owns the format and the parse order (C-16.5); this module
implements them and restates neither. It is pure: no I/O, clock or log. The scan and quarantine
follow at the ADR's S1a seam; appends, segments and quotas are S1b's. No error message carries a
key, a MAC or a record.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from candleviewer.audit.errors import AuditError

#: §15.6 Limits. It bounds the whole encoded frame; a larger one fails parse step (1).
MAX_FRAME_BYTES = 64 * 1024
KEY_BYTES = 32
ZERO_MAC = "0" * 64

_FRAME, _MARKER = b"cv-audit-lane/v1/frame\n", b"cv-audit-lane/v1/marker\n"
_LEN, _MAC = re.compile(rb"[1-9][0-9]{0,9}"), re.compile(rb"[0-9a-f]{64}")
_HEX64, _KID = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{16}")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_FRAME_KEYS = {"v", "lane", "seq", "prev", "kid", "cls", "rec"}
_MARKER_KEYS = {"v", "lane", "pos", "next_seq", "prev", "anchored", "kid"}

Pos = tuple[int, int]  # a segment's `first_seq` and a byte offset, as in the marker's `pos`
Framed = tuple[int, bytes, bytes, dict[str, Any]]  # parse steps (1)-(2): end, body, mac, object
Refused = Literal["hold", "frame_rejected"]


class LaneError(AuditError):
    """Base of the lane journal's errors."""


class LaneKeyInvalid(LaneError):
    def __init__(self) -> None:
        super().__init__(f"an audit lane key must be exactly {KEY_BYTES} bytes")


class LaneFrameTooLarge(LaneError):
    reason = "too_large"  # the appender's refusal (S1b)

    def __init__(self, size: int) -> None:
        super().__init__(f"an audit lane frame of {size} bytes exceeds {MAX_FRAME_BYTES}")


def key_id(key: bytes) -> str:
    return hmac.new(key, b"cv-audit-lane/v1/kid", hashlib.sha256).digest()[:8].hex()


class LaneKeys:
    """`current` makes frames, markers, notes and anomaly ids; `previous` only verifies. The key
    bytes never leave this object, and `repr` shows key ids only (U41)."""

    __slots__ = ("_current", "_keys", "current_kid")

    def __init__(self, current: bytes, previous: bytes | None = None) -> None:
        if any(len(key) != KEY_BYTES for key in (current, previous) if key is not None):
            raise LaneKeyInvalid
        self._current, self.current_kid = current, key_id(current)
        self._keys = {key_id(key): key for key in (previous, current) if key is not None}

    def __repr__(self) -> str:
        return f"LaneKeys(kids={sorted(self._keys)})"

    def __contains__(self, kid: object) -> bool:
        return isinstance(kid, str) and kid in self._keys

    def sign(self, label: bytes, body: bytes) -> bytes:
        return _hmac(self._current, label, body)

    def verify(self, kid: object, label: bytes, body: bytes, mac: bytes) -> bool:
        """On bytes, so a malformed tag fails and never raises `TypeError` (#3114)."""
        key = self._keys.get(kid) if isinstance(kid, str) else None
        return key is not None and hmac.compare_digest(_hmac(key, label, body), mac)


def _hmac(key: bytes, label: bytes, body: bytes) -> bytes:
    return hmac.new(key, label + body, hashlib.sha256).hexdigest().encode("ascii")


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("ascii")


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        obj = json.loads(raw.decode("ascii"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return None
    return obj if isinstance(obj, dict) else None


def _text(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _int(value: object, least: int) -> bool:
    return type(value) is int and value >= least  # never a boolean or "1"


@dataclass(frozen=True, slots=True)
class LaneFrame:
    """An authentic frame; `rec` stays opaque until hand-over."""

    lane: uuid.UUID
    seq: int
    prev: str
    kid: str
    cls: Literal["reserved", "shared"]
    rec: dict[str, Any]
    mac: str


def encode_frame(
    keys: LaneKeys,
    *,
    lane: uuid.UUID,
    seq: int,
    prev: str,
    cls: Literal["reserved", "shared"],
    rec: dict[str, Any],
) -> bytes:
    envelope = {"v": 1, "lane": str(lane), "seq": seq, "prev": prev, "cls": cls, "rec": rec}
    body = _canonical(envelope | {"kid": keys.current_kid})
    frame = b"%d\n%s\n%s\n" % (len(body), body, keys.sign(_FRAME, body))
    if len(frame) > MAX_FRAME_BYTES:
        raise LaneFrameTooLarge(len(frame))
    return frame


def decode_frame(
    keys: LaneKeys, data: bytes, *, lane: uuid.UUID | None = None
) -> LaneFrame | Refused | None:
    """The frame that is exactly `data`; None when it does not parse (steps 1 and 2)."""
    framed = _framed(data, 0)
    return None if framed is None or framed[0] != len(data) else _classify(keys, framed, lane)


def _framed(data: bytes, pos: int) -> Framed | None:
    nl = data.find(b"\n", pos, pos + 11)
    if nl < 0 or not _LEN.fullmatch(data, pos, nl):
        return None
    body_end = nl + 1 + int(data[pos:nl])
    end = body_end + 66
    if (
        end - pos > MAX_FRAME_BYTES
        or end > len(data)
        or data[body_end] != 0x0A
        or data[end - 1] != 0x0A
        or not _MAC.fullmatch(data, body_end + 1, end - 1)
    ):
        return None
    body = data[nl + 1 : body_end]
    obj = _json_object(body)
    return None if obj is None else (end, body, data[body_end + 1 : end - 1], obj)


def _authenticate(
    keys: LaneKeys, label: bytes, body: bytes, mac: bytes, obj: dict[str, Any]
) -> bool | None:
    """Parse steps (3) and (4); None holds: a well-formed `v` or `kid` that is not configured."""
    v, kid = obj.get("v"), obj.get("kid")
    if (type(v) is int and v != 1) or (_text(kid, _KID) and kid not in keys):
        return None
    return keys.verify(kid, label, body, mac)


def _classify(keys: LaneKeys, framed: Framed, lane: uuid.UUID | None) -> LaneFrame | Refused:
    """Steps (3) to (6). Without a lane (the scan's row 3) step (5) is skipped."""
    _end, body, mac, obj = framed
    ok = _authenticate(keys, _FRAME, body, mac, obj)
    if ok is None:
        return "hold"
    if (
        not ok
        or obj.keys() != _FRAME_KEYS
        or not _int(obj["v"], 1)  # an integer other than 1 held at step (3)
        or not _text(obj["lane"], _UUID)
        or (lane is not None and obj["lane"] != str(lane))
        or not _int(obj["seq"], 1)
        or not _text(obj["prev"], _HEX64)
        or (obj["seq"] == 1 and obj["prev"] != ZERO_MAC)
        or obj["cls"] not in ("reserved", "shared")
        or not isinstance(obj["rec"], dict)
    ):
        return "frame_rejected"
    fields = (obj["seq"], obj["prev"], obj["kid"], obj["cls"], obj["rec"])
    return LaneFrame(uuid.UUID(obj["lane"]), *fields, mac.decode("ascii"))


@dataclass(frozen=True, slots=True)
class LaneMarker:
    """The body of `confirmed`: the scan state at `pos`, the end of the last confirmed unit."""

    lane: uuid.UUID
    pos: Pos
    next_seq: int
    prev: str
    anchored: bool


def encode_marker(keys: LaneKeys, marker: LaneMarker) -> bytes:
    fields = {"next_seq": marker.next_seq, "prev": marker.prev, "anchored": marker.anchored}
    ids = {"v": 1, "lane": str(marker.lane), "pos": list(marker.pos), "kid": keys.current_kid}
    body = _canonical(fields | ids)
    return body + b"\n" + keys.sign(_MARKER, body) + b"\n"


def _unseal(data: bytes) -> tuple[bytes, bytes, dict[str, Any]] | None:
    """`<body>\\n<mac>\\n`, the format of the marker and of the `released` note."""
    body, mac = data[:-66], data[-65:-1]
    if data[-66:-65] != b"\n" or data[-1:] != b"\n" or b"\n" in body or not _MAC.fullmatch(mac):
        return None
    obj = _json_object(body)
    return None if obj is None else (body, mac, obj)


def decode_marker(keys: LaneKeys, data: bytes) -> LaneMarker | Literal["hold"] | None:
    """A verifiable marker; `"hold"` for a well-formed `v` or `kid` not configured; else None."""
    sealed = _unseal(data)
    ok = None if sealed is None else _authenticate(keys, _MARKER, *sealed)
    if sealed is None or ok is None:
        return None if sealed is None else "hold"
    obj = sealed[2]
    pos = obj.get("pos")
    if (
        not ok
        or obj.keys() != _MARKER_KEYS
        or not _int(obj["v"], 1)
        or not (isinstance(pos, list) and len(pos) == 2)
        or not (_int(pos[0], 1) and _int(pos[1], 0) and _int(obj["next_seq"], 1))
        or not _text(obj["prev"], _HEX64)
        or type(obj["anchored"]) is not bool
        or not _text(obj["lane"], _UUID)
    ):
        return None
    state = (obj["next_seq"], obj["prev"], obj["anchored"])
    return LaneMarker(uuid.UUID(obj["lane"]), (pos[0], pos[1]), *state)
