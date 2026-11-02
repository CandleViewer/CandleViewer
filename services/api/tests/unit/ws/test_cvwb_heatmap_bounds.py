"""E21-X02 (#652; 23 §3.4, AC-HM-04): the server's heatmap column decoder (`ws/binary.decode`)
refuses a `row_count` above the grid's 512 rows and a `price_step` of zero or less, as
`frame_malformed`, before anything is read or sized from the wire, and a column shorter than its
rows, as the client's does (`packages/protocol/test/runtime-heatmap-bounds.test.ts`). The shared
fuzz corpus (`tests/fuzz/ws-frames/corpus.json`) runs the same cases on both decoders."""

from __future__ import annotations

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.orderflow.heatmap import ROWS
from candleviewer.ws import binary
from candleviewer.ws._generated.cvwb_layout import MAGIC
from candleviewer.ws.binary import (
    HEATMAP_COLUMN,
    HEATMAP_MAX_ROWS,
    Frame,
    FrameMalformedError,
    decode,
    encode,
)

_HEADER = struct.Struct("<IBBBBB3xIQ")
_PREFIX = struct.Struct("<IqqI")


def column(row_count: int, price_step: int, body_rows: int | None = None) -> bytes:
    """One kind-6 frame: the header (one column), its prefix, then `body_rows` rows of bytes."""
    rows = row_count if body_rows is None else body_rows
    header = _HEADER.pack(MAGIC, 1, HEATMAP_COLUMN, 0, 1, 3, 1, 1_789_132_262_100)
    return header + _PREFIX.pack(100, 99_000, price_step, row_count) + bytes(rows * 16)


def test_the_codecs_row_bound_is_the_grids() -> None:
    assert HEATMAP_MAX_ROWS == ROWS == 512
    assert len(decode(column(512, 1)).records) == 512


def test_malformed_binary_frame_a_row_count_above_512_is_refused_before_any_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_rows(*_: object) -> tuple[()]:
        raise AssertionError("rows were read for a column past the grid's bound")

    monkeypatch.setattr(binary, "_rows", no_rows)
    with pytest.raises(FrameMalformedError, match="row_count=513 is above the grid's 512 rows"):
        decode(column(513, 1))  # every row present: the grid's bound refuses it
    for row_count in (513, 2**32 - 1):  # rows the body lacks: the fit check refuses first (SR-128)
        with pytest.raises(FrameMalformedError, match="exceeds"):
            decode(column(row_count, 1, body_rows=0))


def test_malformed_binary_frame_a_price_step_of_zero_or_less_is_refused() -> None:
    for step in (0, -1, -(2**63)):
        with pytest.raises(FrameMalformedError, match=f"price_step={step} is not positive"):
            decode(column(2, step))
    assert decode(column(2, 1)).prefix == (100, 99_000, 1)


def test_malformed_binary_frame_a_heatmap_column_shorter_than_its_rows_is_refused() -> None:
    full = column(3, 1)
    assert len(decode(full).records) == 3
    with pytest.raises(FrameMalformedError, match="exceeds"):
        decode(full[:-1])  # one byte short
    with pytest.raises(FrameMalformedError, match="exceeds"):
        decode(column(3, 1, body_rows=2))  # one row short


@given(
    st.integers(0, 2**32 - 1),
    st.integers(-(2**63), 2**63 - 1),
    st.integers(0, 8),
)
def test_malformed_binary_frame_a_column_decodes_only_within_its_bounds(
    row_count: int, price_step: int, short: int
) -> None:
    """Any declared count and step: refused past the grid's rows, a step not positive, or rows
    the body lacks; otherwise decoded, and re-encoded to the very same bytes."""
    body_rows = min(row_count, HEATMAP_MAX_ROWS + 1)
    wire = column(row_count, price_step, body_rows)[: -short or None]
    fits = short == 0 and body_rows == row_count
    if row_count > HEATMAP_MAX_ROWS or price_step <= 0 or not fits:
        with pytest.raises(FrameMalformedError):
            decode(wire)
        return
    frame = decode(wire)
    assert isinstance(frame, Frame) and len(frame.records) == row_count
    assert encode(frame) == wire
