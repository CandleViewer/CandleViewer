"""E17-X02 (#415): the systematic decoder seeds of the ticket's technical notes, in the PR lane.

Each decode returns or raises only its typed error, and peaks at no more than 1 MiB (SR-128), as
tracemalloc measures it (started here unless it already runs; each input is built first):
- each bit of the 24-byte header flipped, on every valid seed of `corpus.json`;
- every valid seed cut at each length;
- each count field of a valid seed (the header's `record_count`, and the body prefix's
  `row_count` or the first group's `cell_count`) set to each power of two up to 2^31;
- msgpack maps nested 1 to 100 deep, decoded up to `MAX_MSGPACK_DEPTH` and refused past it;
- a 256 KiB frame of fixed-seed random bytes with a valid magic, as drawn and under each body
  kind with its format version.
A failing case is named by its seed and change and its error's class, never its bytes or the
error's text. The mutation fuzz of the same decoders runs nightly (`test_cvwb_fuzz.py`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import struct
import tracemalloc
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Final

from candleviewer.ws._generated.cvwb_layout import HEADER, KINDS, MAGIC
from candleviewer.ws.binary import FrameMalformedError, decode
from candleviewer.ws.codec import MAX_MSGPACK_DEPTH, MsgpackFrameError, decode_client_frame
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

REPO = Path(__file__).resolve().parents[5]
VALID: Final[list[tuple[str, bytes]]] = [
    (s["name"], bytes.fromhex(s["hex"]))
    for s in json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
    if s["expect"] == "ok"
]
MAX_PEAK_BYTES: Final = 1 << 20
COUNT: Final = HEADER.offsets["record_count"]
Cases = Iterable[tuple[str, bytes]]


@contextlib.contextmanager
def _traced() -> Iterator[None]:
    started = not tracemalloc.is_tracing()
    if started:
        tracemalloc.start()
    try:
        yield
    finally:
        if started:
            tracemalloc.stop()


def _sweep(cases: Cases, decoder: Callable[[bytes], object], typed: type[Exception]) -> list[str]:
    """Decodes each case; fails naming every one that raised another error or peaked past the
    cap. Returns the names of the cases that decoded."""
    bad: list[str] = []
    decoded: list[str] = []
    with _traced():
        for name, data in cases:
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]
            try:
                decoder(data)
                decoded.append(name)
            except typed:
                pass
            except Exception as exc:
                bad.append(f"{name}: untyped {type(exc).__name__}")
                continue
            if (peak := tracemalloc.get_traced_memory()[1] - base) > MAX_PEAK_BYTES:
                bad.append(f"{name}: peaked at {peak} B")
    assert not bad, f"{len(bad)} cases, first {bad[:5]}"
    return decoded


def _set(raw: bytes, at: int, value: int) -> bytes:
    data = bytearray(raw)
    struct.pack_into("<I", data, at, value)
    return bytes(data)


def _count_fields(raw: bytes) -> list[int]:
    """Offsets of the count fields `raw` holds: the header's, then its kind's nested one."""
    kind = KINDS[raw[HEADER.offsets["body_kind"]]]
    nested = [(kind.body_prefix, "row_count"), (kind.group_prefix, "cell_count")]
    offsets = [HEADER.size + p.offsets[f] for p, f in nested if p is not None]
    return [COUNT, *(at for at in offsets if at + 4 <= len(raw))]


def test_cvwb_header_bit_flips_raise_only_the_typed_error_within_1_mib() -> None:
    def flipped() -> Cases:
        for name, raw in VALID:
            for bit in range(HEADER.size * 8):
                data = bytearray(raw)
                data[bit // 8] ^= 1 << bit % 8
                yield f"{name} bit {bit}", bytes(data)

    _sweep(flipped(), decode, FrameMalformedError)


def test_cvwb_valid_seeds_cut_at_every_length_raise_only_the_typed_error_within_1_mib() -> None:
    cuts = ((f"{name} cut at {n}", raw[:n]) for name, raw in VALID for n in range(len(raw)))
    _sweep(cuts, decode, FrameMalformedError)


def test_cvwb_counts_at_each_power_of_two_up_to_2_31_raise_only_the_typed_error() -> None:
    counts = (
        (f"{name} count at {at} = 2^{p}", _set(raw, at, 1 << p))
        for name, raw in VALID
        for at in _count_fields(raw)
        for p in range(32)
    )
    _sweep(counts, decode, FrameMalformedError)


def test_msgpack_maps_nested_to_depth_100_are_refused_past_the_depth_cap_within_1_mib() -> None:
    def maps(depth: int) -> bytes:  # {"m": {"m": ... {}}}
        return b"\x81\xa1m" * (depth - 1) + b"\x80"

    nested = [(f"maps {depth} deep", maps(depth)) for depth in range(1, 101)]
    decoded = _sweep(nested, decode_client_frame, MsgpackFrameError)
    assert decoded == [name for name, _ in nested[:MAX_MSGPACK_DEPTH]]


def test_cvwb_256_kib_random_frame_with_a_valid_magic_raises_only_the_typed_error() -> None:
    noise = bytearray(hashlib.shake_256(b"E17-X02 random frame").digest(MAX_INBOUND_FRAME_BYTES))
    struct.pack_into("<I", noise, 0, MAGIC)

    def frames() -> Cases:
        yield "random", bytes(noise)
        for kind in KINDS.values():
            noise[HEADER.offsets["format_version"]] = kind.format_version
            noise[HEADER.offsets["body_kind"]] = kind.id
            yield f"random as {kind.name}", bytes(noise)

    assert _sweep(frames(), decode, FrameMalformedError) == []
