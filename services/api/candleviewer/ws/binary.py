"""CVWB binary frame codec (E17-T02, docs/plan/23-ws-protocol.md section 3.4).

Every offset, stride, struct format and ``format_version`` comes from the ONE layout
declaration ``packages/protocol/cvwb-layout.json``, compiled into
``candleviewer.ws._generated.cvwb_layout`` by ``packages/protocol/scripts/
generate-cvwb-layout.mjs`` (the TS decoder reads the same generated constants).

Values are already-scaled integers (``real = int / 10**scale``); converting Decimals to
scaled ints is the caller's job. The encoder writes into one pre-sized ``bytearray`` with
``Struct.pack_into`` (no per-record objects). The decoder treats input as untrusted: the
SR-128 bounds check against the real buffer length runs right after the header parse and
before anything sized from a wire count is allocated.
"""

from __future__ import annotations

import base64
import binascii
import struct
from dataclasses import dataclass
from time import perf_counter
from typing import Final

from candleviewer.ws._generated.cvwb_layout import HEADER, KINDS, MAGIC, Kind, Part
from candleviewer.ws.errors import WsError
from candleviewer.ws.metrics import ENCODE_COST, ENCODED

BOOK_SNAPSHOT: Final = 1
BOOK_DELTA: Final = 2
TRADES: Final = 3
BARS: Final = 4
FOOTPRINT: Final = 5
HEATMAP_COLUMN: Final = 6

FLAG_ESTIMATED: Final = 0b0001
FLAG_COALESCED: Final = 0b0010
FLAG_REPLAY: Final = 0b0100
FLAG_PARTIAL: Final = 0b1000
_KNOWN_FLAGS: Final = 0b1111

_HEADER: Final = struct.Struct(HEADER.fmt)
_STRUCTS: Final[dict[str, struct.Struct]] = {}

Record = tuple[int, ...]
#: One footprint bar: ``((generation, index, ts_offset_ms, flags), cells)``. The prefix is the
#: kind-5 group prefix in declaration order without ``cell_count`` (derived from ``cells``);
#: ``(generation, index)`` is the section 8.2 bar key and ``flags`` bit0 is ``confirm``
#: (body_kind 5 format_version 2, #2529).
Group = tuple[Record, tuple[Record, ...]]

#: The group prefix field derived from ``len(cells)``. It is not the last field (``flags``
#: follows it), so the codec finds it by name in the generated layout.
_GROUP_COUNT: Final = "cell_count"
#: Group ``flags`` bits the encoder may send: bit0 ``confirm``. Bits 1-7 are reserved, 0 on send
#: and ignored on receive (section 3.4), so a later flag is additive.
_GROUP_KNOWN_FLAGS: Final = 0b0000_0001


def _st(part: Part) -> struct.Struct:
    cached = _STRUCTS.get(part.fmt)
    if cached is None:
        cached = _STRUCTS[part.fmt] = struct.Struct(part.fmt)
    return cached


class FrameMalformedError(WsError):
    """An untrusted CVWB buffer violates section 3.4 (wire code ``frame_malformed``).

    ``diagnostic`` is the local, more specific reason (``frame_malformed`` or
    ``unsupported_format_version`` / ``unsupported_body_kind``); both map to
    ``frame_malformed`` on the wire (section 10.2).
    """

    code: Final = "frame_malformed"

    def __init__(self, message: str, diagnostic: str = "frame_malformed") -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class FrameEncodeError(WsError, ValueError):
    """The caller handed the encoder values that cannot be represented in section 3.4."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One CVWB frame. ``format_version`` and ``record_count`` are derived, never free.

    * kinds 1-4: ``records`` are flat field tuples in declaration order (pad excluded);
    * kind 1 also has ``trailer`` = ``(xu, xseq)``;
    * kind 5: ``groups`` = ``(((generation, index, ts_offset_ms, flags), cells), ...)``,
      ``cell_count`` derived;
    * kind 6: ``prefix`` = ``(ts_offset_ms, price_min, price_step)``, ``records`` = rows,
      ``row_count`` derived; header ``record_count`` is 1 (one column).
    """

    body_kind: int
    records: tuple[Record, ...] = ()
    flags: int = 0
    price_scale: int = 0
    qty_scale: int = 0
    ts_base_ms: int = 0
    trailer: Record | None = None
    prefix: Record | None = None
    groups: tuple[Group, ...] | None = None

    @property
    def format_version(self) -> int:
        return KINDS[self.body_kind].format_version


def _kind(body_kind: int) -> Kind:
    kind = KINDS.get(body_kind)
    if kind is None:
        raise FrameEncodeError(f"unknown body_kind {body_kind}")
    return kind


def _body_size(frame: Frame, kind: Kind) -> int:
    size = len(frame.records) * kind.record.size
    if kind.trailer is not None:
        size += kind.trailer.size
    if kind.body_prefix is not None:
        size += kind.body_prefix.size
    if kind.group_prefix is not None:
        for _, cells in frame.groups or ():
            size += kind.group_prefix.size + len(cells) * kind.record.size
    return size


def _header_count(frame: Frame, kind: Kind) -> int:
    if kind.group_prefix is not None:
        return len(frame.groups or ())
    if kind.body_prefix is not None:
        return 1
    return len(frame.records)


def encode(frame: Frame, weight: int = 0) -> bytes:
    """Encodes ``frame``. The hub calls it once per subscription per delta, and once per chunk of
    a snapshot it renders. A ``weight`` above 0 also times the call and sizes the result into
    ``cv_ws_frame_*{kind}``, observed ``weight`` times: the caller's sampling (the delta the hub
    stamped carries ``SAMPLE_EVERY``, a snapshot chunk 1); 0 reads no timer and observes nothing."""
    kind = _kind(frame.body_kind)
    began = perf_counter() if weight else 0.0
    if frame.flags & ~_KNOWN_FLAGS:
        raise FrameEncodeError(f"unknown header flag bits 0x{frame.flags:x}")
    if (kind.trailer is None) != (frame.trailer is None):
        raise FrameEncodeError(f"{kind.name}: trailer must be given iff the kind declares one")
    if (kind.body_prefix is None) != (frame.prefix is None):
        raise FrameEncodeError(f"{kind.name}: prefix must be given iff the kind declares one")
    if (kind.group_prefix is None) != (frame.groups is None):
        raise FrameEncodeError(f"{kind.name}: groups must be given iff the kind declares them")
    if kind.group_prefix is not None and frame.records:
        raise FrameEncodeError(f"{kind.name}: records live inside groups")
    if kind.group_prefix is not None:
        _check_groups(frame.groups, kind.group_prefix, kind.name)
    out = bytearray(HEADER.size + _body_size(frame, kind))
    rec = _st(kind.record)
    try:
        _HEADER.pack_into(
            out,
            0,
            MAGIC,
            kind.format_version,
            kind.id,
            frame.flags,
            frame.price_scale,
            frame.qty_scale,
            _header_count(frame, kind),
            frame.ts_base_ms,
        )
        off = HEADER.size
        if kind.body_prefix is not None and frame.prefix is not None:
            _st(kind.body_prefix).pack_into(out, off, *frame.prefix, len(frame.records))
            off += kind.body_prefix.size
        if kind.group_prefix is not None:
            gp = _st(kind.group_prefix)
            ci = _count_at(kind.group_prefix)
            for group_prefix, cells in frame.groups or ():
                gp.pack_into(out, off, *group_prefix[:ci], len(cells), *group_prefix[ci:])
                off += kind.group_prefix.size
                for cell in cells:
                    rec.pack_into(out, off, *cell)
                    off += kind.record.size
        for r in frame.records:
            _check_enums(kind.record, r)
            rec.pack_into(out, off, *r)
            off += kind.record.size
        if kind.trailer is not None and frame.trailer is not None:
            _st(kind.trailer).pack_into(out, off, *frame.trailer)
    except struct.error as exc:
        raise FrameEncodeError(f"{kind.name}: value out of range for section 3.4: {exc}") from exc
    except TypeError as exc:  # a record that is not a tuple: `*record` cannot expand it
        raise FrameEncodeError(f"{kind.name}: a record is not a tuple of ints: {exc}") from exc
    encoded = bytes(out)
    # Success path only, O(1) per frame, on the loop thread where the hub calls it (the
    # histograms have a single writer). The timer stops here: the counters are not encode time.
    if weight:
        seconds, sizes = ENCODE_COST[kind.id]
        seconds.observe(perf_counter() - began, weight)
        sizes.observe(len(encoded), weight)
    frames, nbytes = ENCODED[kind.id]
    frames.inc()
    nbytes.inc(len(encoded))
    return encoded


def _count_at(part: Part) -> int:
    """Position of ``cell_count`` among the packed group prefix fields."""
    return part.fields.index(_GROUP_COUNT)


def _check_groups(groups: object, part: Part, name: str) -> None:
    """Refuse a malformed ``groups`` before anything is sized or unpacked from it: a tuple of
    ``(prefix, cells)`` tuples, each prefix one int per field but the derived ``cell_count``, i.e.
    ``(generation, index, ts_offset_ms, flags)`` since kind 5 v2 (#2529). A v1-shaped group (a bare
    ``ts_offset_ms``) or any other loose shape is a typed error, never the bare ValueError or
    TypeError that unpacking it would raise. So are reserved ``flags`` bits, which are 0 on send."""
    fields = tuple(f for f in part.fields if f != _GROUP_COUNT)
    shape = f"{name}: groups are a tuple of (({', '.join(fields)}), cells)"
    if not isinstance(groups, tuple):
        raise FrameEncodeError(shape)
    for group in groups:
        if not (
            isinstance(group, tuple)
            and len(group) == 2
            and isinstance(group[0], tuple)
            and len(group[0]) == len(fields)
            and isinstance(group[1], tuple)
        ):
            raise FrameEncodeError(shape)
        flags = group[0][fields.index("flags")] if "flags" in fields else 0
        if isinstance(flags, int) and flags & ~_GROUP_KNOWN_FLAGS:
            raise FrameEncodeError(f"{name}: reserved group flag bits are 0 on send, got {flags}")


def _check_enums(part: Part, record: Record) -> None:
    for name, allowed in part.enums.items():
        value = record[part.fields.index(name)]
        if value not in allowed:
            raise FrameEncodeError(f"{name}={value} not in {allowed}")


def encode_b64(frame: Frame, weight: int = 0) -> str:
    """``cv.v1.json`` wrapping (section 3.2): the frame bytes as base64, sent with ``e: "b64"``.
    ``weight`` is `encode`'s."""
    return base64.b64encode(encode(frame, weight)).decode("ascii")


def _fits(count: int, stride: int, available: int, what: str) -> None:
    """SR-128: ``count`` wire records must fit in the bytes actually present, BEFORE any
    allocation or loop sized from ``count``."""
    if count * stride > available:
        raise FrameMalformedError(
            f"{what}: count={count} x {stride} bytes exceeds the {available} bytes available"
        )


def _rows(view: memoryview, off: int, count: int, part: Part, what: str) -> tuple[Record, ...]:
    end = off + count * part.size
    rows = tuple(_st(part).iter_unpack(view[off:end]))
    for i, r in enumerate(rows):
        for name, allowed in part.enums.items():
            if r[part.fields.index(name)] not in allowed:
                raise FrameMalformedError(f"{what}: invalid {name} at record {i}")
    return rows


def decode(data: bytes | bytearray | memoryview) -> Frame:
    """Decodes an untrusted CVWB buffer; raises only :class:`FrameMalformedError`."""
    view = memoryview(data).cast("B")
    n = len(view)
    if n < HEADER.size:
        raise FrameMalformedError(f"frame is {n} bytes, shorter than the {HEADER.size}-byte header")
    magic, version, body_kind, flags, p_scale, q_scale, count, ts_base = _HEADER.unpack_from(view)
    if magic != MAGIC:
        raise FrameMalformedError(f"bad magic 0x{magic:08x}")
    kind = KINDS.get(body_kind)
    if kind is None:
        raise FrameMalformedError(f"unknown body_kind {body_kind}", "unsupported_body_kind")
    if version != kind.format_version:
        raise FrameMalformedError(
            f"unsupported (body_kind={body_kind}, format_version={version})",
            "unsupported_format_version",
        )
    off = HEADER.size
    avail = n - off
    # SR-128: every wire count is checked against `avail` before it sizes anything.
    if kind.body_prefix is not None:
        _fits(1, kind.body_prefix.size, avail, kind.name)
        *prefix, row_count = _st(kind.body_prefix).unpack_from(view, off)
        off += kind.body_prefix.size
        _fits(row_count, kind.record.size, n - off, kind.name)
        rows = _rows(view, off, row_count, kind.record, kind.name)
        return Frame(body_kind, rows, flags, p_scale, q_scale, ts_base, prefix=tuple(prefix))
    if kind.group_prefix is not None:
        _fits(count, kind.group_prefix.size, avail, kind.name)
        gp = _st(kind.group_prefix)
        ci = _count_at(kind.group_prefix)
        groups: list[Group] = []
        for g in range(count):
            _fits(1, kind.group_prefix.size, n - off, f"{kind.name} group {g}")
            values = gp.unpack_from(view, off)
            cell_count = values[ci]
            off += kind.group_prefix.size
            _fits(cell_count, kind.record.size, n - off, f"{kind.name} group {g}")
            cells = _rows(view, off, cell_count, kind.record, kind.name)
            # Reserved flag bits are kept as received (lossless); consumers read bit0 only.
            groups.append((values[:ci] + values[ci + 1 :], cells))
            off += cell_count * kind.record.size
        return Frame(body_kind, (), flags, p_scale, q_scale, ts_base, groups=tuple(groups))
    trailer_size = kind.trailer.size if kind.trailer is not None else 0
    need = count * kind.record.size + trailer_size
    if kind.length_rule == "exact" and need != avail:
        raise FrameMalformedError(f"{kind.name}: body is {avail} bytes, expected exactly {need}")
    _fits(count, kind.record.size, avail - trailer_size, kind.name)
    if trailer_size > avail:
        raise FrameMalformedError(f"{kind.name}: missing its {trailer_size}-byte trailer")
    records = _rows(view, off, count, kind.record, kind.name)
    trailer: Record | None = None
    if kind.trailer is not None:
        trailer = _st(kind.trailer).unpack_from(view, off + count * kind.record.size)
    return Frame(body_kind, records, flags, p_scale, q_scale, ts_base, trailer=trailer)


def decode_b64(text: str) -> Frame:
    """Inverse of :func:`encode_b64`; bad base64 is ``frame_malformed`` too."""
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FrameMalformedError("payload is not valid base64") from exc
    return decode(raw)


__all__ = [
    "BARS",
    "BOOK_DELTA",
    "BOOK_SNAPSHOT",
    "FOOTPRINT",
    "HEATMAP_COLUMN",
    "TRADES",
    "Frame",
    "FrameEncodeError",
    "FrameMalformedError",
    "decode",
    "decode_b64",
    "encode",
    "encode_b64",
]
