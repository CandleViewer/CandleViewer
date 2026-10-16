"""Deterministic cross-language CVWB vectors and the SR-155 fuzz seed corpus (E17-T02).

Rendered by ``scripts/generate_cvwb_vectors.py`` into
``packages/fixtures/golden/cvwb/vectors.json`` (Python encode -> TS decode) and
``tests/fuzz/ws-frames/corpus.json`` (hostile seeds; both decoders must reject or accept
exactly as ``expect`` says, never crash). Both files are drift-checked by tests.
"""

from __future__ import annotations

import json
import struct
from typing import Any

from candleviewer.ws.binary import (
    BARS,
    BOOK_DELTA,
    BOOK_SNAPSHOT,
    FOOTPRINT,
    HEATMAP_COLUMN,
    TRADES,
    Frame,
    encode,
)

_MAX_SAFE = 2**53 - 1
_I64_MIN = -(2**63)
_U64_MAX = 2**64 - 1
_U32_MAX = 2**32 - 1


def vector_frames() -> list[tuple[str, Frame]]:
    """Named valid frames covering every kind, every flag bit, deletes and int extremes."""
    bar = (
        7,
        42,
        60_000,
        6_500_012,
        6_510_000,
        6_490_000,
        6_505_050,
        1_234_567,
        9 * 10**12,
        321,
        -4_567,
        1,
    )
    return [
        (
            "book_snapshot",
            Frame(
                BOOK_SNAPSHOT,
                ((0, 6_500_000, 1_500), (0, 6_499_950, 0), (1, 6_500_050, 2_000)),
                0b0001,
                2,
                3,
                1_789_132_262_104,
                trailer=(123_456, _U64_MAX),
            ),
        ),
        ("book_snapshot_empty", Frame(BOOK_SNAPSHOT, (), 0, 2, 3, 0, trailer=(0, 0))),
        (
            "book_delta_extremes",
            Frame(BOOK_DELTA, ((1, _I64_MIN, _U64_MAX), (0, 2**63 - 1, 0)), 0b1111, 8, 8, 2**63),
        ),
        (
            "trades",
            Frame(
                TRADES,
                ((0, 6_500_000, 10, 0, 0b001), (_U32_MAX, -1, 0, 1, 0b111)),
                0b0010,
                1,
                4,
                1_789_132_262_000,
            ),
        ),
        (
            "bars_v2",
            Frame(
                BARS,
                (bar, (7, 43, 120_000, 1, 2, 0, -1, 0, 0, 0, _I64_MIN, 0)),
                0b0100,
                2,
                3,
                1_789_132_200_000,
            ),
        ),
        ("bars_empty", Frame(BARS, (), 0, 0, 0, 0)),
        (
            "footprint",
            Frame(
                FOOTPRINT,
                (),
                0b1000,
                1,
                3,
                1_789_132_200_000,
                groups=(
                    (
                        (7, 42, 0, 1),  # closed (flags bit0 confirm)
                        (
                            (6_500_000, 10, 20, 3, 0b1001),
                            (6_500_005, 0, _U64_MAX, _U32_MAX, 0b0110),
                        ),
                    ),
                    ((7, 43, 60_000, 0), ()),  # forming
                ),
            ),
        ),
        (
            # #2529: one trade closes bar N and opens bar N+1 in the same millisecond, so both
            # bars share an open time (and here a price); only (generation, index) tells them apart.
            # Bar N is closed and bar N+1 forming, as the confirm bit says.
            "footprint_shared_open_time",
            Frame(
                FOOTPRINT,
                (),
                0b0010,
                1,
                3,
                1_789_132_200_000,
                groups=(
                    ((0, 1_000, 59_999, 1), ((6_500_010, 5, 0, 1, 0b0001),)),
                    ((0, 1_001, 59_999, 0), ((6_500_010, 0, 7, 1, 0b0010),)),
                ),
            ),
        ),
        (
            "heatmap_column",
            Frame(
                HEATMAP_COLUMN,
                ((1, 2), (0, 0), (_U64_MAX, 7)),
                0,
                2,
                3,
                1_789_132_262_100,
                prefix=(100, 6_499_000, 5),
            ),
        ),
    ]


def render_vectors() -> str:
    out = []
    for name, f in vector_frames():
        out.append(
            {
                "name": name,
                "hex": encode(f).hex(),
                "body_kind": f.body_kind,
                "flags": f.flags,
                "price_scale": f.price_scale,
                "qty_scale": f.qty_scale,
                "ts_base_ms": str(f.ts_base_ms),
                "records": [[str(v) for v in r] for r in f.records],
                "trailer": None if f.trailer is None else [str(v) for v in f.trailer],
                "prefix": None if f.prefix is None else [str(v) for v in f.prefix],
                "groups": (
                    None
                    if f.groups is None
                    else [
                        [[str(v) for v in prefix], [[str(v) for v in c] for c in cells]]
                        for prefix, cells in f.groups
                    ]
                ),
            }
        )
    return json.dumps(out, indent=2) + "\n"


_HDR = struct.Struct("<IBBBBB3xIQ")
_MAGIC = 0x43565742
#: kind 5 v2 group prefix (#2529): u64 generation, u64 index, u32 ts_offset_ms, u32 cell_count,
#: u8 flags (bit0 confirm), 3 pad bytes: 28 bytes.
_FP_GROUP = struct.Struct("<QQIIB3x")
_FP_CELL = struct.Struct("<qQQIB4x")


def _h(
    kind: int,
    count: int,
    *,
    ver: int | None = None,
    magic: int = _MAGIC,
    flags: int = 0,
    ps: int = 2,
    qs: int = 3,
    ts: int = 0,
) -> bytes:
    version = ver if ver is not None else (2 if kind in (BARS, FOOTPRINT) else 1)
    return _HDR.pack(magic, version, kind, flags, ps, qs, count, ts)


def corpus_seeds() -> list[tuple[str, str, bytes]]:
    """``(name, expect, bytes)``; ``expect`` is ``ok`` or ``malformed`` (SR-155 seeds)."""
    one_bar = encode(vector_frames()[4][1])[24 : 24 + 85]
    fp_cell = _FP_CELL.pack(6_500_000, 1, 2, 1, 0b1000)
    fp_group = _FP_GROUP.pack(0, 7, 60_000, 1, 1) + fp_cell  # one closed v2 group of one cell, 61 B
    v1_fp_group = struct.pack("<II", 60_000, 1) + fp_cell  # the same bar as a v1 encoder sent it
    reserved_flags = _FP_GROUP.pack(0, 7, 60_000, 1, 0b1111_1110) + fp_cell  # bits 1-7 set
    group_pad = _FP_GROUP.pack(0, 7, 60_000, 1, 1)[:25] + bytes([0xFF]) * 3 + fp_cell
    book_rec = struct.pack("<BqQ", 0, 6_500_000, 1)
    nan_bits = struct.pack("<Q", 0x7FF8_0000_0000_0000)  # NaN-shaped bits in an int field
    s: list[tuple[str, str, bytes]] = [
        ("empty-buffer", "malformed", b""),
        ("header-truncated-23", "malformed", _h(BOOK_DELTA, 0)[:23]),
        ("bad-magic", "malformed", _h(BOOK_DELTA, 0, magic=0x42575643)),
        ("future-format-version", "malformed", _h(BOOK_DELTA, 0, ver=9)),
        ("unknown-body-kind-0", "malformed", _h(0, 0, ver=1)),
        ("unknown-body-kind-7", "malformed", _h(7, 0, ver=1)),
        ("zero-length-delta", "ok", _h(BOOK_DELTA, 0)),
        ("delta-count-max-u32-32b-body", "malformed", _h(BOOK_DELTA, _U32_MAX) + bytes(32)),
        ("delta-count-exceeds-buffer", "malformed", _h(BOOK_DELTA, 3) + book_rec * 2),
        ("delta-truncated-record", "malformed", _h(BOOK_DELTA, 1) + book_rec[:16]),
        ("delta-bad-side", "malformed", _h(BOOK_DELTA, 1) + b"\x02" + book_rec[1:]),
        ("delta-trailing-8-bytes", "ok", _h(BOOK_DELTA, 1) + book_rec + bytes(8)),
        ("scales-255", "ok", _h(BOOK_DELTA, 1, ps=255, qs=255) + book_rec),
        ("nan-shaped-size", "ok", _h(BOOK_DELTA, 1) + book_rec[:9] + nan_bits),
        ("all-flag-bits-set", "ok", _h(BOOK_DELTA, 0, flags=0xFF)),
        ("snapshot-missing-trailer", "malformed", _h(BOOK_SNAPSHOT, 1) + book_rec + bytes(15)),
        ("snapshot-count-max-u32", "malformed", _h(BOOK_SNAPSHOT, _U32_MAX) + bytes(16)),
        ("trades-count-max-u32", "malformed", _h(TRADES, _U32_MAX) + bytes(22)),
        ("trades-bad-side", "malformed", _h(TRADES, 1) + bytes(20) + b"\x07\x00"),
        # #2034 (bars v2, exact-length rule):
        ("bars-count-max-u32-one-record", "malformed", _h(BARS, _U32_MAX) + one_bar),
        ("bars-truncated-84", "malformed", _h(BARS, 1) + one_bar[:84]),
        ("bars-v1-header-85-body", "malformed", _h(BARS, 1, ver=1) + one_bar),
        ("bars-v2-header-69-body", "malformed", _h(BARS, 1) + one_bar[:69]),
        ("bars-count0-trailing", "malformed", _h(BARS, 0) + bytes(8)),
        ("bars-count1-trailing", "malformed", _h(BARS, 1) + one_bar + bytes(8)),
        ("bars-exact-one", "ok", _h(BARS, 1) + one_bar),
        ("footprint-groups-max-u32", "malformed", _h(FOOTPRINT, _U32_MAX) + bytes(28)),
        (
            "footprint-cell-count-oversized",
            "malformed",
            _h(FOOTPRINT, 1) + _FP_GROUP.pack(0, 0, 0, _U32_MAX, 0) + bytes(33),
        ),
        ("footprint-group-prefix-truncated", "malformed", _h(FOOTPRINT, 2) + bytes(42)),
        ("footprint-empty-group", "ok", _h(FOOTPRINT, 1) + bytes(28)),
        # #2529 (footprint v2: 28-byte group prefix with the section 8.2 bar key and flags):
        ("footprint-v1-frame", "malformed", _h(FOOTPRINT, 1, ver=1) + v1_fp_group),
        ("footprint-v1-header-v2-group", "malformed", _h(FOOTPRINT, 1, ver=1) + fp_group),
        ("footprint-v2-header-v1-empty-group", "malformed", _h(FOOTPRINT, 1) + bytes(8)),
        ("footprint-group-prefix-27", "malformed", _h(FOOTPRINT, 1) + fp_group[:27]),
        ("footprint-group-cell-truncated", "malformed", _h(FOOTPRINT, 1) + fp_group[:-1]),
        ("footprint-exact-one-group", "ok", _h(FOOTPRINT, 1) + fp_group),
        ("footprint-one-group-trailing-8", "ok", _h(FOOTPRINT, 1) + fp_group + bytes(8)),
        ("footprint-group-reserved-flag-bits", "ok", _h(FOOTPRINT, 1) + reserved_flags),
        ("footprint-group-pad-nonzero", "ok", _h(FOOTPRINT, 1) + group_pad),
        ("heatmap-prefix-truncated", "malformed", _h(HEATMAP_COLUMN, 1) + bytes(23)),
        (
            "heatmap-row-count-max-u32",
            "malformed",
            _h(HEATMAP_COLUMN, 1) + struct.pack("<IqqI", 0, 0, 1, _U32_MAX) + bytes(16),
        ),
        (
            "heatmap-zero-rows-trailing",
            "ok",
            _h(HEATMAP_COLUMN, 1) + struct.pack("<IqqI", 0, 0, 1, 0) + bytes(5),
        ),
    ]
    trade = struct.pack("<IqQBB", 0, 1, 1, 0, 0)
    cell = struct.pack("<qQQIB4x", 1, 1, 1, 1, 0)
    hm = struct.pack("<IqqI", 0, 0, 1, 2)
    trl = bytes(16)
    s += [
        # count=1 and +/-1 byte bodies (security review of #2041):
        ("delta-one-exact", "ok", _h(BOOK_DELTA, 1) + book_rec),
        ("delta-one-minus-1", "malformed", _h(BOOK_DELTA, 1) + book_rec[:-1]),
        ("delta-one-plus-1", "ok", _h(BOOK_DELTA, 1) + book_rec + bytes(1)),
        ("snapshot-one-exact", "ok", _h(BOOK_SNAPSHOT, 1) + book_rec + trl),
        ("snapshot-one-minus-1", "malformed", _h(BOOK_SNAPSHOT, 1) + book_rec + trl[:-1]),
        ("snapshot-one-plus-1", "ok", _h(BOOK_SNAPSHOT, 1) + book_rec + trl + bytes(1)),
        ("snapshot-empty-trailer-minus-1", "malformed", _h(BOOK_SNAPSHOT, 0) + trl[:-1]),
        ("trades-count-0", "ok", _h(TRADES, 0)),
        ("trades-one-exact", "ok", _h(TRADES, 1) + trade),
        ("trades-one-minus-1", "malformed", _h(TRADES, 1) + trade[:-1]),
        ("trades-one-plus-1", "ok", _h(TRADES, 1) + trade + bytes(1)),
        ("heatmap-rows-exact", "ok", _h(HEATMAP_COLUMN, 1) + hm + bytes(32)),
        ("heatmap-rows-minus-1-byte", "malformed", _h(HEATMAP_COLUMN, 1) + hm + bytes(31)),
        ("heatmap-rows-plus-1-byte", "ok", _h(HEATMAP_COLUMN, 1) + hm + bytes(33)),
        (
            "footprint-cell-count-body-plus-1",
            "malformed",
            _h(FOOTPRINT, 1) + _FP_GROUP.pack(0, 0, 0, 2, 0) + cell,
        ),
        (
            "footprint-second-group-overflow",
            "malformed",
            _h(FOOTPRINT, 2)
            + _FP_GROUP.pack(0, 0, 0, 1, 0)
            + cell
            + _FP_GROUP.pack(0, 1, 1, 9, 0)
            + cell,
        ),
        # Pinned ACCEPT behaviour: section 3.4 does not yet say whether non-zero reserved
        # header bytes, unknown flag bits or non-zero record pad bytes must be rejected.
        # Decision tracked in #2042; flip these to "malformed" if it says reject.
        (
            "reserved-header-bytes-nonzero",
            "ok",
            _h(BOOK_DELTA, 0)[:9] + bytes([0xFF]) * 3 + _h(BOOK_DELTA, 0)[12:],
        ),
        ("unknown-flag-bits-0xf0", "ok", _h(BOOK_DELTA, 0, flags=0xF0)),
        ("bars-pad-nonzero", "ok", _h(BARS, 1) + one_bar[:81] + bytes([0xFF]) * 4),
        (
            "footprint-cell-pad-nonzero",
            "ok",
            _h(FOOTPRINT, 1) + _FP_GROUP.pack(0, 0, 0, 1, 0) + cell[:29] + bytes([0xFF]) * 4,
        ),
    ]
    s.extend((f"valid-{n}", "ok", encode(f)) for n, f in vector_frames())
    return s


def render_corpus() -> str:
    seeds = [{"name": n, "expect": e, "hex": b.hex()} for n, e, b in corpus_seeds()]
    return json.dumps(seeds, indent=2) + "\n"


# --- section 14 structured twin ---------------------------------------------------------
# The same payload as the section 14 item shape. Prices/sizes are decimal strings
# (common.schema `decimal`); every integer (epoch-ms, generation, index, xu, xseq) is a
# JSON number, matching the generated types (`number`); values above 2**53 would be
# rejected by the TS converter, and no committed vector carries one.
# Heatmap `bids`/`asks` are JSON numbers (14.5 says `number`).


def _unscale(value: int, scale: int) -> str:
    sign = "-" if value < 0 else ""
    whole, frac = divmod(abs(value), 10**scale)
    return f"{sign}{whole}" if scale == 0 else f"{sign}{whole}.{frac:0{scale}d}"


def structured(f: Frame) -> dict[str, Any]:
    """Section 14 item form of ``f`` (one payload; topic fields like symbol are not on the wire)."""
    ps, qs, base = f.price_scale, f.qty_scale, f.ts_base_ms

    def p(v: int) -> str:
        return _unscale(v, ps)

    def q(v: int) -> str:
        return _unscale(v, qs)

    out: dict[str, Any] = {}
    if f.body_kind in (BOOK_SNAPSHOT, BOOK_DELTA):
        out["price_scale"], out["qty_scale"] = ps, qs
        out["bids"] = [[p(r[1]), q(r[2])] for r in f.records if r[0] == 0]
        out["asks"] = [[p(r[1]), q(r[2])] for r in f.records if r[0] == 1]
        out["coalesced"] = bool(f.flags & 0b10)
        if f.trailer is not None:
            # Generated type is `number`: upstream ids above 2**53 are diagnostics-only, omitted.
            for key, val in zip(("xu", "xseq"), f.trailer, strict=True):
                if val <= _MAX_SAFE:
                    out[key] = val
    elif f.body_kind == TRADES:
        out["trades"] = [
            {
                "ts_ms": (base + r[0]),
                "price": p(r[1]),
                "size": q(r[2]),
                "side": "buy" if r[3] == 0 else "sell",
                "is_block_trade": bool(r[4] & 1),
                "is_liquidation": bool(r[4] & 2),
            }
            for r in f.records
        ]
    elif f.body_kind == BARS:
        out["bars"] = [
            {
                "generation": (r[0]),
                "index": (r[1]),
                "t_ms": (base + r[2]),
                "o": p(r[3]),
                "h": p(r[4]),
                "l": p(r[5]),
                "c": p(r[6]),
                "v": q(r[7]),
                "turnover": q(r[8]),
                "trades": r[9],
                "delta": q(r[10]),
                "confirm": bool(r[11] & 1),
            }
            for r in f.records
        ]
        out["coalesced"] = bool(f.flags & 0b10)
    elif f.body_kind == FOOTPRINT:
        out["bars"] = [
            {
                "generation": generation,
                "index": index,
                "t_ms": (base + ts),
                "confirm": bool(group_flags & 1),  # bit0 only; bits 1-7 are reserved and ignored
                "cells": [
                    {
                        "price": p(c[0]),
                        "bid_volume": q(c[1]),
                        "ask_volume": q(c[2]),
                        "trades": c[3],
                        "is_poc": bool(c[4] & 0b1000),
                    }
                    for c in cells
                ],
            }
            for (generation, index, ts, group_flags), cells in (f.groups or ())
        ]
        out["coalesced"] = bool(f.flags & 0b10)
    else:
        if f.prefix is None:
            raise ValueError("heatmap frame needs a prefix")
        out["columns"] = [
            {
                "t_ms": (base + f.prefix[0]),
                "price_min": p(f.prefix[1]),
                "price_step": p(f.prefix[2]),
                "bids": [float(q(r[0])) for r in f.records],
                "asks": [float(q(r[1])) for r in f.records],
            }
        ]
        out["estimated"] = bool(f.flags & 1)
    return out


def render_structured() -> str:
    rows = [
        {"name": n, "body_kind": f.body_kind, "structured": structured(f)}
        for n, f in vector_frames()
    ]
    return json.dumps(rows, indent=2) + "\n"
