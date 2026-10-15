"""SR-185: the `cv.v1.msgpack` client decoder is bounded and fails only as `frame_malformed`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import msgpack
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.ws.codec import MAX_MSGPACK_DEPTH, MsgpackFrameError, decode_client_frame
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

REPO = Path(__file__).resolve().parents[5]
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
