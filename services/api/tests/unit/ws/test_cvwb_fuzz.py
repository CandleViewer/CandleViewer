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
which byte mutation of small seeds cannot reach.
Failing inputs are written to ``CV_FUZZ_ARTIFACT_DIR`` (uploaded as a CI artefact, never the repo).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import struct
import tracemalloc
from pathlib import Path
from typing import Final

import pytest
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from candleviewer.ws.binary import FrameMalformedError, decode
from candleviewer.ws.codec import MAX_MSGPACK_DEPTH, MsgpackFrameError, decode_client_frame
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

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
EXAMPLES: Final[int] = int(os.environ.get("CV_FUZZ_EXAMPLES", "200"))
MAX_PEAK_BYTES: Final[int] = 1 << 20
#: The msgpack decoder's worst at-cap peak is about 1.2 MiB (`test_msgpack_decode_bounds.py`).
MSGPACK_MAX_PEAK_BYTES: Final[int] = 2 << 20
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


SEED: Final[int] = int(os.environ.get("CV_FUZZ_SEED", "12648430"))
random.seed(SEED)


def _save_failure(data: bytes, kind: str = "cvwb") -> str:
    """Dumps the input under CV_FUZZ_ARTIFACT_DIR by sha256; returns the replay string."""
    out = os.environ.get("CV_FUZZ_ARTIFACT_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"{kind}-fail-{hashlib.sha256(data).hexdigest()}.bin").write_bytes(data)
    return f"seed={SEED} b64={base64.b64encode(data).decode()}"


@pytest.mark.fuzz
@seed(SEED)
@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
    print_blob=True,
)
@given(i=st.integers(0, len(SEEDS) - 1), ops=st.lists(_op, min_size=1, max_size=6))
def test_decode_mutated_corpus_raises_only_the_typed_error(
    i: int, ops: list[tuple[str, int, int]]
) -> None:
    data = mutate(SEEDS[i], ops)
    tracemalloc.start()
    try:
        try:
            decode(data)
        except FrameMalformedError:
            pass
        except BaseException as exc:
            raise AssertionError(f"untyped {exc!r}: {_save_failure(data)}") from exc
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if peak > MAX_PEAK_BYTES:
        pytest.fail(f"decode peaked at {peak} B: {_save_failure(data)}")


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


def _check_msgpack(data: bytes) -> None:
    """The SR-185 invariant for one input: a typed refusal or a bounded JSON-like value."""
    tracemalloc.start()
    try:
        try:
            value, refused = decode_client_frame(data), False
        except MsgpackFrameError:
            value, refused = None, True
        except BaseException as exc:
            raise AssertionError(f"untyped {exc!r}: {_save_failure(data, 'msgpack')}") from exc
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if not refused and not 0 <= _json_like_depth(value) <= MAX_MSGPACK_DEPTH:
        pytest.fail(f"decoded beyond the SR-185 bounds: {_save_failure(data, 'msgpack')}")
    if peak > MSGPACK_MAX_PEAK_BYTES:
        pytest.fail(f"msgpack decode peaked at {peak} B: {_save_failure(data, 'msgpack')}")


_FUZZ_SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
    print_blob=True,
)


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(i=st.integers(0, len(MSGPACK_SEEDS) - 1), ops=st.lists(_op, min_size=1, max_size=6))
def test_msgpack_client_decode_mutated_corpus_raises_only_the_typed_error(
    i: int, ops: list[tuple[str, int, int]]
) -> None:
    _check_msgpack(mutate(MSGPACK_SEEDS[i], ops))


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


@pytest.mark.fuzz
@seed(SEED)
@_FUZZ_SETTINGS
@given(
    nest=st.integers(0, 1_100),
    claim=st.sampled_from(_CLAIMS),
    kind=st.sampled_from(["array", "map"]),
    body=st.lists(_token, max_size=64),
    repeat=st.integers(1, 4_096),
    pad=st.integers(0, MAX_INBOUND_FRAME_BYTES),
)
def test_msgpack_client_decode_structured_frames_stay_bounded(
    nest: int, claim: int, kind: str, body: list[bytes], repeat: int, pad: int
) -> None:
    frame = _header(kind, claim) * nest + b"".join(body) * repeat + b"\xc0" * pad
    _check_msgpack(frame[:MAX_INBOUND_FRAME_BYTES])


# SR-128 (targeted): every count field that cannot fit is rejected up front by `_fits`. Removing
# the body-prefix (row_count), per-group cell_count or trailing record-count check fails here.
# The OUTER footprint group-count check (L235) and the per-group prefix `_fits(1, ...)` (L239) back
# each other up (both raise "exceeds"); removing one alone costs at most a bounded loop, never an
# allocation, so neither is separately observable and neither is probed on its own.
_VALUES = (0, 1, 0xFFFF, 0x7FFFFFFF, 0xFFFFFFFF)
# (body_kind, count offset, stride, bytes before the first counted record)
_SITES = (
    (1, 12, 17, 24),
    (2, 12, 17, 24),
    (3, 12, 22, 24),
    (5, 28, 33, 32),
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
