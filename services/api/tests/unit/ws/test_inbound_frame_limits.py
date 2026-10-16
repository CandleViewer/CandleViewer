"""SR-184: the inbound frame limits before `auth_ok` and before decode (`23-ws-protocol.md` §3.6).

Until the first `auth_ok`, the `hello` included, a frame may be at most `MAX_PREAUTH_FRAME_BYTES`:
a larger one gets `bye frame_too_big` and 1009 and is never scanned or decoded. A JSON text frame
holds at most `MAX_JSON_CONTAINERS` `[` and `{` characters: more is a `frame_malformed` strike, and
the depth scan never walks it. Everything is counted, never timed: sizes, and what the depth scan
and each decoder were handed (spies on the gateway module's own references)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import msgpack
import pytest

import candleviewer.ws.gateway as gateway
from candleviewer.ws.codec import decode_client_frame
from candleviewer.ws.gateway import _OVERSIZE, _Connection
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
    JSON,
    MSGPACK,
    _auth,
    _bye_then_close,
    _hello,
    _recv,
    _World,
)

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

    def spy_unpack(raw: bytes) -> Any:
        seen.decoded.append(("msgpack", len(raw)))
        return decode_client_frame(raw)

    monkeypatch.setattr(gateway, "json", SimpleNamespace(loads=spy_loads, dumps=json.dumps))
    monkeypatch.setattr(gateway, "json_depth_exceeds", spy_scan)
    monkeypatch.setattr(gateway, "decode_client_frame", spy_unpack)
    return seen


# -- `_Connection.decode`: the size cap -----------------------------------------------------------


@pytest.mark.parametrize(("subprotocols", "decoder"), _CODECS)
def test_decode_before_auth_ok_cap_exact_is_decoded_and_one_over_is_refused_unread(
    handed: _Handed, subprotocols: list[str], decoder: str
) -> None:
    conn = _connection(subprotocols[0])
    exact = _padded(subprotocols, "hello", MAX_PREAUTH_FRAME_BYTES, "client")
    assert _decode(conn, exact)["t"] == "hello"
    assert handed.decoded == [(decoder, MAX_PREAUTH_FRAME_BYTES)]
    handed.clear()
    over = _padded(subprotocols, "hello", MAX_PREAUTH_FRAME_BYTES + 1, "client")
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
@pytest.mark.parametrize("openers", [MAX_JSON_DEPTH + 1, MAX_JSON_CONTAINERS])
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
    assert _decode(conn, _Unwalkable(opener * (MAX_JSON_CONTAINERS + 1))) == []
    assert not conn.closing
    assert handed.nothing


# -- the constants --------------------------------------------------------------------------------


def _widest_hello() -> dict[str, Any]:
    """The widest `hello` the schema allows: every property at its bound, each enum list holding
    every member once (the schema sets no list bound; MessagePack caps one at 128)."""
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
            opts[name] = {}
    topics = [
        {"ch": f"t.{i}", "opts": opts} for i in range(sub["properties"]["topics"]["maxItems"])
    ]
    return {"t": "sub", "id": "s", "p": {"topics": topics}}


def test_limits_pre_auth_cap_is_at_most_one_32nd_of_the_inbound_cap() -> None:
    assert MAX_PREAUTH_FRAME_BYTES * 32 <= MAX_INBOUND_FRAME_BYTES


@pytest.mark.parametrize("build", [_widest_hello, _widest_auth], ids=["hello", "auth"])
@pytest.mark.parametrize("subprotocols", [JSON, MSGPACK], ids=["json", "msgpack"])
def test_decode_before_auth_ok_admits_the_widest_schema_valid_hello_and_auth(
    build: Callable[[], dict[str, Any]], subprotocols: list[str]
) -> None:
    frame = build()
    raw: str | bytes = msgpack.packb(frame) if subprotocols == MSGPACK else json.dumps(frame)
    assert len(raw.encode() if isinstance(raw, str) else raw) <= MAX_PREAUTH_FRAME_BYTES
    assert _decode(_connection(subprotocols[0]), raw) == frame


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
