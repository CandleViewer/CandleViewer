"""The `cv.v1.msgpack` codec (`23-ws-protocol.md` §2.2, §3.2; SR-185): client frames decoded under
bounds, server frames encoded.

A client frame reaches this decoder only at or below the 256 KiB inbound cap (SR-040), and the
decoder checks the cap again first. The other limits hold *while* msgpack's C unpacker runs
(the pure-Python fallback is refused at import: it would break the C-2.17 time bound):
- its nesting stack stops at 1 024 levels;
- no array may claim more than `MAX_MSGPACK_ARRAY_LEN` entries and no map more than
  `MAX_MSGPACK_MAP_LEN`, so a header never reserves room for more (msgpack pre-sizes a
  container to the length its header claims);
- ext types are refused on sight, except the timestamp (type -1), which msgpack decodes itself
  and the check below refuses once the decode completes;
- a value budget, `MAX_MSGPACK_VALUES` (`MAX_PREAUTH_MSGPACK_VALUES` until `auth_ok`), charges
  every completed container: the container, its elements, and each map key and value (before
  duplicate keys collapse). The decode ends once the budget is spent, so the decoded value, and
  the check below, stay small.

Until the first `auth_ok` the gateway hands this decoder only frames of at most 8 KiB.

Live memory during a decode is bounded by the open levels (at most 1 024, each pre-sized to
its cap, plus the scalars and map pairs read into them, which the 256 KiB input bounds) and by
the budget. msgpack also interns every string map key into CPython's process-wide
interned-string table, so a decode can be the one that resizes it: a transient allocation sized
by the whole process, not by the frame, which a JSON frame does not cause. The derivation is in
`tests/unit/ws/_msgpack_bounds.py`, the worst shapes measured in `test_msgpack_decode_bounds.py`.

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
`MsgpackFrameError` as `frame_malformed`, as it does for a malformed JSON frame (SR-184). It never
chains an unpacker error that holds frame content, so an `exc_info` log cannot render that content
(C-12.6): `ExtraData` holds the whole decoded frame (an `auth` frame's token), a
`UnicodeDecodeError` the string's bytes.

A server frame is the envelope the JSON writer would send, in MessagePack. A CVWB payload that the
emitter wrapped for JSON (`e: "b64"`) goes out raw instead, as `e: "b"` with a `bin` `p` (§3.2).
"""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping
from typing import Any, Final, NoReturn, TypeAlias

import msgpack

from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_JSON_DEPTH


def _require_c_unpacker(unpackb: Any) -> None:
    """SR-185's time bound holds for msgpack's C unpacker only: never load the fallback."""
    if getattr(unpackb, "__module__", None) != "msgpack._cmsgpack":  # e.g. MSGPACK_PUREPYTHON
        raise ImportError("SR-185: the msgpack C extension is required, not the fallback")


_require_c_unpacker(msgpack.unpackb)

#: SR-185: the nesting cap SR-184 sets for JSON client frames.
MAX_MSGPACK_DEPTH: Final = MAX_JSON_DEPTH
#: SR-185: entries one array may claim. The longest option list a topic accepts is a `rules`
#: sub's 100 `rule_ids` (`topics.py`), and a test keeps every `topics.py` list limit under this
#: cap. A longer list is malformed here, where JSON would answer per option or per topic: a
#: `sub` naming more than 128 topics, or a `hello` / `auth` array the schema leaves unbounded.
#: No conforming client sends one. An `unsub` naming more than 50 topics is refused whole on both
#: paths (`invalid_options`, `field: topics`, §5.3); past 128 this decoder refuses it first.
MAX_MSGPACK_ARRAY_LEN: Final = 128
#: SR-185: entries one map may claim: the widest client object in `ws-schema.json`, a topic's
#: `opts` (32 properties, `additionalProperties: false`). The server accepts fewer keys in any
#: one `opts` (`topics.py`); a test keeps both under this cap. A wider map is malformed here,
#: although the JSON path ignores extra keys in an envelope or a `hello` / `auth` payload; no
#: schema-conforming client sends one.
MAX_MSGPACK_MAP_LEN: Final = 32
#: SR-185: values charged per frame (see `_Budget`). A `sub` of 50 `rules` topics with every
#: list that family accepts full costs about 7 500.
MAX_MSGPACK_VALUES: Final = 16_384
#: SR-185: the value budget the gateway passes until the first `auth_ok`. The widest conforming
#: frames there, a `hello` and an `auth` with each enum list naming every member once, are charged
#: 36 and 16: this is twice the larger.
MAX_PREAUTH_MSGPACK_VALUES: Final = 72
_SCALARS: Final = (str, int, type(None))  # a bool is an int

# `TypeAlias`, not a PEP 695 `type` statement: Semgrep cannot parse that, and it must scan this
# security control whole (#2509 round 6).
JsonValue: TypeAlias = (  # noqa: UP040 - see the comment above (#2483)
    "dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None"
)


class MsgpackFrameError(ValueError):
    """A client frame that is not a valid `cv.v1` MessagePack envelope (`frame_malformed`)."""


class _Budget:
    """Charges each container as the unpacker completes it: 1 for the container, 1 per array
    element, 2 per map entry as read (so duplicate keys still cost). Ends the decode once spent."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.left = limit

    def _charge(self, cost: int) -> None:
        self.left -= cost
        if self.left < 0:
            raise MsgpackFrameError(f"more than {self.limit} values")

    def array(self, items: list[Any]) -> list[Any]:
        self._charge(1 + len(items))
        return items

    def map(self, pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
        self._charge(1 + 2 * len(pairs))
        return dict(pairs)


def decode_client_frame(raw: bytes, *, max_values: int = MAX_MSGPACK_VALUES) -> JsonValue:
    """One client frame's decoded value, or `MsgpackFrameError` (SR-185). `max_values` can only
    lower the value budget: the gateway passes `MAX_PREAUTH_MSGPACK_VALUES` until `auth_ok`."""
    if not isinstance(raw, bytes | bytearray):  # a memoryview's len() is not its byte count
        raise MsgpackFrameError("a msgpack frame is binary")
    if len(raw) > MAX_INBOUND_FRAME_BYTES:
        raise MsgpackFrameError("frame exceeds the inbound cap")
    budget = _Budget(min(max_values, MAX_MSGPACK_VALUES))
    try:
        value: JsonValue = msgpack.unpackb(
            raw,
            raw=False,
            strict_map_key=True,
            ext_hook=_refuse_ext,
            max_array_len=MAX_MSGPACK_ARRAY_LEN,
            max_map_len=MAX_MSGPACK_MAP_LEN,
            list_hook=budget.array,
            object_pairs_hook=budget.map,
        )
    except MsgpackFrameError:
        raise
    except msgpack.ExtraData:
        # `ExtraData.unpacked` is the whole decoded frame, an `auth` frame's token included.
        raise MsgpackFrameError("undecodable frame: ExtraData") from None
    except UnicodeDecodeError:
        # Its `object` is the string's bytes: a mangled token is still most of a token.
        raise MsgpackFrameError("undecodable frame: UnicodeDecodeError") from None
    except ValueError as exc:  # format, stack, truncated input, lengths, map keys: no content
        raise MsgpackFrameError(f"undecodable frame: {type(exc).__name__}") from exc
    _check(value)
    return value


def encode_server_frame(frame: Mapping[str, Any]) -> bytes:
    """One server frame as MessagePack (§3.2); a `b64` payload goes out raw, as `e: "b"`."""
    if frame.get("e") == "b64":
        frame = {**frame, "e": "b", "p": base64.b64decode(frame["p"], validate=True)}
    packed: bytes = msgpack.packb(frame, use_bin_type=True)
    return packed


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
