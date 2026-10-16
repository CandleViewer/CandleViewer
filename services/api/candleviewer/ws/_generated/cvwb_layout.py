"""GENERATED FILE - DO NOT EDIT BY HAND.

Generator: packages/protocol/scripts/generate-cvwb-layout.mjs (E17-T02).
Source: packages/protocol/cvwb-layout.json (docs/plan/23-ws-protocol.md section 3.4).
Run `pnpm --filter @candleviewer/protocol generate`.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class Part(NamedTuple):
    size: int
    fmt: str
    fields: tuple[str, ...]
    offsets: dict[str, int]
    enums: dict[str, tuple[int, ...]]


class Kind(NamedTuple):
    id: int
    name: str
    format_version: int
    length_rule: str
    record: Part
    trailer: Part | None
    group_prefix: Part | None
    body_prefix: Part | None


MAGIC: Final = 1129731906
HEADER: Final = Part(24, "<IBBBBB3xIQ", ("magic", "format_version", "body_kind", "flags", "price_scale", "qty_scale", "record_count", "ts_base_ms"), {"magic": 0, "format_version": 4, "body_kind": 5, "flags": 6, "price_scale": 7, "qty_scale": 8, "record_count": 12, "ts_base_ms": 16}, {})
HEADER_FLAGS: Final[tuple[str, ...]] = ("estimated", "coalesced", "replay", "partial")
KINDS: Final[dict[int, Kind]] = {
    1: Kind(
        1,
        "book_snapshot",
        1,
        "min",
        Part(17, "<BqQ", ("side", "price", "size"), {"side": 0, "price": 1, "size": 9}, {"side": (0, 1)}),
        Part(16, "<QQ", ("xu", "xseq"), {"xu": 0, "xseq": 8}, {}),
        None,
        None,
    ),
    2: Kind(
        2,
        "book_delta",
        1,
        "min",
        Part(17, "<BqQ", ("side", "price", "size"), {"side": 0, "price": 1, "size": 9}, {"side": (0, 1)}),
        None,
        None,
        None,
    ),
    3: Kind(
        3,
        "trades",
        1,
        "min",
        Part(22, "<IqQBB", ("ts_offset_ms", "price", "size", "side", "flags"), {"ts_offset_ms": 0, "price": 4, "size": 12, "side": 20, "flags": 21}, {"side": (0, 1)}),
        None,
        None,
        None,
    ),
    4: Kind(
        4,
        "bars",
        2,
        "exact",
        Part(85, "<QQIqqqqQQIqB4x", ("generation", "index", "ts_offset_ms", "open", "high", "low", "close", "volume", "turnover", "trades", "delta", "flags"), {"generation": 0, "index": 8, "ts_offset_ms": 16, "open": 20, "high": 28, "low": 36, "close": 44, "volume": 52, "turnover": 60, "trades": 68, "delta": 72, "flags": 80}, {}),
        None,
        None,
        None,
    ),
    5: Kind(
        5,
        "footprint",
        2,
        "min",
        Part(33, "<qQQIB4x", ("price", "bid_volume", "ask_volume", "trades", "flags"), {"price": 0, "bid_volume": 8, "ask_volume": 16, "trades": 24, "flags": 28}, {}),
        None,
        Part(28, "<QQIIB3x", ("generation", "index", "ts_offset_ms", "cell_count", "flags"), {"generation": 0, "index": 8, "ts_offset_ms": 16, "cell_count": 20, "flags": 24}, {}),
        None,
    ),
    6: Kind(
        6,
        "heatmap_column",
        1,
        "min",
        Part(16, "<QQ", ("bid_size", "ask_size"), {"bid_size": 0, "ask_size": 8}, {}),
        None,
        None,
        Part(24, "<IqqI", ("ts_offset_ms", "price_min", "price_step", "row_count"), {"ts_offset_ms": 0, "price_min": 4, "price_step": 12, "row_count": 20}, {}),
    ),
}
