"""#4924: the MessagePack decoder checks each container as the unpacker completes it, in its value
budget's hooks, instead of walking the decoded value afterwards. It must accept and refuse exactly
the frames the walk did: the walk is kept here, verbatim, as the reference, and both run over
generated values (every type msgpack packs, non-finite floats, binary strings and binary-string
keys, extension types, nesting on both sides of `MAX_MSGPACK_DEPTH`) and over hand-made frames a
`dict` cannot pack (a repeated key)."""

from __future__ import annotations

import math
from typing import Any

import msgpack
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws.codec import (
    MAX_MSGPACK_ARRAY_LEN,
    MAX_MSGPACK_DEPTH,
    MAX_MSGPACK_MAP_LEN,
    MAX_MSGPACK_VALUES,
    MsgpackFrameError,
    decode_client_frame,
)

_SCALARS = (str, int, type(None))  # a bool is an int


class _OldBudget:
    """The value budget as it was, without checks."""

    def __init__(self, limit: int) -> None:
        self.left = limit

    def _charge(self, cost: int) -> None:
        self.left -= cost
        if self.left < 0:
            raise MsgpackFrameError("values")

    def array(self, items: list[Any]) -> list[Any]:
        self._charge(1 + len(items))
        return items

    def map(self, pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
        self._charge(1 + 2 * len(pairs))
        return dict(pairs)


def _old_check(value: Any) -> None:
    """The walk the decoder ran on the decoded value before #4924, verbatim."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict | list):
            if level > MAX_MSGPACK_DEPTH:
                raise MsgpackFrameError("depth")
            if isinstance(node, dict):
                if not all(isinstance(key, str) for key in node):
                    raise MsgpackFrameError("keys")
                stack.extend((item, level + 1) for item in node.values())
            else:
                stack.extend((item, level + 1) for item in node)
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise MsgpackFrameError("non-finite")
        elif not isinstance(node, _SCALARS):
            raise MsgpackFrameError("type")


def _refuse_ext(code: int, data: bytes) -> Any:
    raise MsgpackFrameError("ext")


def _old_decode(raw: bytes) -> Any:
    budget = _OldBudget(MAX_MSGPACK_VALUES)
    try:
        value = msgpack.unpackb(
            raw,
            raw=False,
            strict_map_key=True,
            ext_hook=_refuse_ext,
            max_ext_len=0,
            max_array_len=MAX_MSGPACK_ARRAY_LEN,
            max_map_len=MAX_MSGPACK_MAP_LEN,
            list_hook=budget.array,
            object_pairs_hook=budget.map,
        )
    except MsgpackFrameError:
        raise
    except (ValueError, msgpack.ExtraData) as exc:
        raise MsgpackFrameError("undecodable") from exc
    _old_check(value)
    return value


def _outcome(decode: Any, raw: bytes) -> tuple[str, str]:
    try:
        return ("accepted", repr(decode(raw)))
    except MsgpackFrameError:
        return ("refused", "")


_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers(-(2**63), 2**64 - 1)
    | st.floats()  # NaN and the infinities included
    | st.text(max_size=4)
    | st.binary(max_size=4)
    | st.builds(msgpack.ExtType, st.integers(0, 127), st.binary(max_size=2))
)
_VALUES = st.recursive(
    _LEAVES,
    lambda inner: (
        st.lists(inner, max_size=5)
        | st.dictionaries(st.text(max_size=3) | st.binary(max_size=2), inner, max_size=4)
    ),
    max_leaves=40,
)


def _nest(depth: int, leaf: Any, *, maps: bool) -> Any:
    value = leaf
    for n in range(depth):
        value = {"k": value} if maps and n % 2 else [value]
    return value


@settings(max_examples=600, deadline=None, derandomize=True)
@given(value=_VALUES)
def test_msgpack_validation_accepts_and_refuses_what_the_old_walk_did(value: Any) -> None:
    raw: bytes = msgpack.packb(value, use_bin_type=True)
    assert _outcome(decode_client_frame, raw) == _outcome(_old_decode, raw)


@settings(max_examples=200, deadline=None, derandomize=True)
@given(
    depth=st.integers(MAX_MSGPACK_DEPTH - 3, MAX_MSGPACK_DEPTH + 3),
    leaf=_LEAVES,
    maps=st.booleans(),
    wide=st.integers(0, 3),
)
def test_msgpack_validation_nesting_at_the_bound_matches_the_old_walk(
    depth: int, leaf: Any, maps: bool, wide: int
) -> None:
    value = [_nest(depth, leaf, maps=maps), *([None] * wide), _nest(2, 1.5, maps=not maps)]
    raw: bytes = msgpack.packb(value, use_bin_type=True)
    assert _outcome(decode_client_frame, raw) == _outcome(_old_decode, raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"\x82\xa1k\xc4\x01x\xa1k\x01", id="repeated-key-binary-then-int"),
        pytest.param(b"\x82\xa1k\x01\xa1k\xc4\x01x", id="repeated-key-int-then-binary"),
        pytest.param(
            b"\x82\xa1k\xcb\x7f\xf8\x00\x00\x00\x00\x00\x00\xa1k\x01", id="nan-overwritten"
        ),
        pytest.param(b"\x82\xc4\x01k\x01\xa1k\x02", id="binary-key"),
        pytest.param(b"\xcb\x7f\xf0\x00\x00\x00\x00\x00\x00", id="top-level-infinity"),
        pytest.param(b"\xc4\x02ab", id="top-level-binary"),
        pytest.param(b"\xd4\x01\x00", id="top-level-ext"),
    ],
)
def test_msgpack_validation_hand_made_frames_match_the_old_walk(raw: bytes) -> None:
    assert _outcome(decode_client_frame, raw) == _outcome(_old_decode, raw)
