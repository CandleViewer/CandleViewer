"""SR-185: the `cv.v1.msgpack` client decoder is bounded and fails only as `frame_malformed`."""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import time
import traceback
import tracemalloc
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import msgpack
import pytest
from hypothesis import given
from hypothesis import strategies as st

import candleviewer.ws.codec as codec
from candleviewer.ws.codec import (
    MAX_MSGPACK_ARRAY_LEN,
    MAX_MSGPACK_DEPTH,
    MAX_MSGPACK_MAP_LEN,
    MAX_MSGPACK_VALUES,
    MsgpackFrameError,
    _require_c_unpacker,
    decode_client_frame,
)
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_TOPICS_PER_SUB
from candleviewer.ws.topics import FAMILIES, UNIVERSAL
from tests.unit.ws._msgpack_bounds import MAX_PEAK_BYTES, peak_bound, smallest_resize_bytes

REPO = Path(__file__).resolve().parents[5]
#: A msgpack timestamp (ext type -1), which the unpacker decodes without calling `ext_hook`.
TIMESTAMP: Final = b"\xd6\xff\x00\x00\x00\x01"
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


_MARK: Final = "c4f9e2a1b7d3"  # only the fake token below carries it
_AUTH: Final = {"t": "auth", "id": "a", "p": {"access_token": f"good-{_MARK}"}}
#: An `auth` whose token is a str of bytes that are not UTF-8 (`use_bin_type=False` packs bytes as
#: a str): the `UnicodeDecodeError`'s `object` is those bytes.
_NOT_UTF8: Final[bytes] = msgpack.packb(
    {**_AUTH, "p": {"access_token": b"\xff" + _MARK.encode()}}, use_bin_type=False
)


@pytest.mark.parametrize(
    ("data", "error"),
    [(_pack(_AUTH) + b"\xc0", "ExtraData"), (_NOT_UTF8, "UnicodeDecodeError")],
    ids=["trailing-bytes", "invalid-utf8"],
)
def test_msgpack_error_never_chains_the_frame_content(data: bytes, error: str) -> None:
    """#2509 round 6 (C-12.6): `ExtraData` holds the whole decoded frame, an `auth` frame's token
    included, and a `UnicodeDecodeError` the string's bytes. Neither may ride the chain into an
    `exc_info` log: what a renderer follows ends at the `MsgpackFrameError`."""
    with pytest.raises(MsgpackFrameError, match=f"^undecodable frame: {error}$") as exc:
        decode_client_frame(data)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    assert _MARK not in "".join(traceback.format_exception(exc.value)) + repr(exc.value.args)


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
    # Within the container caps, so the only refusal a test can meet is the one it asserts: a map
    # wider than `MAX_MSGPACK_MAP_LEN` is refused for its width, before any nesting check (#2483).
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(), children, max_size=MAX_MSGPACK_MAP_LEN)
    ),
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


def test_msgpack_codec_refuses_to_import_under_the_pure_python_fallback() -> None:
    """The module-level check itself. With `MSGPACK_PUREPYTHON` set, msgpack loads its fallback,
    which also hands `object_pairs_hook` a generator, so every map would raise a `TypeError`.
    The import must fail first. This runs in a fresh interpreter, so this process is untouched."""
    result = subprocess.run(  # fixed argv: this interpreter and a literal import, no shell
        [sys.executable, "-c", "import candleviewer.ws.codec"],
        cwd=Path(codec.__file__).resolve().parents[2],
        env={**os.environ, "MSGPACK_PUREPYTHON": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "the msgpack C extension is required" in result.stderr


def test_msgpack_array_cap_covers_every_list_the_server_accepts() -> None:
    """#2509 review: the cap must never turn a valid JSON-path frame into `frame_malformed`."""
    options = [*UNIVERSAL.values(), *(o for f in FAMILIES.values() for o in f.options.values())]
    limits = [o.max_items for o in options if o.max_items is not None]
    assert max([*limits, MAX_TOPICS_PER_SUB]) <= MAX_MSGPACK_ARRAY_LEN


_CLIENT_SCHEMAS: Final = ("envelope", "hello", "heartbeat", "auth", "sub", "unsub", "ctl", "resync")


def _client_objects() -> list[tuple[str, dict[str, Any]]]:
    """(property name, object schema) for every object a client frame may carry, `$ref`s into
    `common` resolved. `if`, `then`, `else` and `not` constrain the object they sit in, so they
    are not objects of their own."""
    doc = json.loads((REPO / "docs/plan/ws-schema.json").read_text(encoding="utf-8"))["schemas"]
    defs = doc["cv://ws/v1/common.schema.json"]["$defs"]
    stack: list[tuple[str, Any]] = [
        ("", doc[f"cv://ws/v1/{n}.schema.json"]) for n in _CLIENT_SCHEMAS
    ]
    found: list[tuple[str, dict[str, Any]]] = []
    while stack:
        name, node = stack.pop()
        if isinstance(node, list):
            stack.extend((name, item) for item in node)
        elif isinstance(node, dict):
            ref = str(node.get("$ref", ""))
            if ref.startswith("cv://ws/v1/common.schema.json#/$defs/"):
                stack.append((name, defs[ref.rsplit("/", 1)[1]]))
            if "properties" in node or node.get("type") == "object":
                found.append((name, node))
            stack.extend(node.get("properties", {}).items())
            skip = {"properties", "if", "then", "else", "not"}
            stack.extend((name, v) for k, v in node.items() if k not in skip)
    return found


def test_msgpack_map_cap_covers_every_object_a_client_frame_may_carry() -> None:
    """#2509 review: the widest closed client object in `ws-schema.json` (a topic's `opts`) and
    the widest `opts` the server accepts fit the map cap. The one open object, `opts.params`, is
    an option no family accepts, so the server refuses it at any width."""
    objects = _client_objects()
    closed = [
        len(o.get("properties", {})) for _, o in objects if o.get("additionalProperties") is False
    ]
    assert max(closed) <= MAX_MSGPACK_MAP_LEN
    opened = {name for name, o in objects if o.get("additionalProperties") is not False}
    accepted = {*UNIVERSAL, *(key for f in FAMILIES.values() for key in f.options)}
    assert opened == {"params"} and not opened & accepted
    assert max(len({**UNIVERSAL, **f.options}) for f in FAMILIES.values()) <= MAX_MSGPACK_MAP_LEN


@pytest.mark.parametrize(
    ("build", "cap"),
    [
        (lambda n: [None] * n, MAX_MSGPACK_ARRAY_LEN),
        (lambda n: {str(i): None for i in range(n)}, MAX_MSGPACK_MAP_LEN),
    ],
    ids=["array", "map"],
)
def test_msgpack_container_length_cap_exact_accepted_and_plus_one_rejected(
    build: Any, cap: int
) -> None:
    assert decode_client_frame(_pack(build(cap)))
    with pytest.raises(MsgpackFrameError) as exc:
        decode_client_frame(_pack(build(cap + 1)))
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
    """3 + (129 + 128 x 65) + (122 + 121 x 65) = 16 439, or 8 471 if an entry counted once."""
    entries = {str(i): None for i in range(MAX_MSGPACK_MAP_LEN)}  # 1 + 64 each
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_pack([[entries] * 128, [entries] * 121]))


def test_msgpack_duplicate_map_keys_are_charged_as_read() -> None:
    """32 pairs of one key decode to one entry and still cost 1 + 64. Two arrays of 128 such
    maps cost 3 + 2 x (129 + 128 x 65) = 16 901, or 1 029 if charged after keys collapse."""
    duplicates = b"\xde\x00\x20" + b"\xa0\xc0" * 32  # {"": None} written 32 times
    assert decode_client_frame(duplicates) == {"": None}
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(b"\x92" + (b"\xdc\x00\x80" + duplicates * 128) * 2)


def test_msgpack_every_container_costs_one_even_when_empty() -> None:
    with pytest.raises(MsgpackFrameError, match="values"):  # 65 + 64 x 129 + 8 192 = 16 513
        decode_client_frame(_pack([[[]] * 128] * 64))  # (8 256 with empty containers free)


def test_msgpack_sub_with_every_option_list_full_fits_the_budget() -> None:
    """An over-approximation of the largest valid `sub`: 50 topics whose `opts` hold every
    bounded list any family accepts, each full (`topics.py`). It costs 10 961. No family accepts
    all of these lists; the costliest one that a family does accept, `rules`, costs 7 511."""
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


def _open_map_levels(value: bytes, distinct: bool = True) -> bytes:
    """Map levels of 31 keys to `value` (distinct, or all `""`), the 32nd key's value the next
    level."""
    keys = [
        b"\xa2" + bytes([0x41 + i // 32, 0x41 + i % 32]) if distinct else b"\xa0"
        for i in range(MAX_MSGPACK_MAP_LEN)
    ]
    level = b"\xde\x00\x20" + b"".join(k + value for k in keys[:-1]) + keys[-1]
    return _at_cap(level * 2_000, b"")


def _unique_keys(salt: int) -> Iterator[bytes]:
    """4-character map keys, none repeated within a frame (one salt per frame)."""
    for tail in itertools.product(range(0x21, 0x7F), repeat=3):
        yield b"\xa4" + bytes([0x21 + salt % 94, *tail])


def _unique_key_levels(salt: int, *, maps: bool) -> bytes:
    """Open levels whose keys are new to the process: map levels of 31 keys, or array levels of
    five one-entry maps and 122 ints."""
    keys, out = _unique_keys(salt), bytearray()
    while len(out) < MAX_INBOUND_FRAME_BYTES:
        if maps:
            out += b"\xde\x00\x20" + b"".join(next(keys) + b"\xe0" for _ in range(31)) + next(keys)
        else:
            out += b"\xdc\x00\x80" + b"".join(b"\x81" + next(keys) + b"\xe0" for _ in range(5))
            out += b"\xe0" * 122
    return bytes(out[:MAX_INBOUND_FRAME_BYTES])


def _repeated_keys() -> bytes:
    """31 x 32 x 32 duplicate-key entries `"": {}`: about 31 700 maps before keys collapse."""
    inner = b"\xde\x00\x20" + b"\xa0\x80" * 32
    return _at_cap(b"\xdc\x00\x1f" + (b"\xde\x00\x20" + (b"\xa0" + inner) * 32) * 31, b"")


#: #2509 security reviews: at-cap shapes that reserved 2 GiB, cost 160 ms per frame, slipped
#: past the round-1 budget (open levels, empty containers, duplicate keys), or peaked at
#: 12 MiB under the round-3 map cap (open map levels of uncached ints).
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
    "open-levels-of-negative-fixints": _open_levels(b"\xe0"),
    "open-levels-of-timestamps": _open_levels(TIMESTAMP),
    "open-levels-of-small-maps-and-ints": _at_cap(
        (b"\xdc\x00\x80" + b"\x81\xa0\xe0" * 5 + b"\xe0" * 122) * 2_000, b""
    ),
    "open-map-levels-of-empty-maps": _open_map_levels(b"\x80"),
    "open-map-levels-of-short-strings": _open_map_levels(b"\xa2ab"),
    "open-map-levels-of-negative-fixints": _open_map_levels(b"\xe0", distinct=False),
    "open-map-levels-of-nils": _open_map_levels(b"\xc0", distinct=False),
    "open-map-levels-of-timestamps": _open_map_levels(TIMESTAMP),
    "open-map-levels-of-unique-keys": _unique_key_levels(0, maps=True),
    "open-levels-of-unique-key-maps-and-ints": _unique_key_levels(1, maps=False),
    # Round 3's 12 MiB shape: 128-wide levels of `"": -32`, refused now at the first header.
    "128-wide-open-map-levels": _at_cap(
        (b"\xde\x00\x80" + b"\xa0\xe0" * 127 + b"\xa0") * 2_000, b""
    ),
    "duplicate-key-maps": _repeated_keys(),
}


#: The shapes whose keys are new to the process (`_unique_key_levels`): their decode can be the
#: one that resizes the interned-string table, so they keep that term in their bound.
_SALTED: Final = frozenset(
    {"open-map-levels-of-unique-keys", "open-levels-of-unique-key-maps-and-ints"}
)


def _peak(data: bytes) -> int:
    """Peak traced allocation of one refused decode."""
    tracemalloc.start()
    try:
        with pytest.raises(MsgpackFrameError):
            decode_client_frame(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


@pytest.mark.parametrize("name", HOSTILE)
def test_msgpack_hostile_at_cap_frame_is_refused_within_the_allocation_bound(name: str) -> None:
    """#2509 round 6: the per-frame term alone for every shape but the two salted ones. A decode
    of keys the process already holds resizes the interned table at most every other time, so the
    smaller of two peaks is the frame's own."""
    if name in _SALTED:
        assert _peak(HOSTILE[name]) <= peak_bound()
    else:
        assert min(_peak(HOSTILE[name]), _peak(HOSTILE[name])) <= MAX_PEAK_BYTES


def test_msgpack_frames_of_new_keys_stay_bounded_through_an_interned_table_resize() -> None:
    """#2509 round 4: about 31 000 keys per frame, new to the process. A released key's entry in
    the interned-string table is only reclaimed when the table resizes, so 24 such frames must
    resize it. A resize adds a whole new table to that decode's peak, at least
    `smallest_resize_bytes()`, while same-shape frames otherwise peak alike: half of it is an
    unambiguous sign. Every decode, the resizing ones included, is within the bound."""
    floor = smallest_resize_bytes()
    peaks = []
    for salt in range(2, 26):
        peak = _peak(_unique_key_levels(salt, maps=True))
        assert peak <= peak_bound()
        peaks.append(peak)
    floor = min(floor, smallest_resize_bytes())  # the table may hold fewer strings by now
    assert max(peaks) - min(peaks) >= floor // 2, "no interned-table resize was reached"


@pytest.mark.perf
@pytest.mark.parametrize("data", HOSTILE.values(), ids=HOSTILE.keys())
def test_msgpack_hostile_at_cap_frame_blocks_the_loop_far_below_c_2_17(data: bytes) -> None:
    """C-2.17: no more than 50 ms on the event loop. The worst of these, timestamps in open map
    levels, takes about 10 ms."""
    started = time.perf_counter()
    with pytest.raises(MsgpackFrameError):
        decode_client_frame(data)
    assert time.perf_counter() - started < 0.05
