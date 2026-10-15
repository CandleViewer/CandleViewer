"""SR-185: the `cv.v1.msgpack` client decoder is bounded and fails only as `frame_malformed`."""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path
from typing import Any, Final

import msgpack
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.ws.codec import (
    MAX_MSGPACK_CONTAINER_LEN,
    MAX_MSGPACK_DEPTH,
    MAX_MSGPACK_VALUES,
    MsgpackFrameError,
    decode_client_frame,
)
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

REPO = Path(__file__).resolve().parents[5]
#: Worst peak the at-cap shapes below reach is about 1.2 MiB (64-ary trees of empty maps).
MAX_PEAK_BYTES: Final = 2 << 20
CORPUS: Final[list[dict[str, str]]] = json.loads(
    (REPO / "tests/fuzz/ws-frames/msgpack-client.json").read_text(encoding="utf-8")
)


def _pack(value: Any) -> bytes:
    packed: bytes = msgpack.packb(value, use_bin_type=True)
    return packed


def _arrays(depth: int) -> Any:
    value: Any = None
    for _ in range(depth):
        value = [value]
    return value


def _maps(depth: int) -> Any:
    value: Any = None
    for _ in range(depth):
        value = {"a": value}
    return value


@pytest.mark.parametrize("seed", CORPUS, ids=[s["name"] for s in CORPUS])
def test_msgpack_corpus_seed_decodes_as_its_expectation(seed: dict[str, str]) -> None:
    data = bytes.fromhex(seed["hex"])
    if seed["expect"] == "ok":
        decode_client_frame(data)
    else:
        with pytest.raises(MsgpackFrameError):
            decode_client_frame(data)


@pytest.mark.parametrize("build", [_arrays, _maps], ids=["arrays", "maps"])
def test_msgpack_depth_limit_exact_accepted_and_plus_one_rejected(build: Any) -> None:
    assert decode_client_frame(_pack(build(MAX_MSGPACK_DEPTH))) == build(MAX_MSGPACK_DEPTH)
    with pytest.raises(MsgpackFrameError, match="nesting"):
        decode_client_frame(_pack(build(MAX_MSGPACK_DEPTH + 1)))


def test_msgpack_depth_counts_maps_and_arrays_together() -> None:
    mixed = {"p": _arrays(MAX_MSGPACK_DEPTH - 1)}
    assert decode_client_frame(_pack(mixed)) == mixed
    with pytest.raises(MsgpackFrameError, match="nesting"):
        decode_client_frame(_pack({"p": _arrays(MAX_MSGPACK_DEPTH)}))


def test_msgpack_ext_types_are_refused_by_the_unpacker_itself() -> None:
    with pytest.raises(MsgpackFrameError, match="ext type 1"):
        decode_client_frame(_pack(msgpack.ExtType(1, b"x")))
    with pytest.raises(MsgpackFrameError, match="Timestamp"):  # ext -1, decoded by msgpack
        decode_client_frame(_pack(msgpack.Timestamp(1, 0)))


def test_msgpack_frame_over_the_inbound_cap_is_refused_before_decoding() -> None:
    with pytest.raises(MsgpackFrameError, match="inbound cap") as exc:
        decode_client_frame(b"\xc0" * (MAX_INBOUND_FRAME_BYTES + 1))
    assert exc.value.__cause__ is None  # refused by size alone: the unpacker never ran


def test_msgpack_frame_of_exactly_the_inbound_cap_is_decoded() -> None:
    text = "x" * (MAX_INBOUND_FRAME_BYTES - 5)  # str32: a 5-byte header
    assert len(_pack(text)) == MAX_INBOUND_FRAME_BYTES
    assert decode_client_frame(_pack(text)) == text


def test_msgpack_frame_error_is_a_value_error_with_its_cause() -> None:
    assert issubclass(MsgpackFrameError, ValueError)  # the gateway's malformed-frame path
    with pytest.raises(MsgpackFrameError) as exc:
        decode_client_frame(b"\x81\xa1t")
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.parametrize(
    "frame", [s for s in CORPUS if s["name"].startswith("valid-")], ids=lambda s: s["name"]
)
def test_msgpack_client_frame_decodes_to_the_json_envelope(frame: dict[str, str]) -> None:
    value = decode_client_frame(bytes.fromhex(frame["hex"]))
    assert json.loads(json.dumps(value)) == value  # exactly what the JSON path would build


_json_like = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(2**63), 2**64 - 1)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(), children),
    max_leaves=40,
)


@given(value=_json_like)
def test_msgpack_any_json_like_value_round_trips(value: Any) -> None:
    assert decode_client_frame(_pack(value)) == value


@given(value=_json_like)
def test_msgpack_any_value_wrapped_past_the_cap_is_refused(value: Any) -> None:
    wrapped = value
    for _ in range(MAX_MSGPACK_DEPTH + 1):
        wrapped = [wrapped]
    with pytest.raises(MsgpackFrameError, match="nesting"):
        decode_client_frame(_pack(wrapped))


def test_msgpack_input_that_is_not_bytes_is_refused() -> None:
    with pytest.raises(MsgpackFrameError, match="binary"):
        decode_client_frame("\x81\xa1t\xa4ping")  # type: ignore[arg-type]  # a text frame


@pytest.mark.parametrize(
    "build", [lambda n: [None] * n, lambda n: {str(i): None for i in range(n)}]
)
def test_msgpack_container_length_cap_exact_accepted_and_plus_one_rejected(build: Any) -> None:
    assert decode_client_frame(_pack(build(MAX_MSGPACK_CONTAINER_LEN)))
    with pytest.raises(MsgpackFrameError) as exc:
        decode_client_frame(_pack(build(MAX_MSGPACK_CONTAINER_LEN + 1)))
    assert "exceeds max_" in str(exc.value.__cause__)  # the unpacker refused the header


def _budget_frame(extra: int) -> bytes:
    """Exactly `MAX_MSGPACK_VALUES` + `extra` values: 64 + 63 x 256 + 4 x 48 = 16 384."""
    level2 = [[None] * 3] * 64
    last = [[None] * 3] * 48 + [None] * extra
    return _pack([level2] * 63 + [last])


def test_msgpack_value_budget_exact_accepted_and_plus_one_rejected() -> None:
    assert MAX_MSGPACK_VALUES == 16_384  # _budget_frame is built for this budget
    decode_client_frame(_budget_frame(0))
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_budget_frame(1))


def test_msgpack_map_entries_count_twice_against_the_budget() -> None:
    entries = {str(i): None for i in range(MAX_MSGPACK_CONTAINER_LEN)}  # 128 values each
    frame = [[entries] * 2] * 64  # 64 + 128 + 128 maps x 128 = 16 576 (8 384 counted once)
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_pack(frame))


def test_msgpack_schema_maximal_sub_fits_the_budget() -> None:
    opts = {
        "metrics": [f"m{j}" for j in range(12)],
        "exchange_account_ids": [f"a{j}" for j in range(25)],
        "symbols": [f"S{j}" for j in range(40)],
        "throttle_ms": 100,
        "coalesce": True,
        "depth": 50,
        "encoding": "structured",
    }
    topics = [{"ch": f"positions.S{i}", "opts": opts} for i in range(50)]
    frame = {"t": "sub", "id": "s", "p": {"topics": topics}}
    assert decode_client_frame(_pack(frame)) == frame


def _at_cap(prefix: bytes) -> bytes:
    return (prefix + b"\xc0" * MAX_INBOUND_FRAME_BYTES)[:MAX_INBOUND_FRAME_BYTES]


def _tree(leaf: bytes) -> bytes:
    """A 64-ary tree, three levels deep, of `leaf`, cut at the inbound cap."""
    inner = b"\xdc\x00\x40" + leaf * 64
    return (b"\xdc\x00\x3c" + (b"\xdc\x00\x40" + inner * 64) * 60)[:MAX_INBOUND_FRAME_BYTES]


#: #2509 security review: at-cap shapes that reserved 2 GiB or cost 160 ms per frame before the
#: container caps and the value budget.
HOSTILE: Final[dict[str, bytes]] = {
    "1024-nested-array32-claiming-262144": _at_cap(b"\xdd\x00\x04\x00\x00" * 1024),
    "1024-nested-array16-claiming-64": _at_cap(b"\xdc\x00\x40" * 1024),
    "1100-nested-fixarray": _at_cap(b"\x9f" * 1100),
    "array32-of-262139-empty-maps": _at_cap(b"\xdd" + (262_139).to_bytes(4, "big")),
    "tree-of-empty-maps": _tree(b"\x80"),
    "tree-of-empty-arrays": _tree(b"\x90"),
    "tree-of-nils": _tree(b"\xc0"),
}


@pytest.mark.parametrize("data", HOSTILE.values(), ids=HOSTILE.keys())
def test_msgpack_hostile_at_cap_frame_is_refused_within_the_allocation_bound(data: bytes) -> None:
    tracemalloc.start()
    try:
        with pytest.raises(MsgpackFrameError):
            decode_client_frame(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak <= MAX_PEAK_BYTES


@pytest.mark.perf
@pytest.mark.parametrize("data", HOSTILE.values(), ids=HOSTILE.keys())
def test_msgpack_hostile_at_cap_frame_blocks_the_loop_far_below_c_2_17(data: bytes) -> None:
    """C-2.17: no more than 50 ms on the event loop; these take about 2 ms at most."""
    started = time.perf_counter()
    with pytest.raises(MsgpackFrameError):
        decode_client_frame(data)
    assert time.perf_counter() - started < 0.05
