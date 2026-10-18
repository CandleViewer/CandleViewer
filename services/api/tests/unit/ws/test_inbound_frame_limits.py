"""The inbound frame limits before `auth_ok` and before decode (`23-ws-protocol.md` §3.6, §8.5).

Until the first `auth_ok`, the `hello` included, a frame may be at most `MAX_PREAUTH_FRAME_BYTES`:
a larger one gets `bye frame_too_big` and 1009 and is never scanned or decoded (SR-040). There, a
MessagePack frame is decoded under `MAX_PREAUTH_MSGPACK_VALUES` (SR-185), and a `pong` counts
toward the inbound rate like any other frame. A JSON text frame holds at most `MAX_JSON_CONTAINERS`
`[` and `{` characters: more is a `frame_malformed` strike, and the depth scan never walks it
(SR-184). The tests count sizes, what the depth scan and each decoder were handed, the values the
MessagePack decoder charged and the limiter's answers (spies on the modules' own references).
After `auth_ok`, a `pong` past 256 bytes gets `bye protocol_violation` and 1002 (§8.5), and no
parser is handed one that opens with its `t`."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import msgpack
import pytest

import candleviewer.ws.codec as codec
import candleviewer.ws.gateway as gateway
from candleviewer.ws import pacing
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.codec import (
    MAX_MSGPACK_ARRAY_LEN,
    MAX_MSGPACK_VALUES,
    MAX_PREAUTH_MSGPACK_VALUES,
    MsgpackFrameError,
    decode_client_frame,
)
from candleviewer.ws.gateway import _OVERSIZE, _Connection
from candleviewer.ws.lifecycle import RATE_PER_SECOND, InboundRateLimiter
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_CONTAINERS,
    MAX_JSON_DEPTH,
    MAX_PREAUTH_FRAME_BYTES,
    json_depth_exceeds,
)
from candleviewer.ws.topics import FAMILIES, UNIVERSAL
from tests.unit.ws.test_gateway_decode import _conn
from tests.unit.ws.test_lifecycle_socket import (
    BASE_MS,
    JSON,
    MSGPACK,
    _auth,
    _bye_then_close,
    _hello,
    _recv,
    _send,
    _World,
)
from tests.unit.ws.test_msgpack_decode_bounds import _budget_frame
from tests.unit.ws.test_pipeline_invalidation import _connected
from tests.unit.ws.test_pipeline_outbound import _ENCODINGS, _Rig, _Wire
from tests.unit.ws.test_pipeline_quality import _at

REPO = Path(__file__).resolve().parents[5]
_SCHEMAS: Final[dict[str, Any]] = json.loads(
    (REPO / "docs" / "plan" / "ws-schema.json").read_text(encoding="utf-8")
)["schemas"]
#: (subprotocols to offer, the spy name of the decoder that reads that codec)
_CODECS: Final = [
    pytest.param(JSON, "json", id="json"),
    pytest.param(MSGPACK, "msgpack", id="msgpack"),
]
_BOTH: Final = pytest.mark.parametrize("subprotocols", [JSON, MSGPACK], ids=["json", "msgpack"])
_AUTHED: Final = pytest.mark.parametrize(
    "authed", [False, True], ids=["before-auth_ok", "after-auth_ok"]
)
#: The numbers `23-ws-protocol.md` §3.6 states, spelled out: a limit that changes value fails the
#: boundary tests that use them (the E17 threat model §6 asks for a security review of the change).
_STATED_CAP, _STATED_VALUES, _STATED_CONTAINERS = 8192, 72, 1024


def _schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = _SCHEMAS[f"cv://ws/v1/{name}.schema.json"]
    return schema


def _connection(encoding: str, *, authed: bool = False) -> _Connection:
    conn = _conn(encoding)
    if authed:
        conn.user_id = uuid.uuid4()  # what the first `auth_ok` sets
    return conn


def _decode(conn: _Connection, frame: str | bytes, cap: int = MAX_INBOUND_FRAME_BYTES) -> Any:
    kind = "bytes" if isinstance(frame, bytes) else "text"
    return conn.decode({"type": "websocket.receive", kind: frame}, cap)


def _send_raw(ws: Any, frame: str | bytes) -> None:
    if isinstance(frame, bytes):
        ws.send_bytes(frame)
    else:
        ws.send_text(frame)


def _padded_json(t: str, size: int, key: str = "pad") -> str:
    """A `t` frame of exactly `size` bytes of JSON text whose `p[key]` is filler."""
    prefix, suffix = f'{{"t":"{t}","id":"p","p":{{"{key}":"', '"}}'
    text = prefix + "x" * (size - len(prefix) - len(suffix)) + suffix
    assert len(text) == size
    return text


def _padded_msgpack(t: str, size: int, key: str = "pad") -> bytes:
    """The same frame in MessagePack. The filler's string header grows with it (1, 3 or 5 bytes),
    so the filler starts as long as `size` allows with an empty one's header and shrinks to fit."""
    head: dict[str, Any] = {"t": t, "id": "p", "p": {key: ""}}
    n = size - len(msgpack.packb(head))
    packed: bytes = msgpack.packb({**head, "p": {key: "x" * n}})
    while len(packed) > size:
        n -= 1
        packed = msgpack.packb({**head, "p": {key: "x" * n}})
    assert len(packed) == size
    return packed


def _padded(subprotocols: list[str], t: str, size: int, key: str = "pad") -> str | bytes:
    if subprotocols == MSGPACK:
        return _padded_msgpack(t, size, key)
    return _padded_json(t, size, key)


def _containers(n: int) -> str:
    """A JSON envelope with exactly `n` `[` and `{` characters, nested three levels deep."""
    return '{"t":"ping","id":"p","p":{"a":[' + ",".join(["[]"] * (n - 3)) + "]}}"


class _Handed:
    """What `decode` handed the depth scan (`scanned`) and the JSON and MessagePack decoders
    (`decoded`, each with the decoder's name): the `len()` of every argument."""

    def __init__(self) -> None:
        self.scanned: list[int] = []
        self.decoded: list[tuple[str, int]] = []

    def clear(self) -> None:
        self.scanned.clear()
        self.decoded.clear()

    @property
    def nothing(self) -> bool:
        return not self.scanned and not self.decoded

    @property
    def longest(self) -> int:
        return max([*self.scanned, *(n for _, n in self.decoded)], default=0)


@pytest.fixture
def handed(monkeypatch: pytest.MonkeyPatch) -> _Handed:
    """Spies on the gateway module's own references to the depth scan, the JSON parser and the
    MessagePack decoder."""
    seen = _Handed()
    loads = json.loads

    def spy_scan(text: str, limit: int) -> bool:
        seen.scanned.append(len(text))
        return json_depth_exceeds(text, limit)

    def spy_loads(raw: str) -> Any:
        seen.decoded.append(("json", len(raw)))
        return loads(raw)

    def spy_unpack(raw: bytes, **budget: int) -> Any:
        seen.decoded.append(("msgpack", len(raw)))
        return decode_client_frame(raw, **budget)

    monkeypatch.setattr(gateway, "json", SimpleNamespace(loads=spy_loads, dumps=json.dumps))
    monkeypatch.setattr(gateway, "json_depth_exceeds", spy_scan)
    monkeypatch.setattr(gateway, "decode_client_frame", spy_unpack)
    return seen


@pytest.fixture
def charged(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Each charge the MessagePack decoder's value budget took, in order: one per container it
    completed (`codec._Budget`; the codec module's own reference is replaced)."""
    charges: list[int] = []

    class _Recording(codec._Budget):
        def _charge(self, n: int) -> None:
            charges.append(n)
            super()._charge(n)

    monkeypatch.setattr(codec, "_Budget", _Recording)
    return charges


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Each answer the inbound rate limiter gave (`InboundRateLimiter.allow`), in order; the
    gateway module's own reference is replaced."""
    answers: list[bool] = []

    class _Recording(InboundRateLimiter):
        def allow(self, now: float) -> bool:
            answers.append(ok := super().allow(now))
            return ok

    monkeypatch.setattr(gateway, "InboundRateLimiter", _Recording)
    return answers


# -- `_Connection.decode`: the size cap -----------------------------------------------------------


@pytest.mark.parametrize(("subprotocols", "decoder"), _CODECS)
def test_decode_before_auth_ok_cap_exact_is_decoded_and_one_over_is_refused_unread(
    handed: _Handed, subprotocols: list[str], decoder: str
) -> None:
    conn = _connection(subprotocols[0])
    exact = _padded(subprotocols, "hello", _STATED_CAP, "client")
    assert _decode(conn, exact)["t"] == "hello"
    assert handed.decoded == [(decoder, _STATED_CAP)]
    handed.clear()
    over = _padded(subprotocols, "hello", _STATED_CAP + 1, "client")
    assert _decode(conn, over) is _OVERSIZE
    assert handed.nothing
    assert conn.bye_frame is not None
    assert (conn.bye_frame["p"]["reason"], conn.bye_frame["p"]["code"]) == ("frame_too_big", 1009)


def test_decode_before_auth_ok_cap_counts_encoded_bytes_not_characters() -> None:
    half = MAX_PREAUTH_FRAME_BYTES // 2
    at_cap = '"' + "é" * (half - 1) + '"'  # 2 + 2 x 4 095 = 8 192 bytes, 4 097 characters
    assert len(at_cap.encode()) == MAX_PREAUTH_FRAME_BYTES
    assert _decode(_connection(JSON[0]), at_cap) == at_cap[1:-1]
    over = '"' + "é" * half + '"'  # 8 194 bytes, 4 098 characters
    assert _decode(_connection(JSON[0]), over) is _OVERSIZE


class _Encoded(Exception):
    """Raised when something encodes an `_Unencodable`."""


class _Unencodable(str):
    """A text frame whose `encode` raises: measuring it in bytes would encode it."""

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        raise _Encoded


@_AUTHED
def test_decode_of_a_text_frame_longer_than_the_cap_in_characters_is_refused_unencoded(
    authed: bool,
) -> None:
    """A character is at least one byte, so a text frame with more characters than the cap is over
    it and is refused without being encoded to count its bytes. At the cap in characters it is
    still counted in bytes: one two-byte character puts it over."""
    cap = MAX_INBOUND_FRAME_BYTES if authed else MAX_PREAUTH_FRAME_BYTES
    frame = _Unencodable("x" * (cap + 1))
    assert _decode(_connection(JSON[0], authed=authed), frame) is _OVERSIZE
    at_cap = '"é' + "x" * (cap - 3) + '"'
    assert (len(at_cap), len(at_cap.encode())) == (cap, cap + 1)
    assert _decode(_connection(JSON[0], authed=authed), at_cap) is _OVERSIZE


@pytest.mark.parametrize(("subprotocols", "decoder"), _CODECS)
def test_decode_after_auth_ok_cap_is_the_inbound_cap_not_the_pre_auth_cap(
    handed: _Handed, subprotocols: list[str], decoder: str
) -> None:
    conn = _connection(subprotocols[0], authed=True)
    for size in (MAX_PREAUTH_FRAME_BYTES + 1, MAX_INBOUND_FRAME_BYTES):
        assert _decode(conn, _padded(subprotocols, "ping", size))["t"] == "ping"
    sizes = [(decoder, MAX_PREAUTH_FRAME_BYTES + 1), (decoder, MAX_INBOUND_FRAME_BYTES)]
    assert handed.decoded == sizes
    over = _padded(subprotocols, "ping", MAX_INBOUND_FRAME_BYTES + 1)
    assert _decode(conn, over) is _OVERSIZE


@pytest.mark.parametrize(
    ("make", "decoded"),
    [(bytes, True), (bytearray, True), (memoryview, False)],
    ids=["bytes", "bytearray", "memoryview"],
)
def test_decode_sizes_a_binary_payload_by_its_length_whatever_its_buffer_type(
    make: Callable[[bytes], Any], decoded: bool
) -> None:
    """The size check measures a `bytes`, a `bytearray` and a `memoryview` alike, by length. The
    codec then reads the first two and refuses the last (`[]`); past the cap each is over."""
    conn = _connection(MSGPACK[0])

    def decode(size: int) -> Any:
        msg = {"type": "websocket.receive", "bytes": make(_padded_msgpack("ping", size))}
        return conn.decode(msg, MAX_INBOUND_FRAME_BYTES)

    assert bool(decode(_STATED_CAP)) is decoded
    assert decode(_STATED_CAP + 1) is _OVERSIZE


def _cut(unit: str, n: int) -> str:
    """The first `n` characters of `unit` repeated."""
    return (unit * (n // len(unit) + 1))[:n]


_JSON_SHAPES: Final[dict[str, Callable[[int], str]]] = {
    "brackets": lambda n: _cut("[", n),
    "objects": lambda n: _cut('{"a":', n),
    "empty-lists": lambda n: "[" + _cut("[],", n - 1),
    "number-list": lambda n: "[" + _cut("0,", n - 1),
    "escapes": lambda n: '["' + _cut('\\"', n - 2),
    "padded-ping": lambda n: _padded_json("ping", n),
}
_MSGPACK_SHAPES: Final[dict[str, Callable[[int], bytes]]] = {
    "nested-arrays": lambda n: b"\x91" * n,
    "array-headers": lambda n: (b"\xdc\x00\x80" * (n // 3 + 1))[:n],
    "padded-ping": lambda n: _padded_msgpack("ping", n),
}
_SHAPES: Final = [
    *(pytest.param(JSON[0], build, id=f"json-{name}") for name, build in _JSON_SHAPES.items()),
    *(pytest.param(MSGPACK[0], b, id=f"msgpack-{name}") for name, b in _MSGPACK_SHAPES.items()),
]


@pytest.mark.parametrize("size", [MAX_PREAUTH_FRAME_BYTES, MAX_INBOUND_FRAME_BYTES])
@pytest.mark.parametrize(("encoding", "build"), _SHAPES)
def test_decode_before_auth_ok_hands_the_scan_and_decoders_nothing_over_the_cap(
    handed: _Handed, encoding: str, build: Callable[[int], str | bytes], size: int
) -> None:
    _decode(_connection(encoding), build(size))
    assert handed.longest <= MAX_PREAUTH_FRAME_BYTES


# -- `_Connection.decode`: the container cap and the depth scan -----------------------------------


class _Walked(Exception):
    """Raised when something iterates an `_Unwalkable`: the depth scan walked the frame."""


class _Unwalkable(str):
    """JSON text that the depth scan cannot walk: `for ch in text` raises. Sizing it, counting its
    `[` and `{` and parsing it do not iterate it."""

    def __iter__(self) -> Iterator[str]:
        raise _Walked


@_AUTHED
@pytest.mark.parametrize("openers", [3, MAX_JSON_DEPTH])
def test_decode_of_a_frame_with_no_more_openers_than_the_depth_limit_is_never_walked(
    handed: _Handed, openers: int, authed: bool
) -> None:
    frame = _Unwalkable(_containers(openers))
    assert _decode(_connection(JSON[0], authed=authed), frame)["t"] == "ping"
    assert handed.decoded == [("json", len(frame))]


@_AUTHED
@pytest.mark.parametrize("openers", [MAX_JSON_DEPTH + 1, _STATED_CONTAINERS])
def test_decode_of_a_frame_between_the_depth_limit_and_the_container_cap_is_walked(
    openers: int, authed: bool
) -> None:
    frame = _Unwalkable(_containers(openers))
    with pytest.raises(_Walked):
        _decode(_connection(JSON[0], authed=authed), frame)


@_AUTHED
@pytest.mark.parametrize("opener", ["[", '{"a":'], ids=["lists", "objects"])
def test_decode_of_a_frame_one_over_the_container_cap_is_malformed_and_never_walked_or_parsed(
    handed: _Handed, opener: str, authed: bool
) -> None:
    conn = _connection(JSON[0], authed=authed)
    assert _decode(conn, _Unwalkable(opener * (_STATED_CONTAINERS + 1))) == []
    assert not conn.closing
    assert handed.nothing


# -- `_Connection.decode`: the MessagePack value budget -------------------------------------------


def _ping_of(values: int) -> bytes:
    """A MessagePack `ping` the SR-185 decoder charges exactly `values`: 7 for the envelope map,
    3 for `p` and 1 for its `pad` list, plus 1 per nil in that list."""
    assert 11 <= values <= 11 + MAX_MSGPACK_ARRAY_LEN
    packed: bytes = msgpack.packb({"t": "ping", "id": "p", "p": {"pad": [None] * (values - 11)}})
    return packed


#: MessagePack frames within the pre-auth size cap whose value count is over the pre-auth budget
#: and within the SR-185 budget.
_VALUE_SHAPES: Final[dict[str, bytes]] = {
    "empty-arrays": msgpack.packb([[[]] * 128] * 62),
    "one-entry-maps": msgpack.packb([[{"": None}] * 128] * 21),
    "nils": msgpack.packb([[None] * 127] * 62),
}


def test_decode_msgpack_before_auth_ok_value_budget_exact_is_decoded_one_over_malformed() -> None:
    conn = _connection(MSGPACK[0])
    assert _decode(conn, _ping_of(_STATED_VALUES))["t"] == "ping"
    assert _decode(conn, _ping_of(_STATED_VALUES + 1)) == []
    assert not conn.closing  # a strike, counted by `dispatch`, not a close


@pytest.mark.parametrize("frame", list(_VALUE_SHAPES.values()), ids=list(_VALUE_SHAPES))
def test_decode_msgpack_before_auth_ok_charges_no_more_values_than_the_budget(
    charged: list[int], frame: bytes
) -> None:
    """The decode ends on the container whose charge passes the budget: every charge before it
    fits, whatever the frame's shape."""
    assert len(frame) <= MAX_PREAUTH_FRAME_BYTES
    assert _decode(_connection(MSGPACK[0]), frame) == []
    assert sum(charged[:-1]) <= MAX_PREAUTH_MSGPACK_VALUES < sum(charged)


def test_decode_msgpack_after_auth_ok_value_budget_is_the_sr_185_budget() -> None:
    conn = _connection(MSGPACK[0], authed=True)
    assert _decode(conn, _ping_of(MAX_PREAUTH_MSGPACK_VALUES + 1))["t"] == "ping"
    for frame in _VALUE_SHAPES.values():
        assert _decode(conn, frame) == msgpack.unpackb(frame)
    assert _decode(conn, _budget_frame(0)) != []  # exactly MAX_MSGPACK_VALUES
    assert _decode(conn, _budget_frame(1)) == []


def test_codec_value_budget_can_only_be_lowered() -> None:
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_budget_frame(1), max_values=2 * MAX_MSGPACK_VALUES)
    with pytest.raises(MsgpackFrameError, match="values"):
        decode_client_frame(_ping_of(12), max_values=11)


@pytest.mark.parametrize(
    ("authed", "reply"),
    [(False, ("err", "frame_malformed")), (True, ("pong", None))],
    ids=["before-auth_ok", "after-auth_ok"],
)
def test_gateway_msgpack_frame_past_the_pre_auth_value_budget_is_a_strike_until_auth_ok(
    authed: bool, reply: tuple[str, str | None]
) -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
        _hello(ws)
        if authed:
            assert _auth(ws)["t"] == "auth_ok"
        ws.send_bytes(_ping_of(MAX_PREAUTH_MSGPACK_VALUES + 1))
        frame = _recv(ws)
        assert (frame["t"], frame["p"].get("code")) == reply
        _send(ws, {"t": "ping", "id": "p2"})  # one strike is not fatal
        assert _recv(ws)["t"] == "pong"


# -- the constants --------------------------------------------------------------------------------


def _widest_hello() -> dict[str, Any]:
    """The widest conforming `hello`: every property at its bound and each enum list naming every
    member once. The schema bounds no list, so a list that repeats a member is read as
    non-conforming (MessagePack caps any list at 128)."""
    props = _schema("hello")["properties"]
    body = {
        "protocol": props["protocol"]["const"],
        "client": "c" * props["client"]["maxLength"],
        "client_version": "v" * props["client_version"]["maxLength"],
        "locale": "l" * props["locale"]["maxLength"],
        "shell": max(props["shell"]["enum"], key=len),
        "clock_ms": 2**53 - 1,  # no maximum in the schema: the largest integer a JS client keeps
        "capabilities": list(props["capabilities"]["items"]["enum"]),
        "encodings": list(props["encodings"]["items"]["enum"]),
    }
    assert body.keys() == props.keys()  # a new property needs a new bound here
    return {
        "t": "hello",
        "id": "i" * _schema("envelope")["properties"]["id"]["maxLength"],
        "p": body,
    }


def _widest_auth() -> dict[str, Any]:
    """The widest conforming `auth`: the longest `access_token` the schema allows, in ASCII (the
    schema bounds characters; the frame cap counts bytes), and every environment once."""
    props = _schema("auth")["properties"]
    environments = _SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]["environment"]["enum"]
    body = {
        "access_token": "t" * props["access_token"]["maxLength"],
        "environments": list(environments),
    }
    assert body.keys() == props.keys()
    return {
        "t": "auth",
        "id": "i" * _schema("envelope")["properties"]["id"]["maxLength"],
        "p": body,
    }


def _widest_sub() -> dict[str, Any]:
    """The widest `sub` the schema allows: the most topics, each with every list option full (to
    the schema's bound, else the server's) and every object option present."""
    sub = _schema("sub")
    server = {**UNIVERSAL, **{k: o for f in FAMILIES.values() for k, o in f.options.items()}}
    opts: dict[str, Any] = {}
    for name, spec in sub["$defs"]["options"]["properties"].items():
        if spec.get("type") == "array":
            bound = spec.get("maxItems") or server[name].max_items
            assert bound is not None  # every list option has a bound, the schema's or the server's
            opts[name] = ["x"] * bound
        elif spec.get("type") == "object":
            # No family accepts an object option, so `{}` is its widest form. One that does must
            # bound its shape and re-derive this ceiling.
            assert name not in server
            opts[name] = {}
    topics = [
        {"ch": f"t.{i}", "opts": opts} for i in range(sub["properties"]["topics"]["maxItems"])
    ]
    return {"t": "sub", "id": "s", "p": {"topics": topics}}


def test_limits_pre_auth_cap_is_at_most_one_32nd_of_the_inbound_cap() -> None:
    assert MAX_PREAUTH_FRAME_BYTES * 32 <= MAX_INBOUND_FRAME_BYTES


@pytest.mark.parametrize("build", [_widest_hello, _widest_auth], ids=["hello", "auth"])
@pytest.mark.parametrize("subprotocols", [JSON, MSGPACK], ids=["json", "msgpack"])
def test_decode_before_auth_ok_admits_the_widest_schema_valid_hello_and_ascii_auth(
    build: Callable[[], dict[str, Any]], subprotocols: list[str]
) -> None:
    frame = build()
    raw: str | bytes = msgpack.packb(frame) if subprotocols == MSGPACK else json.dumps(frame)
    assert len(raw.encode() if isinstance(raw, str) else raw) <= MAX_PREAUTH_FRAME_BYTES
    assert _decode(_connection(subprotocols[0]), raw) == frame


def test_limits_pre_auth_value_budget_is_at_least_twice_the_widest_hello_and_auth(
    charged: list[int],
) -> None:
    widest = 0
    for build in (_widest_hello, _widest_auth):
        charged.clear()
        decode_client_frame(msgpack.packb(build()))
        widest = max(widest, sum(charged))
    assert 2 * widest <= MAX_PREAUTH_MSGPACK_VALUES


def test_limits_container_cap_is_at_least_twice_the_widest_schema_valid_sub() -> None:
    text = json.dumps(_widest_sub())
    assert text.count("[") + text.count("{") <= MAX_JSON_CONTAINERS // 2
    assert _decode(_connection(JSON[0], authed=True), text)["t"] == "sub"


# -- the gateway, over a socket -------------------------------------------------------------------


@_BOTH
@pytest.mark.parametrize(
    ("stage", "t", "key"),
    [
        pytest.param("before-hello", "hello", "client", id="before-hello"),
        pytest.param("after-welcome", "auth", "access_token", id="after-welcome"),
        pytest.param("after-failed-auth", "ping", "pad", id="after-failed-auth"),
    ],
)
def test_gateway_frame_over_the_pre_auth_cap_gets_bye_frame_too_big_1009_unread(
    handed: _Handed, subprotocols: list[str], stage: str, t: str, key: str
) -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=subprotocols) as ws:
        if stage != "before-hello":
            assert _hello(ws)["t"] == "welcome"
        if stage == "after-failed-auth":
            assert _auth(ws, "rejected")["p"]["code"] == "auth_failed"
        tokens = list(w.tokens_seen)
        handed.clear()
        _send_raw(ws, _padded(subprotocols, t, MAX_PREAUTH_FRAME_BYTES + 1, key))
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("frame_too_big", 1009)
    assert handed.nothing and w.tokens_seen == tokens


@_BOTH
def test_gateway_frame_past_the_pre_auth_cap_is_served_once_auth_ok_is_sent(
    subprotocols: list[str],
) -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=subprotocols) as ws:
        _hello(ws)
        assert _auth(ws)["t"] == "auth_ok"
        _send_raw(ws, _padded(subprotocols, "ping", MAX_PREAUTH_FRAME_BYTES + 1))
        assert _recv(ws)["t"] == "pong"


# -- the inbound rate: a `pong` before `auth_ok` --------------------------------------------------


def test_gateway_pong_counts_toward_the_inbound_rate_until_auth_ok_only(
    allowed: list[bool],
) -> None:
    """§8.5: the limiter is asked about a `pong` before `auth_ok`, as about any frame, and, within
    its budget, not after it. Each `ping` is answered before the next count is read, so every
    frame before it has been handled."""
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _send(ws, {"t": "pong", "id": "s-hb-1"})
        _send(ws, {"t": "ping", "id": "p1"})
        assert _recv(ws)["t"] == "pong"
        before = len(allowed)  # `hello`, `pong`, `ping`
        assert _auth(ws)["t"] == "auth_ok"
        _send(ws, {"t": "pong", "id": "s-hb-2"})
        _send(ws, {"t": "ping", "id": "p2"})
        assert _recv(ws)["t"] == "pong"
        after = len(allowed) - before  # `auth`, `ping`
    assert (before, after) == (3, 2)
    assert all(allowed)


def test_gateway_pongs_before_auth_ok_get_client_rate_limited_then_4429() -> None:
    """A peer that sends only `pong` frames before `auth_ok` meets the inbound rate like any
    other: the fake clock stands still, so every frame below falls in one second."""
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)  # the first frame of this second
        for _ in range(RATE_PER_SECOND - 1):
            _send(ws, {"t": "pong", "id": "s-hb-1"})
        _send(ws, {"t": "ping", "id": "over"})
        err = _recv(ws)
        assert (err["t"], err["p"].get("code")) == ("err", "client_rate_limited")
        _send(ws, {"t": "pong", "id": "s-hb-1"})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("client_rate_limited", 4429)


# -- a `pong` after `auth_ok`: at most 256 bytes (§8.5) -------------------------------------------

#: The bound 23 §8.5 states, spelled out like `_STATED_CAP`.
_STATED_PONG_BYTES = 256
_MOST = 2**53 - 1  # no maximum in the schema: the largest integer a JS client keeps


def _wire(subprotocols: list[str], frame: dict[str, Any]) -> str | bytes:
    return msgpack.packb(frame) if subprotocols == MSGPACK else json.dumps(frame)


def _bye(conn: _Connection) -> tuple[str, int] | None:
    """The reason and code of the close `conn` queued, if any."""
    p = None if conn.bye_frame is None else conn.bye_frame["p"]
    return None if p is None else (p["reason"], p["code"])


def _schema_valid_long_pong() -> dict[str, Any]:
    """A `pong` the §13 schemas accept, with `id`, `ch` and `rs` at their bounds and every
    heartbeat field: over 256 bytes on either wire."""
    heartbeat = {"client_ms": _MOST, "server_ms": _MOST, "rtt_hint_ms": _MOST}
    bounded = {"id": "i" * 64, "ch": "a" + ".b" * 59, "rs": str(uuid.UUID(int=1))}
    return {"t": "pong", **bounded, "ts": _MOST, "p": heartbeat}


@pytest.mark.parametrize(("subprotocols", "decoder"), _CODECS)
def test_an_oversized_pong_after_auth_ok_closes_protocol_violation(
    handed: _Handed, subprotocols: list[str], decoder: str
) -> None:
    """Past 256 bytes, padded, at the schemas' bounds or as a 15-key map, a `pong` led by its `t`
    gets `bye protocol_violation` (1002) and no parser is handed it; at 256 it is handled."""
    at_bound = _padded(subprotocols, "pong", _STATED_PONG_BYTES)
    assert _decode(_connection(subprotocols[0], authed=True), at_bound)["t"] == "pong"
    assert [name for name, _ in handed.decoded] == [decoder]
    handed.clear()
    wide = {"t": "pong", **{f"k{i:02}": "x" * 20 for i in range(14)}}  # 15 keys: a fixmap's most
    for frame in (
        _padded(subprotocols, "pong", _STATED_PONG_BYTES + 1),
        _wire(subprotocols, _schema_valid_long_pong()),
        _wire(subprotocols, wide),
    ):
        conn = _connection(subprotocols[0], authed=True)
        assert _decode(conn, frame) is _OVERSIZE and _bye(conn) == ("protocol_violation", 1002)
    assert handed.nothing


@pytest.mark.parametrize(
    ("subprotocols", "raw", "read"),
    [
        pytest.param(JSON, '{"id":"p","t":"pong","p":{"pad":"%s"}}', True, id="json-t-later"),
        pytest.param(JSON, ' \n{ "t" : "pong" , "p": {"pad": "%s"}}', False, id="json-spaced"),
        pytest.param(JSON, '{"\\u0074": "pong", "p": {"pad": "%s"}}', True, id="json-t-escaped"),
        pytest.param(JSON, " " * 256 + '{"t":"pong","p":{"pad":"%s"}}', True, id="json-late-brace"),
        pytest.param(MSGPACK, {"id": "p", "t": "pong"}, True, id="msgpack-t-later"),
    ],
)
def test_an_oversized_pong_closes_protocol_violation_however_its_t_is_written(
    handed: _Handed, subprotocols: list[str], raw: str | dict[str, Any], read: bool
) -> None:
    """However its `t` is written, it closes. It is decoded first when its `t` comes later, is
    escaped or follows 256 characters of whitespace; a `t` that opens it, spaced or not, is not."""
    pad = "x" * _STATED_PONG_BYTES
    frame = raw % pad if isinstance(raw, str) else msgpack.packb({**raw, "p": {"pad": pad}})
    conn = _connection(subprotocols[0], authed=True)
    assert _decode(conn, frame) is _OVERSIZE and _bye(conn) == ("protocol_violation", 1002)
    assert bool(handed.decoded) is read


_LONG_PONG: Final = {"t": "pong", "id": "p", "p": {"pad": "x" * _STATED_PONG_BYTES}}
_NO_PONGS: Final[dict[str, Any]] = {
    **{t: {"t": t, "id": "p", "p": {"pad": "x" * 300}} for t in ("ping", "pond", "pongs", "Pong")},
    "pong-inside": {"id": "pong", "t": "ping", "p": {"t": "pong", "pad": "x" * 300}},
}


@pytest.mark.parametrize(
    ("encoding", "raw", "decoded"),
    [
        *(
            pytest.param(s[0], _wire(s, f), f, id=f"{s[0]}-{n}")
            for s in (JSON, MSGPACK)
            for n, f in _NO_PONGS.items()
        ),
        pytest.param(MSGPACK[0], json.dumps(_LONG_PONG), [], id="text-on-msgpack"),
        pytest.param(JSON[0], msgpack.packb(_LONG_PONG), [], id="binary-on-json"),
        pytest.param(MSGPACK[0], b"\x80" + msgpack.packb(_LONG_PONG)[1:], [], id="empty-map"),
    ],
)
def test_an_oversized_frame_that_is_no_pong_is_handled_as_before_after_auth_ok(
    encoding: str, raw: str | bytes, decoded: Any
) -> None:
    """One that only mentions `pong` is decoded and served; a frame of the other kind, or an empty
    map, that starts like a `pong` is a strike (`[]`). Neither closes."""
    conn = _connection(encoding, authed=True)
    assert _decode(conn, raw) == decoded and conn.bye_frame is None


_EMOJI_ID: Final = {"t": "pong", "id": "\U0001f600" * 64}  # 64 characters, 256 bytes of UTF-8


@pytest.mark.parametrize(
    ("encoding", "raw"),
    [
        pytest.param(JSON[0], json.dumps(_EMOJI_ID, ensure_ascii=False), id="json-non-ascii-id"),
        pytest.param(MSGPACK[0], msgpack.packb(_EMOJI_ID), id="msgpack-non-ascii-id"),
        pytest.param(JSON[0], '{"t":"pong","p":{"pad":"' + "x" * 300, id="json-malformed"),
        pytest.param(MSGPACK[0], msgpack.packb(_LONG_PONG)[:-1], id="msgpack-malformed"),
    ],
)
def test_a_frame_led_by_t_pong_past_256_bytes_closes_even_if_non_ascii_or_malformed(
    handed: _Handed, encoding: str, raw: str | bytes
) -> None:
    """The bound counts bytes: a 64-character non-ASCII `id` passes it in under 100 characters of
    JSON. A frame that opens with `t: "pong"` and would not parse closes too: no strike."""
    conn = _connection(encoding, authed=True)
    assert _decode(conn, raw) is _OVERSIZE and _bye(conn) == ("protocol_violation", 1002)
    assert handed.nothing


@pytest.mark.parametrize(("subprotocols", "decoder"), _CODECS)
def test_an_oversized_pong_before_auth_ok_is_handled_as_before(
    handed: _Handed, subprotocols: list[str], decoder: str
) -> None:
    conn = _connection(subprotocols[0])
    assert _decode(conn, _wire(subprotocols, _schema_valid_long_pong()))["t"] == "pong"
    assert _bye(conn) is None and [name for name, _ in handed.decoded] == [decoder]


# -- the `pong` budget after `auth_ok` (§8.5), through the real router, flag off and on -----------

_FLAGS = pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])
_BURST = 8  # the budget's most at once, as 23 §8.5 states it
_PONG: Final = {"t": "pong", "id": "s-hb-1"}


async def _fenced(sock: _Wire, *frames: dict[str, Any]) -> list[dict[str, Any]]:
    """Feed `frames`, then a `ping`: what was sent before its `pong`, once all were handled."""
    for frame in (*frames, {"t": "ping", "id": "fence"}):
        sock.feed(frame)
    sent: list[dict[str, Any]] = []
    while (frame := (await sock.next())[0]).get("id") != "fence":
        sent.append(frame)
    return sent


@_FLAGS
@_ENCODINGS
async def test_pongs_within_their_budget_never_reach_the_inbound_limiter(
    flag: BackpressureConfig | None, encoding: str, allowed: list[bool]
) -> None:
    """Before `auth_ok` each `pong` is counted and spends no budget; after it the budget's 8, at
    one instant, are not counted by the limiter, and the 9th is the first it counts."""
    rig, sock = _Rig(flag), _Wire(encoding)
    handler = asyncio.create_task(rig.endpoint(sock))
    try:
        async with asyncio.timeout(5.0):
            sock.feed({"t": "hello", "id": "h", "p": {"clock_ms": BASE_MS}})
            assert [f["t"] for f in await sock.next()] == ["welcome"]
            assert await _fenced(sock, *[_PONG] * _BURST) == []
            assert len(allowed) == 1 + _BURST + 1  # `hello`, each `pong`, the fence
            sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
            assert [f["t"] for f in await sock.next()] == ["auth_ok"]
            assert await _fenced(sock, *[_PONG] * _BURST) == []
            assert len(allowed) == 1 + _BURST + 1 + 2  # then `auth` and the fence alone
            assert await _fenced(sock, _PONG) == []
    finally:
        handler.cancel()
        await asyncio.wait({handler})
    assert len(allowed) == 1 + _BURST + 1 + 2 + 2 and all(allowed)  # the 9th `pong` and a fence


@_ENCODINGS
async def test_a_client_answering_every_ping_at_the_fastest_probe_interval_stays_within_budget(
    encoding: str, allowed: list[bool]
) -> None:
    """60 s at the 500 ms classification floor, each writer turn late, mid or on time in its tick
    (probes as close as 250 ms apart), every server `ping` answered at once: no `pong` reaches
    the limiter, which counts `hello`, `auth` and the two fences of each turn alone."""
    rig, sock = _Rig(BackpressureConfig(classify_interval_ms=500)), _Wire(encoding)
    async with _connected(rig, sock):
        for k in range(1, 121):
            await _at(rig, sock, 0.5 * k + (0.4375, 0.25, 0.0)[k % 3])
    assert len(sock.pings) == 120
    assert len(allowed) == 2 + 2 * 120 and all(allowed)


@_ENCODINGS
async def test_the_widest_reply_pong_with_a_64_character_id_feeds_the_rtt_probe(
    encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `pong` echoing a 64-character probe `id` with `ts` and every heartbeat field is under the
    bound on either wire (`_Wire` writes JSON with spaces): taken, it is the RTT sample (§9.1)."""
    monkeypatch.setattr(pacing, "PROBE_TOKEN_BYTES", 28)  # `s-rtt-1-` and 56 hex characters
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    sock.answer = False
    async with _connected(rig, sock) as conn:
        await _at(rig, sock, 1.0)  # the first classification sends the probe
        [ping] = sock.pings
        heartbeat = {"client_ms": _MOST, "server_ms": _MOST, "rtt_hint_ms": _MOST}
        await _at(rig, sock, 1.125, {"t": "pong", "id": ping["id"], "ts": _MOST, "p": heartbeat})
        assert conn.pipeline is not None and conn.pipeline.ladder is not None
        sample = conn.pipeline.ladder.pacer.probe.sample_ms
    assert (len(ping["id"]), conn.bye_frame, sample) == (64, None, 125.0)
