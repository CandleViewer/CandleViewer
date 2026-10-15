"""SR-185: the `cv.v1.msgpack` client decoder is bounded and fails only as `frame_malformed`."""

from __future__ import annotations

import json
import time
import tracemalloc
import uuid
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
    _require_c_unpacker,
    decode_client_frame,
)
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_TOPICS_PER_SUB
from candleviewer.ws.topics import FAMILIES, UNIVERSAL

REPO = Path(__file__).resolve().parents[5]
#: The worst `HOSTILE` shape peaks at about 4.8 MiB (open map levels holding short strings):
#: the open levels' pre-sized slots and their scalars, which the 256 KiB input bounds, plus the
#: budgeted values. 8 MiB leaves headroom; the JSON path's worst at the cap is about 6 MiB.
MAX_PEAK_BYTES: Final = 8 << 20
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
    "view",
    [memoryview(b"\x90"), memoryview(bytes(16)).cast("B", shape=[2, 8])],
    ids=["memoryview", "2-d-memoryview"],
)
def test_msgpack_memoryview_is_refused_because_its_len_is_not_its_size(view: memoryview) -> None:
    with pytest.raises(MsgpackFrameError, match="binary"):
        decode_client_frame(view)  # type: ignore[arg-type]  # ASGI hands the gateway bytes


def test_msgpack_fallback_unpacker_is_refused_at_import() -> None:
    def fallback(packed: bytes) -> Any:
        return None

    fallback.__module__ = "msgpack.fallback"
    _require_c_unpacker(msgpack.unpackb)  # the installed one is the C extension
    with pytest.raises(ImportError, match="C extension"):
        _require_c_unpacker(fallback)


def test_msgpack_container_cap_covers_every_list_the_server_accepts() -> None:
    """#2509 review: the cap must never turn a valid JSON-path frame into `frame_malformed`."""
    options = [*UNIVERSAL.values(), *(o for f in FAMILIES.values() for o in f.options.values())]
    limits = [o.max_items for o in options if o.max_items is not None]
    assert max([*limits, MAX_TOPICS_PER_SUB]) <= MAX_MSGPACK_CONTAINER_LEN


@pytest.mark.parametrize(
    "build",
    [lambda n: [None] * n, lambda n: {str(i): None for i in range(n)}],
    ids=["array", "map"],
)
def test_msgpack_container_length_cap_exact_accepted_and_plus_one_rejected(build: Any) -> None:
    assert decode_client_frame(_pack(build(MAX_MSGPACK_CONTAINER_LEN)))
    with pytest.raises(MsgpackFrameError) as exc:
        decode_client_frame(_pack(build(MAX_MSGPACK_CONTAINER_LEN + 1)))
    assert "exceeds max_" in str(exc.value.__cause__)  # the unpacker refused the header


def _budget_frame(extra: int) -> bytes:
    """Charged exactly `MAX_MSGPACK_VALUES` + `extra`: [L, R] with L = 126 lists of 127 nils and
    R = 125 nils costs 3 + (1 + 126 + 126 x 128) + 126 = 16 384."""
    return _pack([[[None] * 127] * 126, [None] * (125 + extra)])


def test_msgpack_value_budget_exact_accepted_and_plus_one_rejected() -> None:
    assert MAX_MSGPACK_VALUES == 16_384  # _budget_frame is built for this budget
    decode_client_frame(_budget_frame(0))
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_budget_frame(1))


def test_msgpack_map_entries_count_twice_against_the_budget() -> None:
    entries = {str(i): None for i in range(MAX_MSGPACK_CONTAINER_LEN)}  # 1 + 256 each
    with pytest.raises(MsgpackFrameError, match="values"):  # 2 + 65 + 64 x 257 = 16 515
        decode_client_frame(_pack([[entries] * 64]))  # (8 323 if an entry counted once)


def test_msgpack_duplicate_map_keys_are_charged_as_read() -> None:
    """128 pairs of one key decode to one entry, and still cost 1 + 256: 65 + 64 x 257."""
    duplicates = b"\xde\x00\x80" + b"\xa0\xc0" * 128  # {"": None} written 128 times
    assert decode_client_frame(duplicates) == {"": None}
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(b"\xdc\x00\x40" + duplicates * 64)


def test_msgpack_every_container_costs_one_even_when_empty() -> None:
    with pytest.raises(MsgpackFrameError, match="values"):  # 65 + 64 x 129 + 8 192 = 16 513
        decode_client_frame(_pack([[[]] * 128] * 64))  # (8 256 with empty containers free)


def test_msgpack_largest_schema_valid_sub_fits_the_budget() -> None:
    """50 topics, each with every bounded option list full (`topics.py`)."""
    ids = [str(uuid.UUID(int=i)) for i in range(100)]
    opts = {
        "rule_ids": ids,
        "exchange_account_ids": ids[:25],
        "symbols": [f"S{j}" for j in range(40)],
        "metrics": [f"m{j}" for j in range(12)],
        "status": [f"s{j}" for j in range(16)],
        "throttle_ms": 100,
        "coalesce": True,
    }
    topics = [{"ch": f"rules.S{i}", "opts": opts} for i in range(MAX_TOPICS_PER_SUB)]
    frame = {"t": "sub", "id": "s", "p": {"topics": topics}}
    assert decode_client_frame(_pack(frame)) == frame


def _at_cap(prefix: bytes, filler: bytes = b"\xc0") -> bytes:
    return (prefix + filler * MAX_INBOUND_FRAME_BYTES)[:MAX_INBOUND_FRAME_BYTES]


def _tree(leaf: bytes) -> bytes:
    """A 128-ary tree, three levels deep, of `leaf`, cut at the inbound cap."""
    inner = b"\xdc\x00\x80" + leaf * 128
    return _at_cap(b"\xdc\x00\x80" + (b"\xdc\x00\x80" + inner * 128) * 128, b"")


def _open_levels(child: bytes) -> bytes:
    """Array levels of 127 `child` values each, the 128th the next level: never completed."""
    return _at_cap((b"\xdc\x00\x80" + child * 127) * 2_000, b"")


def _open_map_levels(value: bytes) -> bytes:
    """Map levels of 127 distinct keys to `value`, the 128th key's value the next level."""
    keys = [b"\xa2" + bytes([0x41 + i // 32, 0x41 + i % 32]) for i in range(128)]
    level = b"\xde\x00\x80" + b"".join(k + value for k in keys[:127]) + keys[127]
    return _at_cap(level * 2_000, b"")


def _repeated_keys() -> bytes:
    """31 x 64 x 64 duplicate-key entries `"": {}`: about 129 000 maps before keys collapse."""
    inner = b"\xde\x00\x40" + b"\xa0\x80" * 64
    return _at_cap(b"\xdc\x00\x1f" + (b"\xde\x00\x40" + (b"\xa0" + inner) * 64) * 31, b"")


#: #2509 security reviews: at-cap shapes that reserved 2 GiB, cost 160 ms per frame, or slipped
#: past the round-1 budget (open levels, empty containers, duplicate keys).
HOSTILE: Final[dict[str, bytes]] = {
    "1024-nested-array32-claiming-262144": _at_cap(b"\xdd\x00\x04\x00\x00" * 1024),
    "1024-nested-array16-claiming-128": _at_cap(b"\xdc\x00\x80" * 1024),
    "1100-nested-fixarray": _at_cap(b"\x9f" * 1100),
    "array32-of-262139-empty-maps": _at_cap(b"\xdd" + (262_139).to_bytes(4, "big")),
    "tree-of-empty-maps": _tree(b"\x80"),
    "tree-of-empty-arrays": _tree(b"\x90"),
    "tree-of-nils": _tree(b"\xc0"),
    "open-levels-of-empty-maps": _open_levels(b"\x80"),
    "open-levels-of-short-strings": _open_levels(b"\xa2ab"),
    "open-levels-of-uint16": _open_levels(b"\xcd\x12\x34"),
    "open-map-levels-of-empty-maps": _open_map_levels(b"\x80"),
    "open-map-levels-of-short-strings": _open_map_levels(b"\xa2ab"),
    "duplicate-key-maps": _repeated_keys(),
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
    """C-2.17: no more than 50 ms on the event loop; the worst of these takes about 7 ms."""
    started = time.perf_counter()
    with pytest.raises(MsgpackFrameError):
        decode_client_frame(data)
    assert time.perf_counter() - started < 0.05
