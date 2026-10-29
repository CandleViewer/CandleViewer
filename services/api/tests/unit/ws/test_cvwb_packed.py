"""#605 (M-1): a packed CVWB frame (`binary.pack`, `Frame.raw`) is a part encoded once. It must be
byte-identical to the frame it was packed from on every later encode, with the header's flags,
scales and time base the caller sets (what `render` and a `d` set per subscription and chunk), so
a snapshot or a fan-out re-encodes only the 24-byte header. Every kind, and the gateway's render
of a snapshot, packed or not, give the same bytes."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws.binary import (
    BOOK_DELTA,
    FLAG_ESTIMATED,
    HEATMAP_COLUMN,
    Frame,
    FrameEncodeError,
    encode,
    encode_b64,
    frame_size,
    pack,
)
from candleviewer.ws.cvwb_vectors import vector_frames
from candleviewer.ws.sequencing import SnapshotBody, render, split_frame
from tests.unit.ws.test_cvwb_binary import frames


@pytest.mark.parametrize(("name", "frame"), vector_frames(), ids=[n for n, _ in vector_frames()])
def test_every_vector_frame_packs_to_its_own_bytes(name: str, frame: Frame) -> None:
    packed = pack(frame)
    assert packed.raw is not None and packed.records == () and pack(packed) is packed
    assert encode(packed) == encode(frame) and encode_b64(packed) == encode_b64(frame)
    assert frame_size(packed) == frame_size(frame) == len(encode(frame))


@settings(max_examples=300, deadline=None)
@given(
    frames(),
    st.integers(0, 0b1111),
    st.integers(0, 8),
    st.integers(0, 8),
    st.integers(0, 2**64 - 1),
)
def test_a_packed_frame_with_a_new_header_encodes_as_the_frame_with_that_header(
    frame: Frame, flags: int, ps: int, qs: int, ts: int
) -> None:
    def head(f: Frame) -> Frame:
        return replace(f, flags=flags, price_scale=ps, qty_scale=qs, ts_base_ms=ts)

    assert encode(head(pack(frame))) == encode(head(frame))
    assert encode_b64(head(pack(frame))) == encode_b64(head(frame))
    want = encode_b64(replace(frame, flags=flags, price_scale=ps, qty_scale=qs))
    # `encode_b64`'s own overrides, on a packed frame and a plain one
    assert encode_b64(pack(frame), flags=flags, price_scale=ps, qty_scale=qs) == want
    assert encode_b64(frame, flags=flags, price_scale=ps, qty_scale=qs) == want


def test_a_packed_frame_holds_bytes_only_and_of_its_kind() -> None:
    with pytest.raises(FrameEncodeError, match="bytes only"):
        Frame(HEATMAP_COLUMN, ((1, 2),), raw=b"x" * 40)
    with pytest.raises(FrameEncodeError, match="tail"):
        Frame(HEATMAP_COLUMN, tail="AAAA")
    vectors = dict(vector_frames())
    wrong = replace(pack(vectors["heatmap_column"]), body_kind=BOOK_DELTA)
    with pytest.raises(FrameEncodeError, match="not of its kind"):
        encode(wrong)
    with pytest.raises(FrameEncodeError, match="not of its kind"):
        encode_b64(wrong)
    with pytest.raises(FrameEncodeError, match="flag"):
        encode_b64(pack(vectors["heatmap_column"]), flags=0b1_0000)
    with pytest.raises(FrameEncodeError, match="out of range"):
        encode_b64(pack(vectors["heatmap_column"]), price_scale=256)
    with pytest.raises(FrameEncodeError, match="flag"):
        encode(replace(pack(vectors["heatmap_column"]), flags=0b1_0000))


def test_a_packed_part_is_never_cut() -> None:
    packed = pack(dict(vector_frames())["heatmap_column"])
    assert split_frame(packed, 10_000) == [packed]
    with pytest.raises(FrameEncodeError, match="packed part"):
        split_frame(packed, 10)


def _sub(encoding: str, replay: str | None = None) -> Any:
    family = SimpleNamespace(family="heatmap")
    return SimpleNamespace(topic=SimpleNamespace(family=family), effective={"encoding": encoding},
                           replay_session_id=replay)  # fmt: skip


@pytest.mark.parametrize("replay", [None, "8f3a2c1e-0000-4000-8000-000000000001"])
def test_render_of_packed_parts_is_byte_identical_to_render_of_plain_ones(
    replay: str | None,
) -> None:
    """The gateway's snapshot render: same b64 chunks, `partial` bits, replay bit and
    `estimated` bit, packed or not (only the producer chooses to pack)."""
    parts = tuple(
        Frame(
            HEATMAP_COLUMN,
            ((i, 2 * i), (3, 4)),
            0,
            1,
            3,
            1_700_000_000_000 + 100 * i,
            prefix=(0, 6_309_240 + i, 1),
        )
        for i in range(5)
    )
    columns = [{"t_ms": p.ts_base_ms, "complete": True} for p in parts]
    plain = SnapshotBody({"symbol": "BTCUSDT", "columns": columns}, parts, 1, 3, estimated=True)
    packed = replace(plain, parts=tuple(pack(p) for p in parts))
    a, b = render(_sub("binary", replay), plain, 4096), render(_sub("binary", replay), packed, 4096)
    assert a.parts == b.parts and len(a.parts) == 5
    assert a.complete == b.complete and a.root == b.root
    assert encode(replace(parts[0], flags=FLAG_ESTIMATED)) != encode(parts[0])  # bits matter
