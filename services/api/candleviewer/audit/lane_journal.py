"""Journal-first audit lane (ADR-0037; S1a-S1c): codec, marker, scan, appends, quotas, drain I/O.

`docs/plan/24-internal-schemas.md` §15.6 owns the format, the parse order, the scan table and the
quarantine rules (C-16.5); this module implements them and restates none. It is pure: no I/O,
clock or log, except the appender: `LaneFiles` does the file I/O, and `LaneJournal` runs
it in worker threads under the lane lock. No error
message carries a key, a MAC or a record, and no `repr` a key or a record (U41). The envelope is
checked field by field, not by a pydantic model, whose lax mode would coerce `"1"` and `true` to 1.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import hmac
import json
import os
import re
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import structlog

from candleviewer.audit.actions import LANE_ACTIONS, LaneClass
from candleviewer.audit.errors import AuditError
from candleviewer.observability.context import spawn, thread_future

#: §15.6 Limits. It bounds the whole encoded frame; a larger one fails parse step (1).
MAX_FRAME_BYTES = 64 * 1024
KEY_BYTES = 32
ZERO_MAC = "0" * 64

_FRAME, _MARKER = b"cv-audit-lane/v1/frame\n", b"cv-audit-lane/v1/marker\n"
_RELEASED, _ANOMALY = b"cv-audit-lane/v1/released\n", b"cv-audit-lane/v1/anomaly\n"
_LEN, _MAC = re.compile(rb"[1-9][0-9]{0,9}"), re.compile(rb"[0-9a-f]{64}")
_HEX64, _KID = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{16}")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_SEGMENT = re.compile(r"seg-([0-9]{20})\.lane")
_SEVERITY = ("segment_corrupt", "frame_rejected", "marker_lost", "seq_gap", "torn_tail")
_FRAME_KEYS = {"v", "lane", "seq", "prev", "kid", "cls", "rec"}
_MARKER_KEYS = {"v", "lane", "pos", "next_seq", "prev", "anchored", "kid"}
_NOTE_KEYS = {"v", "lane", "hold", "end", "from_seq", "operator", "ticket", "operator_reason"}

Pos = tuple[int, int]  # a segment's `first_seq` and a byte offset, as in the marker's `pos`
Framed = tuple[int, bytes, bytes, dict[str, Any]]  # parse steps (1)-(2): end, body, mac, object
Refused = Literal["hold", "frame_rejected"]


class LaneError(AuditError):
    """Base of the lane journal's errors."""


class LaneKeyInvalid(LaneError):
    def __init__(self) -> None:
        super().__init__(f"an audit lane key must be exactly {KEY_BYTES} bytes")


LaneReason = Literal["full", "too_large", "busy", "io_error", "stopped", "held"]


class LaneRefused(LaneError):
    """An append refused with nothing written; `reason` is §15.6's closed set (the façade adds
    `timeout`)."""

    def __init__(self, reason: LaneReason, detail: str = "") -> None:
        super().__init__(f"the audit lane refused an append: {reason}{detail}")
        self.reason: LaneReason = reason


class LaneFrameTooLarge(LaneRefused):
    def __init__(self, size: int) -> None:
        super().__init__("too_large", f", a frame of {size} bytes exceeds {MAX_FRAME_BYTES}")


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
    rec: dict[str, object] = field(repr=False)
    mac: str


def encode_frame(
    keys: LaneKeys,
    *,
    lane: uuid.UUID,
    seq: int,
    prev: str,
    cls: Literal["reserved", "shared"],
    rec: dict[str, object],
) -> bytes:
    envelope = {"v": 1, "lane": str(lane), "seq": seq, "prev": prev, "cls": cls, "rec": rec}
    body = _canonical(envelope | {"kid": keys.current_kid})
    frame = b"%d\n%s\n%s\n" % (len(body), body, keys.sign(_FRAME, body))
    if len(frame) > MAX_FRAME_BYTES:
        raise LaneFrameTooLarge(len(frame))
    return frame


def decode_frame(
    keys: LaneKeys, data: bytes, *, lane: uuid.UUID | None
) -> LaneFrame | Refused | None:
    """The frame that is exactly `data`; None when it does not parse (steps 1 and 2). With
    `lane=None`, step (5) is skipped, as in the scan's row 3 before a frame sets the lane."""
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


def segment_name(first_seq: int) -> str:
    return f"seg-{first_seq:020d}.lane"


def _item(data: bytes, pos: int) -> tuple[str, int, Framed | None]:
    """The table's view at `pos`: a frame, or bytes that do not parse, up to the next line start
    whose frame passes steps (1) and (2), else to the end, where an incomplete frame is torn."""
    framed = _framed(data, pos)
    if framed is not None:
        return "frame", framed[0], framed
    nxt = data.find(b"\n", pos) + 1
    while 0 < nxt < len(data) and _framed(data, nxt) is None:
        nxt = data.find(b"\n", nxt) + 1
    if 0 < nxt < len(data):
        return "segment_corrupt", nxt, None
    nl = data.find(b"\n", pos, pos + 11)
    head = data[pos : pos + 11] if nl < 0 else data[pos:nl]
    size = len(head) + int(head) + 67 if _LEN.fullmatch(head) else MAX_FRAME_BYTES + 1
    torn = size <= MAX_FRAME_BYTES and (nl < 0 or pos + size > len(data))
    return ("torn_tail" if torn else "segment_corrupt"), len(data), None


def _pos(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and _int(value[0], 1) and _int(value[1], 0)


def _at_boundary(data: bytes, offset: int) -> bool:
    at = 0
    while at < offset:
        at = _item(data, at)[1]
    return at == offset


def _note(
    keys: LaneKeys, data: bytes, lane: uuid.UUID | None, hold: Pos
) -> tuple[Pos, tuple[str, str, str]] | None:
    """The `released` note when it applies at `hold`; with no `kid`, the current key verifies."""
    sealed = _unseal(data)
    if sealed is None or lane is None or not keys.verify(keys.current_kid, _RELEASED, *sealed[:2]):
        return None
    obj = sealed[2]
    if (
        obj.keys() != _NOTE_KEYS
        or not (_int(obj["v"], 1) and obj["v"] == 1)
        or obj["lane"] != str(lane)
        or not (_pos(obj["hold"]) and tuple(obj["hold"]) == hold)
        or not (_pos(obj["end"]) and tuple(obj["end"]) > hold)
        or not _int(obj["from_seq"], 1)
        or not all(isinstance(obj[k], str) for k in ("operator", "ticket", "operator_reason"))
    ):
        return None
    end, words = obj["end"], (obj["operator"], obj["ticket"], obj["operator_reason"])
    return (end[0], end[1]), words


@dataclass(frozen=True, slots=True)
class LaneState:
    """The marker's state besides `lane` and `pos`. `next_seq` is None only while a rescan
    without a verifiable marker has met no authentic frame."""

    next_seq: int | None
    prev: str
    anchored: bool


@dataclass(frozen=True, slots=True)
class Handover:
    """An authentic frame in sequence for `AuditWriter.ingest()`; `state` is the state after it."""

    frame: LaneFrame = field(repr=False)
    raw: bytes = field(repr=False)
    start: Pos
    end: Pos
    state: LaneState


@dataclass(frozen=True, slots=True)
class Run:
    """One `audit.lane_anomaly` row. Once it is committed the marker moves to `end` with `state`;
    `data` is copied to `quarantine/<quarantined>`, which is None when the run has no bytes."""

    reason: str
    from_seq: int | None
    to_seq: int | None
    data: bytes = field(repr=False)
    start: Pos | None
    end: Pos
    state: LaneState
    prev_unverified: bool = False
    marker_behind: bool = False
    marker_ahead: bool = False
    note: tuple[str, str, str] | None = None  # operator, ticket, operator_reason

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def quarantined(self) -> str | None:
        return None if self.start is None else f"{segment_name(self.start[0])}.{self.start[1]}"


def record_invalid(unit: Handover) -> Run:
    """The run that replaces a hand-over `ingest()` refused for good (§15.6 Ingest step 2)."""
    seq = unit.frame.seq
    return Run("record_invalid", seq, seq, unit.raw, unit.start, unit.end, unit.state)


def anomaly_id(keys: LaneKeys, lane: uuid.UUID | None, run: Run) -> uuid.UUID:
    """A run's `record_id` (§15.6 Ingest step 1), with the version (8) and variant set by hand."""
    text = None if lane is None else str(lane)
    message = _canonical([text, run.reason, run.from_seq, run.to_seq, run.digest])
    raw = bytearray.fromhex(keys.sign(_ANOMALY, message).decode("ascii")[:32])
    raw[6], raw[8] = (raw[6] & 0x0F) | 0x80, (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


@dataclass(frozen=True, slots=True)
class LaneScan:
    """`lane` is None when no marker verified and no frame was authentic (S1b decides that lane's
    fate). `hold` is the held frame's position, None when the marker holds (row 1); a present
    `released` note that did not apply sets `note_ignored`, which the drain logs."""

    lane: uuid.UUID | None
    units: tuple[Handover | Run, ...] = field(repr=False)
    state: LaneState
    held: bool
    hold: Pos | None
    note_ignored: bool
    sealed: bool  # row 16: the next append starts a new segment


@dataclass(slots=True)
class _OpenRun:
    reason: str
    from_seq: int | None
    data: bytearray = field(default_factory=bytearray)
    start: Pos | None = None
    marker_behind: bool = False
    marker_ahead: bool = False

    def add(self, reason: str, raw: bytes, at: Pos) -> None:
        if _SEVERITY.index(reason) < _SEVERITY.index(self.reason):
            self.reason = reason  # a run's reason is the most severe it holds
        if raw and self.start is None:
            self.start = at
        self.data += raw

    def close(self, to_seq: int | None, end: Pos, state: LaneState, unverified: bool) -> Run:
        data, flags = bytes(self.data), (unverified, self.marker_behind, self.marker_ahead)
        return Run(self.reason, self.from_seq, to_seq, data, self.start, end, state, *flags)


class _Scan:
    """One pass of the §15.6 table; "row n" names the row whose `#` is n."""

    def __init__(self, keys: LaneKeys, names: Iterable[str], read: Callable[[str], bytes]) -> None:
        found = sorted((int(m[1]), name) for name in names if (m := _SEGMENT.fullmatch(name)))
        self.keys, self.read, self.cache = keys, read, dict[int, bytes]()
        self.firsts, self.names = [first for first, _ in found], [name for _, name in found]
        self.lane: uuid.UUID | None = None
        self.state, self.at = LaneState(None, ZERO_MAC, False), (1, 0)
        self.lost = self.held = self.note_ignored = self.sealed = False
        self.hold: Pos | None = None
        self.run: _OpenRun | None = None
        self.units: list[Handover | Run] = []

    def data(self, i: int) -> bytes:
        if i not in self.cache:
            self.cache[i] = self.read(self.names[i])
        return self.cache[i]

    def begin(self, marker: bytes | None, trusted: bool) -> Pos | None:
        """Rows 1 to 6: the state, and the segment index and offset to scan from."""
        found = None if marker is None else decode_marker(self.keys, marker)
        if isinstance(found, str):
            self.held = True
            return None
        if found is None:
            if not self.firsts:
                return None  # no lane yet: S1b creates it
            self.lost, self.run = True, _OpenRun("marker_lost", None)  # row 3
            return 0, 0
        self.lane, self.at = found.lane, found.pos
        self.state = LaneState(found.next_seq, found.prev, found.anchored)
        first, offset = found.pos
        if first in self.firsts:
            i = self.firsts.index(first)
            if offset <= len(self.data(i)) and (trusted or _at_boundary(self.data(i), offset)):
                return i, offset
        elif not self.firsts and found.pos == (1, 0):
            return None  # row 6: a new lane before its frame 1
        elif self.firsts and self.firsts[-1] > first:  # its segment was deleted: rows 4 and 5
            if self.firsts[0] > found.next_seq:  # row 4
                self.run = _OpenRun("seq_gap", found.next_seq, marker_behind=True)
                self.state = replace(self.state, anchored=False)
            return next(i for i, f in enumerate(self.firsts) if f > first), 0
        self.lost = True  # row 2
        self.run = _OpenRun("marker_lost", found.next_seq, marker_ahead=True)
        self.state = replace(self.state, anchored=False)
        return 0, 0

    def walk(self, i: int, off: int, note: bytes | None) -> None:
        while i < len(self.firsts):
            data, self.at = self.data(i), (self.firsts[i], off)
            if off >= len(data):
                i, off = i + 1, 0
                continue
            kind, end, framed = _item(data, off)
            found = kind if framed is None else _classify(self.keys, framed, self.lane)
            if isinstance(found, LaneFrame):
                self.frame(found, data[off:end], (self.firsts[i], end))
            elif found == "hold":
                resume = self.release(i, off, note)
                if resume is None:
                    return
                i, off = resume
                continue
            else:  # rows 11, 14 and 15
                self.join(found, data[off:end], unanchor=found != "torn_tail")
            off = end
        if self.run is not None:  # row 16
            self.units.append(self.run.close(None, self.at, self.state, False))
            self.run, self.sealed = None, bool(self.firsts)

    def frame(self, frame: LaneFrame, raw: bytes, end: Pos) -> None:
        """Rows 7 to 10. A rescan without a verifiable marker starts at the first authentic frame,
        which in row 3 also sets the lane; in row 2 `next_seq` is the smaller of the marker's and
        that frame's `seq`, so row 8 puts any `seq` between them in the run."""
        if self.lost:
            self.lost, self.lane = False, frame.lane if self.lane is None else self.lane
            known = self.state.next_seq
            first = frame.seq if known is None else min(frame.seq, known)
            self.state = replace(self.state, next_seq=first)
            if self.run is not None:
                self.run.from_seq = first
        expected = frame.seq if self.state.next_seq is None else self.state.next_seq
        if frame.seq > expected:  # row 8
            self.join("seq_gap", b"", unanchor=True)
            self.state, expected = replace(self.state, next_seq=frame.seq), frame.seq
        if frame.seq != expected or (self.state.anchored and frame.prev != self.state.prev):
            self.join("frame_rejected", raw, unanchor=True)  # rows 9 and 10
            return
        if self.run is not None:  # row 7
            unverified = frame.prev != self.state.prev
            self.units.append(self.run.close(frame.seq - 1, self.at, self.state, unverified))
            self.run = None
        self.state = LaneState(frame.seq + 1, frame.mac, True)
        self.units.append(Handover(frame, raw, self.at, end, self.state))

    def join(self, reason: str, raw: bytes, *, unanchor: bool) -> None:
        if self.run is None:
            self.run = _OpenRun(reason, self.state.next_seq)
        self.run.add(reason, raw, self.at)
        if unanchor:
            self.state = replace(self.state, anchored=False)

    def release(self, i: int, off: int, note: bytes | None) -> Pos | None:
        """Rows 12 and 13: close the open run as at the end of the data, then resume after a
        `released` note's bytes if it applies here, else hold."""
        hold = self.at
        if self.run is not None:
            self.units.append(self.run.close(None, hold, self.state, False))
            self.run = None
        found = None if note is None else _note(self.keys, note, self.lane, hold)
        j = self.firsts.index(found[0][0]) if found and found[0][0] in self.firsts else -1
        if found is None or j < 0 or found[0][1] > len(self.data(j)):
            self.held, self.hold, self.note_ignored = True, hold, note is not None
            return None
        (_, stop), words = found
        span = b"".join(self.data(k) for k in range(i, j + 1))
        raw = span[off : len(span) - len(self.data(j)) + stop]
        start, self.state = self.state.next_seq, replace(self.state, anchored=False)
        to_seq = None if start is None else start - 1
        run = Run("released", start, to_seq, raw, hold, found[0], self.state, note=words)
        self.units.append(run)
        return j, stop


def scan(
    keys: LaneKeys,
    *,
    marker: bytes | None,
    names: Iterable[str],
    read: Callable[[str], bytes],
    note: bytes | None = None,
    trusted: bool = False,
) -> LaneScan:
    """The §15.6 scan from `marker` (`confirmed`, None when absent) over the segments among
    `names`, each read once through `read`, with the `released` note if one exists. `trusted`
    marks the drain's own position, a frame boundary it scanned: nothing before it is parsed."""
    run = _Scan(keys, names, read)
    start = run.begin(marker, trusted)
    if start is not None:
        run.walk(*start, note)
    units = tuple(run.units)
    return LaneScan(run.lane, units, run.state, run.held, run.hold, run.note_ignored, run.sealed)


# S1b: appends, segments, fsync point 1 (§15.6; rulings R1, R2 on #3009); S1c: quotas, points 2-4.

SEGMENT_MAX_BYTES = 1 << 20  # §15.6 Limits; the constructor overrides them in tests only
LANE_MAX_SEGMENTS = 1024
_READ_MAX = SEGMENT_MAX_BYTES + MAX_FRAME_BYTES  # longer than any file the lane writes
_STRAY = re.compile(r"confirmed\.tmp|seg-[0-9]{20}\.lane\.new")
LANE_MAX_BYTES, SHARED_MAX_BYTES = 32 << 20, 16 << 20  # S1c: the byte quotas
_BOOT_ROWS = ("audit.lane_started", "audit.lane_resumed")  # Limits: no cap refuses them
LANE_WAITERS: Mapping[LaneClass, int] = MappingProxyType({"reserved": 192, "shared": 64})
DRAIN_BATCH, CONFIRM_POLL_S, RETRY_S = 200, 0.05, (0.5, 30.0)  # S2a2: the drain's (`audit/lane.py`)


class LaneNotAdmitted(LaneError):
    """No `LANE_ACTIONS` row admits the record, or frame 1 is not `audit.lane_started`, or a later
    frame is: only the lane writes it, as a new lane's frame 1."""


def _segments(names: Iterable[str]) -> list[int]:
    return sorted(int(m[1]) for name in names if (m := _SEGMENT.fullmatch(name)))


def _open(path: Path | str, flags: int, dir_fd: int | None = None) -> int:
    return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)


def _mkdir(path: Path) -> bool:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        return False
    return True


class LaneFiles:
    """The lane's only file I/O (§15.6 Directory, fsync points): each call blocks, in a worker
    thread under the lane lock. Tests override `write`, `fsync`, `truncate` and `unlink`."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    def write(self, fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]

    def fsync(self, fd: int) -> None:
        os.fsync(fd)

    def truncate(self, fd: int, length: int) -> None:
        os.ftruncate(fd, length)

    def unlink(self, path: Path) -> None:
        os.unlink(path)

    def sync_dir(self, path: Path | None = None) -> None:
        fd = _open(path or self.dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.fsync(fd)
        finally:
            os.close(fd)

    def read(self, name: str) -> bytes:
        with os.fdopen(_open(self.dir / name, os.O_RDONLY), "rb") as file:
            data = file.read(_READ_MAX + 1)
        if len(data) > _READ_MAX:
            raise LaneError("an audit lane file is longer than any the lane writes")
        return data

    def boot(self) -> tuple[list[str], bytes | None, bytes | None]:
        """Make `lane/` if needed and remove a crash's strays; the names, marker and note."""
        if _mkdir(self.dir):
            self.sync_dir(self.dir.parent)
        names = sorted(os.listdir(self.dir))
        strays = [name for name in names if _STRAY.fullmatch(name)]
        for name in strays:
            self.unlink(self.dir / name)
        if strays:
            self.sync_dir()
        names = [name for name in names if name not in strays]
        found = {name: self.read(name) for name in ("confirmed", "released") if name in names}
        return names, found.get("confirmed"), found.get("released")

    def publish(self, seq: int, frame: bytes, max_segments: int, boot: bool) -> tuple[int, bool]:
        """fsync point 1, a new segment (R1): `.new`, its fsync, the link to the segment's name,
        which must not exist, the unlink, the directory's fsync; returns the descriptor and True
        past `max_segments` (R2), only a boot row's (Limits). A `.new` that fails publishes none."""
        path = self.dir / segment_name(seq)
        new = path.with_name(f"{path.name}.new")
        if (over := len(_segments(os.listdir(self.dir))) >= max_segments) and not boot:
            raise LaneRefused("full")
        if os.path.lexists(path):  # only damage takes the name; the link guards a race too
            raise FileExistsError(errno.EEXIST, "an audit lane segment name is taken", path.name)
        try:
            fd = _open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND)
        except OSError:
            raise LaneRefused("io_error") from None
        try:
            try:
                self.write(fd, frame)
            except OSError:
                self.unlink(new)
                raise LaneRefused("io_error") from None
            self.fsync(fd)
            os.link(new, path, follow_symlinks=False)
            self.unlink(new)
            self.sync_dir()
        except BaseException:
            os.close(fd)
            raise
        return fd, over

    def append(self, fd: int, frame: bytes, end: int) -> None:
        """fsync point 1: a failed write is cut back to `end` and fsynced (`io_error`)."""
        try:
            self.write(fd, frame)
        except OSError:
            self.truncate(fd, end)
            self.fsync(fd)
            raise LaneRefused("io_error") from None
        self.fsync(fd)

    def _put(self, path: Path | str, data: bytes, dir_fd: int | None = None) -> None:
        fd = _open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, dir_fd)
        try:
            self.write(fd, data)
            self.fsync(fd)
        finally:
            os.close(fd)

    def mark(self, body: bytes) -> None:
        """fsync point 2: `confirmed.tmp`, renamed over `confirmed`."""
        self._put(self.dir / "confirmed.tmp", body)
        os.rename(self.dir / "confirmed.tmp", self.dir / "confirmed")
        self.sync_dir()

    def compact(self, pos: Pos, active: int) -> list[int]:
        """fsync point 3: unlink each segment wholly before `pos`, never the newest or `active`
        (reading 1: the next scan would read the marker as ahead, row 2)."""
        first, offset = pos
        doomed = [
            seg
            for seg in _segments(os.listdir(self.dir))[:-1]
            if seg != active and (seg < first or (seg == first and offset >= self._size(seg)))
        ]
        for seg in doomed:
            self.unlink(self.dir / segment_name(seg))
        if doomed:
            self.sync_dir()
        return doomed

    def _size(self, seg: int) -> int:
        return os.lstat(self.dir / segment_name(seg)).st_size

    def quarantine(self, name: str, data: bytes) -> None:
        """fsync point 4; a crash's partial copy is replaced. `quarantine/` is opened without
        following a link, and the copy is made through its descriptor."""
        made = _mkdir(self.dir / "quarantine")
        dir_fd = _open(self.dir / "quarantine", os.O_RDONLY | os.O_DIRECTORY)
        try:
            self._put(name, data, dir_fd)
            self.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        if made:
            self.sync_dir()


class _LaneLock:
    """The lane lock (§15.6 Limits): `reserved` waiters are served first, and past its class's
    cap an acquire is refused at once (`busy`), never queued (C-2.18)."""

    def __init__(self, caps: Mapping[LaneClass, int]) -> None:
        self._caps, self._held = caps, False
        self._queues: dict[LaneClass, deque[asyncio.Future[None]]] = {
            "reserved": deque(),
            "shared": deque(),
        }

    async def acquire(self, cls: LaneClass, capped: bool) -> None:
        if not self._held:
            self._held = True
            return
        queue = self._queues[cls]
        if capped and len(queue) >= self._caps[cls]:
            raise LaneRefused("busy")
        waiter = asyncio.get_running_loop().create_future()
        queue.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.cancelled():
                with contextlib.suppress(ValueError):  # `release()` may have dropped it
                    queue.remove(waiter)
            else:  # granted just as it was cancelled: pass the lock on
                self.release()
            raise

    def release(self) -> None:
        for queue in self._queues.values():  # `reserved` first
            while queue:
                waiter = queue.popleft()
                if not waiter.done():
                    waiter.set_result(None)
                    return
        self._held = False


@dataclass(slots=True)
class _Op:
    """One critical section under the lane lock (#2250, the rule of `audit/writer.py`)."""

    holding: bool = False  # once set, a cancelled caller no longer releases the lock
    cancel_pending: bool = False  # cancelled during a thread call: raised once the op is done


async def _in_thread[T](op: _Op, fn: Callable[..., T], /, *args: object) -> T:
    """A blocking call, awaited to its end even if the op is cancelled meanwhile: the lock must
    outlive the thread (#2250); teardown cannot cancel a plain `thread_future`."""
    future = thread_future(fn, *args)
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            op.cancel_pending = True
    return future.result()


def _boot(files: LaneFiles, keys: LaneKeys) -> tuple[list[str], object, LaneScan]:
    names, marker, note = files.boot()
    found = None if marker is None else decode_marker(keys, marker)
    return names, found, scan(keys, marker=marker, names=names, read=files.read, note=note)


def _running_scan(files: LaneFiles, keys: LaneKeys, origin: bytes) -> LaneScan:
    names = os.listdir(files.dir)
    return scan(keys, marker=origin, names=names, read=files.read, trusted=True)


def _admit(rec: dict[str, object], *, first: bool) -> LaneClass:
    """Decision 3: the class follows the action; frame 1 is `audit.lane_started`."""
    action = str(rec.get("action"))
    row = LANE_ACTIONS.get(action)
    started = action == "audit.lane_started"
    if row is None or str(rec.get("outcome")) not in row[1] or (first and not started):
        raise LaneNotAdmitted("the audit lane registry does not admit this record here")
    if started and not first:
        raise LaneNotAdmitted("audit.lane_started is a new lane's frame 1 only")
    return row[0]


class LaneJournal:
    """The appender, and the drain's fsync points 2 to 4 (§15.6). Each file operation runs in a
    worker thread under the lane lock, which a cancelled caller never releases while a thread
    runs (#2250). `open()` boots it; a lane that holds, or segments that no authentic frame gives
    a lane (row 3), refuse every append with `held`. Every boot opens a new segment (row 16)."""

    def __init__(
        self,
        files: LaneFiles,
        keys: LaneKeys,
        *,
        segment_max_bytes: int = SEGMENT_MAX_BYTES,
        max_segments: int = LANE_MAX_SEGMENTS,
        lane_max_bytes: int = LANE_MAX_BYTES,
        shared_max_bytes: int = SHARED_MAX_BYTES,
        waiters: Mapping[LaneClass, int] = LANE_WAITERS,
    ) -> None:
        self._files, self._keys = files, keys
        self._segment_max, self._max_segments = segment_max_bytes, max_segments
        self._lane_max, self._shared_max = lane_max_bytes, shared_max_bytes
        self._bytes = self._shared = 0  # after the marker, a run's bytes too (reading 2)
        self._units: deque[tuple[Pos, int, bool]] = deque()  # (end, bytes, shared) of each
        self._end: Pos = (1, 0)  # the furthest unit end counted; no marker passes it
        self._opened = self._closed = False  # `open()` runs once; `close()` ends the drain's ops
        self.lane, self._next_seq, self._prev = uuid.UUID(int=0), 1, ZERO_MAC
        self.refusal: LaneReason | None = "stopped"  # until `open()`
        self._pos: Pos | None = None  # the verified marker's; a new lane writes its own first
        self.boot_marker: LaneMarker | None = None  # the verifiable marker the boot found
        self._fd, self._active, self._size = -1, 0, 0  # the segment the appends go to
        self._lock = _LaneLock(waiters)
        self.boot_overshoot_frames = 0  # Limits: boot rows past a cap (S4a's metric)
        self._resumed = False  # this boot's `audit.lane_resumed` is written
        self._ops: set[asyncio.Task[Any]] = set()

    async def open(self, new_lane: Callable[[], uuid.UUID] = uuid.uuid4) -> LaneScan:
        """Boot: remove a crash's strays, scan, and take the lane's state from the scan. It runs
        once, so nothing is counted twice: after a failure a retry needs a new `LaneJournal`."""
        if self._opened:
            raise LaneError("the audit lane is already open")
        self._opened = True
        return await self._run(lambda op: self._open(op, new_lane))

    async def _open(self, op: _Op, new_lane: Callable[[], uuid.UUID]) -> LaneScan:
        async with self._held(op):
            names, found, result = await _in_thread(op, _boot, self._files, self._keys)
            state, segments = result.state, _segments(names)
            self.lane = new_lane() if result.lane is None else result.lane
            self._next_seq = 1 if state.next_seq is None else state.next_seq
            self._prev, self._pos = state.prev, found.pos if isinstance(found, LaneMarker) else None
            self.boot_marker = found if isinstance(found, LaneMarker) else None
            if any(isinstance(unit, Run) and unit.marker_ahead for unit in result.units):
                self._pos = None  # row 2: no compaction until the first `confirm()`
            held = result.held or (result.lane is None and bool(segments))
            self.refusal = "held" if held else ("stopped" if self._closed else None)
            for unit in result.units:
                shared = isinstance(unit, Handover) and unit.frame.cls == "shared"
                self._count(
                    unit.end, len(unit.raw if isinstance(unit, Handover) else unit.data), shared
                )
        return result

    @property
    def fresh(self) -> bool:
        """Frame 1, `audit.lane_started`, is due."""
        return self._next_seq == 1

    @property
    def head(self) -> tuple[int, str]:
        """The newest authentic frame's `seq` and `mac`: 0 and 64 zeros before frame 1."""
        return self._next_seq - 1, self._prev

    @property
    def end(self) -> Pos:
        """The furthest unit end counted: the boot's units and every append since."""
        return self._end

    def run_id(self, lane: uuid.UUID | None, run: Run) -> uuid.UUID:
        """The `record_id` of `run`'s anomaly row, keyed under the current key (Ingest step 1)."""
        return anomaly_id(self._keys, lane, run)

    async def append(self, rec: dict[str, object]) -> int:
        """Append one record (an `AuditEmission` as JSON); its `seq` once the frame is durable.
        `LaneNotAdmitted`, `LaneRefused` (§15.6's reasons) and the `TypeError` of a record that is
        not JSON (callers pass dicts the codec built) write nothing. A refused lane answers with its
        refusal first, so a held lane whose frame 1 is due still says `held` (§15.6 Hold)."""
        if self.refusal is not None:
            raise LaneRefused(self.refusal)
        cls = _admit(rec, first=self.fresh)
        self._frame(cls, rec)  # refused at once
        return await self._run(lambda op: self._append(op, cls, rec))

    def _frame(self, cls: LaneClass, rec: dict[str, object]) -> bytes:
        if self.refusal is not None:
            raise LaneRefused(self.refusal)
        seq, prev = self._next_seq, self._prev
        frame = encode_frame(self._keys, lane=self.lane, seq=seq, prev=prev, cls=cls, rec=rec)
        size = len(frame)
        if not self._exempt(rec) and (
            self._bytes + size > self._lane_max
            or (cls == "shared" and self._shared + size > self._shared_max)
        ):
            raise LaneRefused("full")
        return frame

    def _exempt(self, rec: dict[str, object]) -> bool:
        """Limits: a boot's own rows (frame 1, its first `audit.lane_resumed`) pass the caps."""
        return rec.get("action") in _BOOT_ROWS and not self._resumed

    async def _append(self, op: _Op, cls: LaneClass, rec: dict[str, object]) -> int:
        async with self._held(op, cls, capped=True):
            _admit(rec, first=self.fresh)  # again under the lock: one frame 1 among racing appends
            frame, seq, boot = self._frame(cls, rec), self._next_seq, self._exempt(rec)
            past = boot and self._bytes + len(frame) > self._lane_max  # counted (Limits)
            try:
                if self._pos is None and seq == 1 and self.boot_marker is None:  # a new lane
                    start = LaneMarker(self.lane, (1, 0), 1, ZERO_MAC, True)  # its marker first
                    await _in_thread(op, self._files.mark, encode_marker(self._keys, start))
                    self._pos = start.pos
                if self._fd < 0 or self._size + len(frame) > self._segment_max:
                    publish, cap = self._files.publish, self._max_segments
                    fd, over = await _in_thread(op, publish, seq, frame, cap, boot)
                    past = past or over
                    self._close()
                    self._fd, self._active, self._size = fd, seq, 0
                else:
                    await _in_thread(op, self._files.append, self._fd, frame, self._size)
            except OSError as exc:  # R1's taken name among them
                self.stop(exc)
                raise LaneRefused("stopped") from None
            self._size += len(frame)
            self._next_seq, self._prev = seq + 1, frame[-65:-1].decode("ascii")
            self._count((self._active, self._size), len(frame), cls == "shared")
            self.boot_overshoot_frames += past
            self._resumed = self._resumed or rec["action"] == "audit.lane_resumed"
            _log().info(
                "audit.lane.appended", seq=seq, cls=cls, action=rec["action"], mac=self._prev[:16]
            )
        return seq

    async def confirm(self, marker: LaneMarker) -> None:
        """fsync point 2: the drain moves the marker once a unit's records are committed. A marker
        of another lane, or anywhere but the current marker or a unit end the lane counted, is
        refused, so the marker never moves back or into a unit."""
        self._require_open()
        ends = (end for end, _, _ in self._units)
        if marker.lane != self.lane or (marker.pos != self._pos and marker.pos not in ends):
            raise LaneError("the audit lane refused a marker of another lane or off its units")
        body = encode_marker(self._keys, marker)
        await self._run(lambda op: self._io(op, self._files.mark, body))
        self._pos = marker.pos
        while self._units and self._units[0][0] <= marker.pos:
            _, size, shared = self._units.popleft()
            self._bytes -= size
            self._shared -= size if shared else 0

    async def compact(self) -> int:
        """fsync point 3 (decision 7); how many segments it unlinked, none until a marker is
        trusted."""
        self._require_open()
        if self._pos is None:
            return 0
        pos, active = self._pos, self._active
        return len(await self._run(lambda op: self._io(op, self._files.compact, pos, active)))

    async def quarantine(self, run: Run) -> None:
        """fsync point 4: a run's bytes; a run without bytes has no copy."""
        self._require_open()
        if (name := run.quarantined) is not None:
            await self._run(lambda op: self._io(op, self._files.quarantine, name, run.data))

    async def rescan(self, origin: LaneMarker) -> LaneScan:
        """The drain's running scan (§15.6 Scan) from `origin`, the end of the last unit it took:
        a frame boundary it scanned, so nothing before it is parsed again. A run open at the end of
        the newest segment seals it (row 16), and bytes past the appends count (reading 2)."""
        self._require_open()
        body = encode_marker(self._keys, origin)
        return await self._run(lambda op: self._rescan(op, body))

    async def _rescan(self, op: _Op, body: bytes) -> LaneScan:
        async with self._held(op):  # a failed read ends the drain, whose death stops the lane
            result = await _in_thread(op, _running_scan, self._files, self._keys, body)
            for unit in result.units:
                if unit.end > self._end:  # bytes the appender did not write
                    self._count(
                        unit.end, len(unit.data if isinstance(unit, Run) else unit.raw), False
                    )
            if result.sealed:
                self._close()  # the next append starts a new segment
        return result

    def hold(self) -> None:
        """A hold the running scan met (row 12): every later append is refused `held`."""
        self.refusal = "held"
        _log().critical("audit lane held until a restart")

    async def close(self) -> None:
        """Refuse every later append (`stopped`) and drain operation (`LaneError`), wait for the
        ops in flight, close the segment."""
        self.refusal = self.refusal or "stopped"
        self._closed = True
        while self._ops:
            await asyncio.wait(set(self._ops))
        self._close()

    def _close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def _require_open(self) -> None:
        """The drain's operations end with `close()`."""
        if self._closed:
            raise LaneError("the audit lane is closed")

    def _count(self, end: Pos, size: int, shared: bool) -> None:
        self._units.append((end, size, shared))
        self._bytes += size
        self._shared += size if shared else 0
        self._end = max(self._end, end)

    def stop(self, exc: BaseException) -> None:
        """Failures while running, a dead drain among them: no append until a restart; a hold
        stays a hold."""
        self.refusal = self.refusal or "stopped"
        _log().critical("audit lane stopped until a restart", error=type(exc).__name__)

    @contextlib.asynccontextmanager
    async def _held(
        self, op: _Op, cls: LaneClass = "reserved", capped: bool = False
    ) -> AsyncIterator[None]:
        """The lane lock for one op: an append's class and cap, while the drain's operations
        queue with `reserved` outside the caps (reading 6). A cancel deferred during a thread
        call is raised at the op's end."""
        await self._lock.acquire(cls, capped)
        try:
            op.holding = True
            yield
        finally:
            self._lock.release()
        if op.cancel_pending:
            raise asyncio.CancelledError

    async def _io[T](self, op: _Op, fn: Callable[..., T], *args: object) -> T:
        """A drain's fsync point; a failure stops the lane, as a dead drain would, and raises."""
        async with self._held(op):
            try:
                return await _in_thread(op, fn, *args)
            except OSError as exc:
                self.stop(exc)
                raise

    async def _run[T](self, body: Callable[[_Op], Coroutine[Any, Any, T]]) -> T:
        """One op as a tracked task awaited through `asyncio.shield` (#2250): once it holds the
        lock a cancelled caller returns at once and the task runs on; still queued, it is
        cancelled with its caller."""
        op = _Op()
        task = spawn(body(op), name="audit-lane-op")
        self._ops.add(task)
        task.add_done_callback(self._ops.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if op.holding:
                task.add_done_callback(_log_abandoned)
            else:
                task.cancel()
            raise


def _log_abandoned(task: asyncio.Task[Any]) -> None:
    """Done-callback of an op whose caller was cancelled: nobody else sees how it ended."""
    error = None if task.cancelled() else task.exception()
    if error is not None and not isinstance(error, LaneRefused):
        _log().critical("audit lane op failed after its caller left", error=type(error).__name__)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
