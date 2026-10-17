"""Journal-first audit lane: frame codec, marker, scan and quarantine (ADR-0037, slice S1a).

`docs/plan/24-internal-schemas.md` §15.6 owns the format, the parse order, the scan table and the
quarantine rules (C-16.5); this module implements them and restates none. It is pure: no I/O,
clock or log. `scan()` takes the marker, the file names, a segment reader and the `released` note,
so the drain (S2a2) owns every file operation; appends, segments and quotas are S1b's. No error
message carries a key, a MAC or a record.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from candleviewer.audit.errors import AuditError

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

    frame: LaneFrame
    raw: bytes
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
    data: bytes
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
    units: tuple[Handover | Run, ...]
    state: LaneState
    held: bool
    hold: Pos | None
    note_ignored: bool
    sealed: bool  # row 14: the next append starts a new segment


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
    """One pass of the §15.6 table; "row n" counts its rows from the top."""

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

    def begin(self, marker: bytes | None) -> Pos | None:
        """Rows 1 to 4: the state, and the segment index and offset to scan from."""
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
            if offset <= len(self.data(i)) and _at_boundary(self.data(i), offset):
                return i, offset
        elif not self.firsts and found.pos == (1, 0):
            return None  # a new lane before its frame 1
        elif self.firsts and self.firsts[-1] > first:  # its segment was deleted
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
            else:  # rows 9, 12 and 13
                self.join(found, data[off:end], unanchor=found != "torn_tail")
            off = end
        if self.run is not None:  # row 14
            self.units.append(self.run.close(None, self.at, self.state, False))
            self.run, self.sealed = None, bool(self.firsts)

    def frame(self, frame: LaneFrame, raw: bytes, end: Pos) -> None:
        """Rows 5 to 8. A rescan without a verifiable marker starts at the first authentic frame,
        which in row 3 also sets the lane."""
        if self.lost:
            self.lost, self.lane = False, frame.lane if self.lane is None else self.lane
            self.state = replace(self.state, next_seq=frame.seq)
            if self.run is not None:
                self.run.from_seq = frame.seq
        expected = frame.seq if self.state.next_seq is None else self.state.next_seq
        if frame.seq > expected:  # row 6
            self.join("seq_gap", b"", unanchor=True)
            self.state, expected = replace(self.state, next_seq=frame.seq), frame.seq
        if frame.seq != expected or (self.state.anchored and frame.prev != self.state.prev):
            self.join("frame_rejected", raw, unanchor=True)  # rows 7 and 8
            return
        if self.run is not None:  # row 5
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
        """Rows 10 and 11: close the open run as at the end of the data, then resume after a
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
) -> LaneScan:
    """The §15.6 scan from `marker` (`confirmed`, None when absent) over the segments among
    `names`, each read once through `read`, with the `released` note if one exists."""
    run = _Scan(keys, names, read)
    start = run.begin(marker)
    if start is not None:
        run.walk(*start, note)
    units = tuple(run.units)
    return LaneScan(run.lane, units, run.state, run.held, run.hold, run.note_ignored, run.sealed)
