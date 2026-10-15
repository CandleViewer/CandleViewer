"""MessagePack decoding of `cv.v1.msgpack` client frames (`23-ws-protocol.md` §2.2, SR-185).

A client frame reaches this decoder only below the 256 KiB inbound cap (SR-040), and the
decoder checks the cap again first. Every other limit holds *while* msgpack's C unpacker runs,
before anything large exists:
- its nesting stack stops at 1 024 levels;
- no array or map may claim more than `MAX_MSGPACK_CONTAINER_LEN` entries, so a header never
  reserves room for more (msgpack pre-sizes an array to the length its header claims);
- ext types are refused on sight;
- a value budget, `MAX_MSGPACK_VALUES`, stops the decode once the frame holds more values than
  any schema-valid client frame can.

The decoded value must then be something a JSON frame could carry: maps with string keys,
arrays, strings, finite numbers, booleans and nil, nested at most `MAX_MSGPACK_DEPTH` deep.
Anything else raises `MsgpackFrameError`:
- input that is not bytes
- timestamps
- binary strings, as values or keys
- NaN and infinities
- truncated input or trailing bytes
- invalid UTF-8

Number ranges are the envelope validators' concern, as on the JSON path. The gateway counts a
`MsgpackFrameError` as `frame_malformed`, as it does for a malformed JSON frame (SR-184).
"""

from __future__ import annotations

import math
from typing import Any, Final, NoReturn

import msgpack

from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_JSON_DEPTH

#: SR-185: the nesting cap SR-184 sets for JSON client frames.
MAX_MSGPACK_DEPTH: Final = MAX_JSON_DEPTH
#: SR-185: entries one array or map may claim. The longest list a client frame carries is a
#: `sub`'s 50 topics (`ws-schema.json`); a longer one is malformed here, not `too_many_topics`.
MAX_MSGPACK_CONTAINER_LEN: Final = 64
#: SR-185: values in one frame (array elements, map keys and map values). A schema-maximal
#: `sub` (50 topics, every bounded option list full) holds about 6 000.
MAX_MSGPACK_VALUES: Final = 16_384
_SCALARS: Final = (str, int, type(None))  # a bool is an int

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


class MsgpackFrameError(ValueError):
    """A client frame that is not a valid `cv.v1` MessagePack envelope (`frame_malformed`)."""


class _Budget:
    """Counts values as the unpacker completes each container; ends the decode past the budget."""

    def __init__(self) -> None:
        self.left = MAX_MSGPACK_VALUES

    def spend[C: (dict[Any, Any], list[Any])](self, container: C) -> C:
        self.left -= len(container) * (2 if isinstance(container, dict) else 1)
        if self.left < 0:
            raise MsgpackFrameError(f"more than {MAX_MSGPACK_VALUES} values")
        return container


def decode_client_frame(raw: bytes) -> JsonValue:
    """One client frame's decoded value, or `MsgpackFrameError` (SR-185)."""
    if not isinstance(raw, bytes | bytearray | memoryview):
        raise MsgpackFrameError("a msgpack frame is binary")
    if len(raw) > MAX_INBOUND_FRAME_BYTES:
        raise MsgpackFrameError("frame exceeds the inbound cap")
    budget = _Budget()
    try:
        value: JsonValue = msgpack.unpackb(
            raw,
            raw=False,
            strict_map_key=True,
            ext_hook=_refuse_ext,
            max_array_len=MAX_MSGPACK_CONTAINER_LEN,
            max_map_len=MAX_MSGPACK_CONTAINER_LEN,
            list_hook=budget.spend,
            object_hook=budget.spend,
        )
    except MsgpackFrameError:
        raise
    except ValueError as exc:  # every unpackb failure: format, stack, extra data, UTF-8, lengths
        raise MsgpackFrameError(f"undecodable frame: {type(exc).__name__}") from exc
    _check(value)
    return value


def _refuse_ext(code: int, data: bytes) -> NoReturn:
    raise MsgpackFrameError(f"ext type {code} is not allowed")


def _check(value: Any) -> None:
    """Refuse what JSON could not carry and nesting deeper than the cap, without recursing.
    The value budget already bounds the walk."""
    stack: list[tuple[Any, int]] = [(value, 1)]  # (node, its level if it is a container)
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict | list):
            if level > MAX_MSGPACK_DEPTH:
                raise MsgpackFrameError(f"nesting deeper than {MAX_MSGPACK_DEPTH}")
            if isinstance(node, dict):
                if not all(isinstance(key, str) for key in node):  # e.g. a binary-string key
                    raise MsgpackFrameError("map keys must be strings")
                stack.extend((item, level + 1) for item in node.values())
            else:
                stack.extend((item, level + 1) for item in node)
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise MsgpackFrameError("non-finite number")
        elif not isinstance(node, _SCALARS):
            raise MsgpackFrameError(f"{type(node).__name__} is not allowed")
