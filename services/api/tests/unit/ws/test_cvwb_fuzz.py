"""E17-T02 part B: nightly mutation fuzz of the CVWB decoder (SR-155) seeded from the corpus, and
of the `cv.v1.msgpack` client-frame decoder (SR-185, #2483) seeded from `msgpack-client.json`.

Deselected from the default lane by `addopts` (`-m "not fuzz and not perf"`); run explicitly with
``pytest -m fuzz --no-cov``. Default 200 examples; the nightly sets ``CV_FUZZ_EXAMPLES=20000`` and
``CV_FUZZ_SEED`` (Hypothesis runs derandomised from it, so a failure replays from the seed).
Invariant: ``decode`` returns a ``Frame`` or raises ONLY ``FrameMalformedError``, and one decode
never allocates more than ``MAX_PEAK_BYTES`` (SR-128: wire counts never size an allocation). The
msgpack decoder returns a JSON-like value within ``MAX_MSGPACK_DEPTH`` or raises ONLY
``MsgpackFrameError``, within ``MSGPACK_MAX_PEAK_BYTES``. Its second target builds frames from
array and map headers (claims up to 2^32 - 1, nesting past 1 024, padding to the inbound cap),
which byte mutation of small seeds cannot reach; its third builds open levels, each holding up to
its cap of children before opening the next (distinct or duplicate map keys).
A failure reports only its target and a sha256 digest of (seed, input): the tests take one redacted
`_Input`, and Hypothesis reports nothing (no failing-case report, blob or explanation). The pair is
written to ``CV_FUZZ_ARTIFACT_DIR``, which CI uploads only encrypted (fuzz-nightly.yml). Those
helpers are shared with the parser suite (`_fuzz.py`).
"""

from __future__ import annotations

import json
import random
import struct
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from hypothesis import given, seed
from hypothesis import strategies as st

from candleviewer.ws.binary import FrameMalformedError, decode
from candleviewer.ws.codec import (
    MAX_MSGPACK_ARRAY_LEN,
    MAX_MSGPACK_DEPTH,
    MsgpackFrameError,
    decode_client_frame,
)
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES
from tests.unit.ws._fuzz import FUZZ_SETTINGS as _FUZZ_SETTINGS
from tests.unit.ws._fuzz import SEED
from tests.unit.ws._fuzz import Input as _Input
from tests.unit.ws._fuzz import save_failure as _save_failure
from tests.unit.ws._msgpack_bounds import peak_bound

REPO = Path(__file__).resolve().parents[5]
SEEDS: Final[list[bytes]] = [
    bytes.fromhex(s["hex"])
    for s in json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
]
MSGPACK_SEEDS: Final[list[bytes]] = [
    bytes.fromhex(s["hex"])
    for s in json.loads(
        (REPO / "tests/fuzz/ws-frames/msgpack-client.json").read_text(encoding="utf-8")
    )
]
MAX_PEAK_BYTES: Final[int] = 1 << 20
_INTERESTING: Final[tuple[int, ...]] = (0, 1, 2, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE)

_op = st.one_of(
    st.tuples(st.just("flip"), st.integers(0, 400), st.integers(0, 7)),
    st.tuples(st.just("trunc"), st.integers(0, 400), st.just(0)),
    st.tuples(st.just("count"), st.integers(0, 400), st.sampled_from(_INTERESTING)),
    st.tuples(st.just("extend"), st.integers(0, 64), st.integers(0, 255)),
    st.tuples(st.just("set"), st.integers(0, 400), st.integers(0, 255)),
)


def mutate(seed: bytes, ops: list[tuple[str, int, int]]) -> bytes:
    buf = bytearray(seed)
    for kind, a, b in ops:
        if kind == "trunc":
            del buf[a:]
        elif kind == "extend":
            buf.extend(bytes([b]) * a)
        elif not buf:
            continue
        elif kind == "flip":
            buf[a % len(buf)] ^= 1 << b
        elif kind == "set":
            buf[a % len(buf)] = b
        elif len(buf) >= 4:  # count tampering: rewrite a u32 at any offset
            struct.pack_into("<I", buf, a % (len(buf) - 3), b)
    return bytes(buf)


random.seed(SEED)


def _json_like_depth(value: object) -> int:
    """Container nesting of a decoded value, or -1 if it holds anything JSON could not carry."""
    stack: list[tuple[object, int]] = [(value, 0)]
    deepest = 0
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            if not all(isinstance(key, str) for key in node):
                return -1
            children: list[object] = list(node.values())
        elif isinstance(node, list):
            children = list(node)
        elif isinstance(node, float):
            if node != node or node in (float("inf"), float("-inf")):
                return -1
            continue
        elif isinstance(node, str | int | bool) or node is None:
            continue
        else:
            return -1
        deepest = max(deepest, depth + 1)
        stack.extend((child, depth + 1) for child in children)
    return deepest


def _check(
    case: _Input,
    decoder: Callable[[bytes], object],
    typed: type[Exception],
    peak_cap: Callable[[], int],
    depth_cap: int | None = None,
) -> None:
    """One input against a decoder's invariant: it returns or raises only `typed`, never nests
    past `depth_cap` (when set) and never peaks above `peak_cap()`. A violation, or a check that
    raises, fails with the target and the digest, raised where no exception is in flight."""
    data = case.data  # built before tracing starts: the peak is the decoder's alone
    why = ""
    value: object = None
    tracemalloc.start()
    try:
        try:
            value = decoder(data)
        except typed:
            pass
        except BaseException as exc:
            why = f"untyped {type(exc).__name__}"
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    try:  # the peak first: a value that broke it may be too big to walk
        if not why and peak > peak_cap():
            why = "decode peaked above its cap"
        if not why and depth_cap is not None and not 0 <= _json_like_depth(value) <= depth_cap:
            why = "decoded beyond the SR-185 bounds"
    except Exception as exc:
        why = f"bounds check raised {type(exc).__name__}"
    finally:
        del data, value  # nothing derived from the input stays in the frame that fails
    if why:
        raise AssertionError(f"{why}: {_save_failure(case)}") from None


def _check_msgpack(case: _Input) -> None:
    """The SR-185 invariant for one input: a typed refusal or a bounded JSON-like value."""
    _check(case, decode_client_frame, MsgpackFrameError, peak_bound, MAX_MSGPACK_DEPTH)


@st.composite
def _mutated(draw: st.DrawFn, target: str, seeds: list[bytes]) -> _Input:
    i = draw(st.integers(0, len(seeds) - 1))
    ops = draw(st.lists(_op, min_size=1, max_size=6))
    return _Input(target, lambda: mutate(seeds[i], ops))


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(case=_mutated("cvwb", SEEDS))
def test_decode_mutated_corpus_raises_only_the_typed_error(case: _Input) -> None:
    _check(case, decode, FrameMalformedError, lambda: MAX_PEAK_BYTES)


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(case=_mutated("msgpack", MSGPACK_SEEDS))
def test_msgpack_client_decode_mutated_corpus_raises_only_the_typed_error(case: _Input) -> None:
    _check_msgpack(case)


_CLAIMS: Final[tuple[int, ...]] = (0, 1, 2, 15, 16, 63, 64, 65, 255, 0xFFFF, 1 << 31, 0xFFFFFFFF)


def _header(kind: str, n: int) -> bytes:
    """An array or map header claiming `n` entries, in its shortest form."""
    small, h16, h32 = (0x90, b"\xdc", b"\xdd") if kind == "array" else (0x80, b"\xde", b"\xdf")
    if n < 16:
        return bytes([small | n])
    return h16 + n.to_bytes(2, "big") if n <= 0xFFFF else h32 + n.to_bytes(4, "big")


_token = st.one_of(
    st.builds(_header, st.sampled_from(["array", "map"]), st.sampled_from(_CLAIMS)),
    st.sampled_from(
        [b"\xc0", b"\xc3", b"\x01", b"\xa1t", b"\xa4ping", b"\xcb\x7f\xf8" + bytes(6), b"\xc4\x00"]
    ),
)


def _structured(
    nest: int, claim: int, kind: str, body: list[bytes], repeat: int, pad: int
) -> _Input:
    def build() -> bytes:
        frame = _header(kind, claim) * nest + b"".join(body) * repeat + b"\xc0" * pad
        return frame[:MAX_INBOUND_FRAME_BYTES]

    return _Input("msgpack", build)


_STRUCTURED = st.builds(
    _structured,
    nest=st.integers(0, 1_100),
    claim=st.sampled_from(_CLAIMS),
    kind=st.sampled_from(["array", "map"]),
    body=st.lists(_token, max_size=64),
    repeat=st.integers(1, 4_096),
    pad=st.integers(0, MAX_INBOUND_FRAME_BYTES),
)


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(case=_STRUCTURED)
def test_msgpack_client_decode_structured_frames_stay_bounded(case: _Input) -> None:
    _check_msgpack(case)


# SR-128 (targeted): every count field that cannot fit is rejected up front by `_fits`. Removing
# the body-prefix (row_count), per-group cell_count or trailing record-count check fails here.
# The OUTER footprint group-count `_fits(count, ...)` and the per-group prefix `_fits(1, ...)` back
# each other up (both raise "exceeds"); removing one alone costs at most a bounded loop, never an
# allocation, so this test probes neither. The outer check's 28-byte v2 stride (#2529) is pinned
# by its message in test_cvwb_binary.py instead.
_VALUES = (0, 1, 0xFFFF, 0x7FFFFFFF, 0xFFFFFFFF)
# (body_kind, count offset, stride, bytes before the first counted record)
_SITES = (
    (1, 12, 17, 24),
    (2, 12, 17, 24),
    (3, 12, 22, 24),
    (5, 44, 33, 52),  # first group's cell_count at 24 + 20; cells after the 28-byte prefix
    (6, 44, 16, 48),
)


def test_every_unfittable_wire_count_is_rejected_up_front() -> None:
    probes = 0
    for kind, off, stride, base in _SITES:
        for raw in SEEDS:
            if len(raw) < off + 4 or raw[5] != kind:
                continue
            try:
                decode(raw)
            except FrameMalformedError:
                continue
            avail = len(raw) - base
            for value in (*_VALUES, avail // stride + 1):
                if value * stride <= avail:
                    continue
                data = bytearray(raw)
                struct.pack_into("<I", data, off, value)
                with pytest.raises(FrameMalformedError, match="exceeds"):
                    decode(bytes(data))
                probes += 1
    assert probes > 20


def _key(level: int, i: int) -> bytes:
    """A 4-character map key unique to (level, i) within one frame."""
    return b"\xa4" + bytes(
        [0x21 + level // 94 % 94, 0x21 + level % 94, 0x21 + i // 94, 0x21 + i % 94]
    )


def _level(kind: str, width: int, child: bytes, distinct: bool, level: int) -> bytes:
    """One level holding `width` children; its last slot opens the next level. `distinct` keys
    are new to the process (interning pressure, `_msgpack_bounds.py`), else all `""`."""
    if kind == "array":
        if distinct and child == _ONE_ENTRY_MAP:
            return _header("array", width + 1) + b"".join(
                b"\x81" + _key(level, i) + b"\xe0" for i in range(width)
            )
        return _header("array", width + 1) + child * width
    keys = [_key(level, i) if distinct else b"\xa0" for i in range(width + 1)]
    return _header("map", width + 1) + b"".join(k + child for k in keys[:-1]) + keys[-1]


_ONE_ENTRY_MAP: Final = b"\x81\xa0\xe0"  # a completed one-entry map


def _open_levels(kind: str, width: int, child: bytes, levels: int, distinct: bool) -> _Input:
    def build() -> bytes:
        frame = b"".join(_level(kind, width, child, distinct, n) for n in range(levels))
        return frame[:MAX_INBOUND_FRAME_BYTES]

    return _Input("msgpack", build)


_OPEN_LEVELS = st.builds(
    _open_levels,
    kind=st.sampled_from(["array", "map"]),
    width=st.integers(0, MAX_MSGPACK_ARRAY_LEN),
    child=st.sampled_from(
        [
            b"\x80",
            b"\x90",
            b"\xc0",
            b"\xe0",  # an int CPython does not cache: 32 B per input byte
            b"\xa2ab",
            b"\xcd\x12\x34",
            b"\xcb" + bytes(8),
            b"\xd6\xff\x00\x00\x00\x01",  # a timestamp, decoded without `ext_hook`
            _ONE_ENTRY_MAP,
        ]
    ),
    levels=st.integers(1, 1_100),
    distinct=st.booleans(),
)


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(case=_OPEN_LEVELS)
def test_msgpack_client_decode_open_levels_stay_bounded(case: _Input) -> None:
    """#2509 review: values held in containers that never complete are charged late."""
    _check_msgpack(case)
