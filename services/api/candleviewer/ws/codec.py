"""The `cv.v1.msgpack` codec (`23-ws-protocol.md` §2.2, §3.2; SR-185): client frames decoded under
bounds, server frames encoded.

A client frame reaches this decoder only at or below the 256 KiB inbound cap (SR-040), and the
decoder checks the cap again first. The other limits hold *while* msgpack's C unpacker runs
(the pure-Python fallback is refused at import: it would break the C-2.17 time bound):
- its nesting stack stops at 1 024 levels;
- no array may claim more than `MAX_MSGPACK_ARRAY_LEN` entries and no map more than
  `MAX_MSGPACK_MAP_LEN`, so a header never reserves room for more (msgpack pre-sizes a
  container to the length its header claims);
- ext types are refused at their header: no ext may carry data (`max_ext_len=0`), so the unpacker
  builds none, the timestamp (type -1) included; an empty ext of another type reaches
  `_refuse_ext`, and an empty timestamp is malformed (#415, E17-R-06);
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
import functools
import math
import operator
from collections.abc import Mapping
from itertools import compress, repeat
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
#: cap. A longer list is malformed here, where JSON would answer per option or ignore it: an
#: option list longer than 128, or a `hello` / `auth` array the schema leaves unbounded. No
#: conforming client sends one. A `sub` or `unsub` naming more than 50 topics is refused whole on
#: both paths (`too_many_topics` and `invalid_options`, `field: topics`; §5.2, §5.3); past 128
#: this decoder refuses it first.
MAX_MSGPACK_ARRAY_LEN: Final = 128
#: SR-185: entries one map may claim: the widest client object in `ws-schema.json`, a topic's
#: `opts` (32 properties, `additionalProperties: false`). The server accepts fewer keys in any
#: one `opts` (`topics.py`); a test keeps both under this cap. A wider map is malformed here,
#: although the JSON path ignores extra keys in an envelope or a `hello` / `auth` payload; no
#: schema-conforming client sends one.
MAX_MSGPACK_MAP_LEN: Final = 32
#: SR-185: values charged per frame (see `_Budget`). A `sub` of 50 `rules` topics with every
#: list that family accepts full costs about 7 500. #4924: also the JSON value bound, over-counted
#: on the text before decode (`limits.json_values_over_count`): one number for both encodings.
MAX_MSGPACK_VALUES: Final = 16_384
#: SR-185: the value budget the gateway passes until the first `auth_ok`. The widest conforming
#: frames there, a `hello` and an `auth` with each enum list naming every member once, are charged
#: 36 and 16: this is twice the larger.
MAX_PREAUTH_MSGPACK_VALUES: Final = 72

# `TypeAlias`, not a PEP 695 `type` statement: Semgrep cannot parse that, and it must scan this
# security control whole (#2509 round 6).
JsonValue: TypeAlias = (  # noqa: UP040 - see the comment above (#2483)
    "dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None"
)


class MsgpackFrameError(ValueError):
    """A client frame that is not a valid `cv.v1` MessagePack envelope (`frame_malformed`)."""


#: What a decoded value may be: what JSON carries (a bool is its own type here; `bytes` from a
#: binary string is not among them).
_ALLOWED_TYPES: Final[frozenset[type]] = frozenset({dict, list, str, int, float, bool, type(None)})
_CONTAINER_TYPES: Final[frozenset[type]] = frozenset({dict, list})
_IS_FLOAT: Final = functools.partial(operator.is_, float)


class _Budget:
    """Charges each container as the unpacker completes it: 1 for the container, 1 per array
    element, 2 per map entry as read (so duplicate keys still cost). Ends the decode once spent.

    It also checks each container as it completes, so the decoded value needs no second walk
    (#4924): every element and map value is of a type JSON carries, every float is finite, every
    map key a string, and no container nests deeper than `MAX_MSGPACK_DEPTH`. Each check runs over
    a container's items with C iterators (`map`, `set`, `compress`), not a Python loop per value.
    A container's height (1, plus its deepest child's) is kept by `id`: the children are alive in
    their parent, so no id is reused while the decode runs."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.left = limit
        self._heights: dict[int, int] = {}

    def _charge(self, cost: int) -> None:
        self.left -= cost
        if self.left < 0:
            raise MsgpackFrameError(f"more than {self.limit} values")

    def _checked(self, container: list[Any] | dict[Any, Any], items: Any) -> None:
        """Check `items`, the elements or map values of `container`, and record its height."""
        items = items if isinstance(items, list) else list(items)
        kinds = set(map(type, items))
        if not kinds <= _ALLOWED_TYPES:
            name = min(t.__name__ for t in kinds - _ALLOWED_TYPES)
            raise MsgpackFrameError(f"{name} is not allowed")
        floats = compress(items, map(_IS_FLOAT, map(type, items))) if float in kinds else ()
        if not all(map(math.isfinite, floats)):
            raise MsgpackFrameError("non-finite number")
        height = 1
        if kinds & _CONTAINER_TYPES:
            height += max(map(self._heights.get, map(id, items), repeat(0, len(items))))
            if height > MAX_MSGPACK_DEPTH:
                raise MsgpackFrameError(f"nesting deeper than {MAX_MSGPACK_DEPTH}")
        self._heights[id(container)] = height

    def array(self, items: list[Any]) -> list[Any]:
        self._charge(1 + len(items))
        self._checked(items, items)
        return items

    def map(self, pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
        self._charge(1 + 2 * len(pairs))
        value = dict(pairs)  # a repeated key keeps its last value, which alone is checked
        if not set(map(type, value)) <= {str}:  # e.g. a binary-string key
            raise MsgpackFrameError("map keys must be strings")
        self._checked(value, value.values())
        return value


def decode_client_frame(
    raw: bytes, *, max_values: int = MAX_MSGPACK_VALUES, charged: list[int] | None = None
) -> JsonValue:
    """One client frame's decoded value, or `MsgpackFrameError` (SR-185). `max_values` can only
    lower the value budget: the gateway passes `MAX_PREAUTH_MSGPACK_VALUES` until `auth_ok`. A
    decode that succeeds appends to `charged`, if given, the values it charged (the gateway's
    post-decode refund of the inbound rate, §8.5; #4924)."""
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
            max_ext_len=0,  # E17-R-06: an ext with data is refused at its header, never built
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
    _check_top(value)
    if charged is not None:
        charged.append(budget.limit - budget.left)
    return value


def encode_server_frame(frame: Mapping[str, Any]) -> bytes:
    """One server frame as MessagePack (§3.2); a `b64` payload goes out raw, as `e: "b"`."""
    if frame.get("e") == "b64":
        frame = {**frame, "e": "b", "p": base64.b64decode(frame["p"], validate=True)}
    packed: bytes = msgpack.packb(frame, use_bin_type=True)
    return packed


def _refuse_ext(code: int, data: bytes) -> NoReturn:
    raise MsgpackFrameError(f"ext type {code} is not allowed")


def _check_top(value: Any) -> None:
    """The checks `_Budget` makes of a container's items, for the frame's own value, which is in
    no container: a container was checked as it completed."""
    if type(value) not in _ALLOWED_TYPES:
        raise MsgpackFrameError(f"{type(value).__name__} is not allowed")
    if type(value) is float and not math.isfinite(value):
        raise MsgpackFrameError("non-finite number")
