"""E17-T02 part B: nightly mutation fuzz of the CVWB decoder (SR-155) seeded from the corpus.

Deselected from the default lane by `addopts` (`-m "not fuzz and not perf"`); run explicitly with
``pytest -m fuzz --no-cov``. Default 200 examples; the nightly sets ``CV_FUZZ_EXAMPLES=20000`` and
``CV_FUZZ_SEED`` (Hypothesis runs derandomised from it, so a failure replays from the seed).
Invariant: ``decode`` returns a ``Frame`` or raises ONLY ``FrameMalformedError``, and one decode
never allocates more than ``MAX_PEAK_BYTES`` (SR-128: wire counts never size an allocation).
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

REPO = Path(__file__).resolve().parents[5]
SEEDS: Final[list[bytes]] = [
    bytes.fromhex(s["hex"])
    for s in json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
]
EXAMPLES: Final[int] = int(os.environ.get("CV_FUZZ_EXAMPLES", "200"))
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


SEED: Final[int] = int(os.environ.get("CV_FUZZ_SEED", "12648430"))
random.seed(SEED)


def _save_failure(data: bytes) -> str:
    """Dumps the input under CV_FUZZ_ARTIFACT_DIR by sha256; returns the replay string."""
    out = os.environ.get("CV_FUZZ_ARTIFACT_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"cvwb-fail-{hashlib.sha256(data).hexdigest()}.bin").write_bytes(data)
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
