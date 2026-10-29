"""The inbound budget is charged before a frame is decoded (`23-ws-protocol.md` §3.6, §8.5; #4924).

Every frame, of any kind and on either subprotocol, is charged once against the connection's
inbound rate before any decode work: a frame the rate refuses is never handed to a decoder or to
the depth check, its `err` `client_rate_limited` has no `id` (the frame is never read), and the
second refusal closes `4429`, as the rate refused frames before. From the first `auth_ok` a frame
that opens with `t: "pong"` takes from the `pong` budget first; a frame that does not open so is
charged as any frame. A JSON frame's depth is checked on the value the C decoder returns, so no
Python loop walks the frame's text; what the decoder accepts is unchanged (SR-184)."""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Final

import msgpack
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import candleviewer.ws.gateway as gateway
from candleviewer.ws.codec import MAX_MSGPACK_VALUES, decode_client_frame
from candleviewer.ws.gateway import _REFUSED, GatewayHub, _Connection
from candleviewer.ws.lifecycle import (
    DECODE_BUDGET_BURST,
    MAX_CONNECTIONS_PER_USER,
    PONG_BUDGET_BURST,
    RATE_PER_SECOND,
    WIDEST_SUB_EXTRA_TOKENS,
    DecodeBudget,
    InboundRateLimiter,
)
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_CONTAINERS,
    MAX_JSON_DEPTH,
    MAX_PONG_BYTES,
    MAX_PREAUTH_FRAME_BYTES,
    MAX_SUBSCRIPTIONS,
    MAX_TOPICS_PER_SUB,
    inbound_frame_weight,
    json_depth_exceeds,
    json_nests_deeper,
    json_values_over_count,
)
from tests.security.ws._raw import delta
from tests.unit.ws.test_inbound_frame_limits import (
    _bye,
    _connection,
    _decode,
    _Handed,
    _widest_sub,
)
from tests.unit.ws.test_lifecycle_socket import JSON, MSGPACK, _auth, _hello, _recv, _send, _World

_ENCODINGS: Final = pytest.mark.parametrize(
    "encoding", [JSON[0], MSGPACK[0]], ids=["json", "msgpack"]
)


@pytest.fixture
def handed(monkeypatch: pytest.MonkeyPatch) -> _Handed:
    """Spies on the gateway module's own references to the two decoders and the depth check."""
    seen = _Handed()
    loads, walk = json.loads, gateway.json_nests_deeper

    def spy_loads(raw: str) -> Any:
        seen.decoded.append(("json", len(raw)))
        return loads(raw)

    def spy_unpack(raw: bytes, **budget: int) -> Any:
        seen.decoded.append(("msgpack", len(raw)))
        return decode_client_frame(raw, **budget)

    def spy_walk(value: object, limit: int) -> bool:
        seen.walked.append(value)
        return walk(value, limit)

    monkeypatch.setattr(gateway, "json", SimpleNamespace(loads=spy_loads, dumps=json.dumps))
    monkeypatch.setattr(gateway, "decode_client_frame", spy_unpack)
    monkeypatch.setattr(gateway, "json_nests_deeper", spy_walk)
    return seen


def _wire(encoding: str, frame: dict[str, Any]) -> str | bytes:
    if encoding == MSGPACK[0]:
        packed: bytes = msgpack.packb(frame)
        return packed
    return json.dumps(frame)


def _queued(conn: _Connection) -> list[Any]:
    """Every frame `conn` queued so far, in order (the writer is not running)."""
    items: list[Any] = []
    while not conn.outbound.empty():
        items.append(conn.outbound.get_nowait())
    return items


def _spent(conn: _Connection, encoding: str) -> None:
    """Spend the second's frames of `conn`'s inbound rate, every one admitted."""
    for n in range(RATE_PER_SECOND):
        assert _decode(conn, _wire(encoding, {"t": "ping", "id": f"p{n}"}))["t"] == "ping"


@_ENCODINGS
@pytest.mark.parametrize("authed", [False, True], ids=["before-auth_ok", "after-auth_ok"])
def test_charge_a_frame_past_the_rate_is_refused_before_any_decode_work(
    handed: _Handed, encoding: str, authed: bool
) -> None:
    conn = _connection(encoding, authed=authed)
    _spent(conn, encoding)
    _queued(conn)
    handed.clear()
    assert _decode(conn, _wire(encoding, {"t": "ping", "id": "over"})) is _REFUSED
    assert handed.nothing  # neither decoder nor the depth check saw it
    (err,) = _queued(conn)
    assert (err["t"], err["p"]["code"], "id" in err) == ("err", "client_rate_limited", False)
    assert not conn.closing


@_ENCODINGS
def test_charge_the_second_refusal_closes_4429_unread(handed: _Handed, encoding: str) -> None:
    conn = _connection(encoding, authed=True)
    _spent(conn, encoding)
    handed.clear()
    for n in range(2):
        assert _decode(conn, _wire(encoding, {"t": "sub", "id": f"s{n}", "p": {}})) is _REFUSED
    assert handed.nothing
    assert _bye(conn) == ("client_rate_limited", 4429)
    assert conn.bye_frame is not None and conn.bye_frame["p"]["retry_after_ms"] == 1000


def test_charge_a_frame_at_the_cap_past_the_rate_is_never_decoded(handed: _Handed) -> None:
    """The heaviest frame the cap allows costs no decode once the rate is spent."""
    conn = _connection(JSON[0], authed=True)
    _spent(conn, JSON[0])
    handed.clear()
    head, tail = '{"t":"ping","id":"x","p":{"a":[', "]}}"
    lists = ",".join(["[]"] * (MAX_JSON_CONTAINERS - 3))
    frame = head + lists + ",0" * ((MAX_INBOUND_FRAME_BYTES - len(head + lists + tail)) // 2) + tail
    assert MAX_INBOUND_FRAME_BYTES - 2 <= len(frame) <= MAX_INBOUND_FRAME_BYTES
    assert _decode(conn, frame) is _REFUSED
    assert handed.nothing


@_ENCODINGS
def test_charge_a_leading_pong_after_auth_ok_takes_its_own_budget_not_the_rate(
    encoding: str,
) -> None:
    conn = _connection(encoding, authed=True)
    _spent(conn, encoding)
    for n in range(PONG_BUDGET_BURST):
        assert _decode(conn, _wire(encoding, {"t": "pong", "id": f"q{n}"}))["t"] == "pong"
    assert _decode(conn, _wire(encoding, {"t": "pong", "id": "past"})) is _REFUSED


def test_charge_a_pong_whose_t_is_not_its_first_member_counts_as_any_frame() -> None:
    conn = _connection(JSON[0], authed=True)
    _spent(conn, JSON[0])
    assert _decode(conn, json.dumps({"id": "q", "t": "pong"})) is _REFUSED


def test_charge_before_auth_ok_a_leading_pong_counts_as_any_frame() -> None:
    conn = _connection(JSON[0])
    _spent(conn, JSON[0])
    assert _decode(conn, json.dumps({"t": "pong", "id": "q"})) is _REFUSED


# -- the JSON decoder: what it accepts is unchanged ---------------------------------------------

#: Text the standard library reads that RFC 8259 does not define or a double cannot hold. Each still
#: decodes as `json.loads` reads it; the option checks refuse what no option takes (#415 AC-09).
_READ_AS_BEFORE: Final = {
    "nan": '{"t":"ping","id":"p","p":{"x":NaN}}',
    "infinity": '{"t":"ping","id":"p","p":{"x":Infinity}}',
    "lone-surrogate": '{"t":"ping","id":"\\ud800"}',
    "integer-past-64-bits": '{"t":"ping","id":"p","p":{"x":18446744073709551616}}',
    "integer-past-a-double": '{"t":"ping","id":"p","p":{"x":1' + "0" * 400 + "}}",
    "duplicate-key": '{"t":"ping","id":"a","id":"b"}',
}


@pytest.mark.parametrize("text", list(_READ_AS_BEFORE.values()), ids=list(_READ_AS_BEFORE))
def test_json_decode_reads_what_json_loads_reads(text: str) -> None:
    frame = _decode(_connection(JSON[0], authed=True), text)
    assert repr(frame) == repr(json.loads(text))  # `repr`: NaN is not equal to itself


class _Walked(Exception):
    """Raised when something iterates an `_Unwalkable`."""


class _Unwalkable(str):
    """JSON text that no Python loop can walk: `for ch in text` raises. Sizing it, counting its `[`
    and `{`, matching a pattern on it and the C decoder do not iterate it."""

    def __iter__(self) -> Iterator[str]:
        raise _Walked


@pytest.mark.parametrize("openers", [3, MAX_JSON_DEPTH + 1, MAX_JSON_CONTAINERS])
@pytest.mark.parametrize("authed", [False, True], ids=["before-auth_ok", "after-auth_ok"])
def test_decode_never_walks_a_frames_text_in_python(openers: int, authed: bool) -> None:
    text = '{"t":"ping","id":"p","p":{"a":[' + ",".join(["[]"] * (openers - 3)) + "]}}"
    assert _decode(_connection(JSON[0], authed=authed), _Unwalkable(text))["t"] == "ping"


# -- the depth check on the decoded value ---------------------------------------------------------

_JSON_VALUES: Final = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(alphabet='[]{}"\\ab', max_size=4),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=2), inner, max_size=3)
    ),
    max_leaves=60,
)


@settings(max_examples=300, deadline=None, derandomize=True)
@given(value=_JSON_VALUES, limit=st.integers(0, 8))
def test_json_nests_deeper_agrees_with_the_text_scan(value: Any, limit: int) -> None:
    assert json_nests_deeper(value, limit) == json_depth_exceeds(json.dumps(value), limit)


@pytest.mark.parametrize(("depth", "over"), [(MAX_JSON_DEPTH, False), (MAX_JSON_DEPTH + 1, True)])
def test_json_nests_deeper_at_the_limit_and_one_past_it(depth: int, over: bool) -> None:
    value: Any = 0
    for n in range(depth):
        value = [value] if n % 2 else {"k": value}
    assert json_nests_deeper(value, MAX_JSON_DEPTH) is over


def test_json_nests_deeper_a_scalar_has_no_depth() -> None:
    assert not json_nests_deeper("[[[", 0)
    assert json_nests_deeper([], 0)


@pytest.mark.parametrize(
    ("lists", "malformed"), [(MAX_JSON_DEPTH - 1, False), (MAX_JSON_DEPTH, True)]
)
def test_decode_after_auth_ok_depth_counts_the_envelope(lists: int, malformed: bool) -> None:
    """The envelope is depth 1, so `lists` nested lists in `p` reach depth `lists + 1`."""
    text = '{"t":"ping","p":' + "[" * lists + "]" * lists + "}"
    frame = _decode(_connection(JSON[0], authed=True), text)
    assert (frame == []) is malformed


# -- the JSON value bound (#4924): SR-185's number, over-counted on the text before decode ------


def _values(value: Any) -> int:
    """The values SR-185 charges for `value`: one for it, and those of each element, or of each
    key (one) and value of an object."""
    if isinstance(value, list):
        return 1 + sum(_values(v) for v in value)
    if isinstance(value, dict):
        return 1 + sum(1 + _values(v) for v in value.values())
    return 1


@settings(max_examples=300, deadline=None, derandomize=True)
@given(value=_JSON_VALUES)
def test_json_values_over_count_is_never_below_the_values_a_frame_holds(value: Any) -> None:
    text = json.dumps(value)
    assert json_values_over_count(text) >= _values(value)
    assert json_values_over_count(json.dumps(value, indent=1)) == json_values_over_count(text)


def test_json_values_over_count_is_exact_without_empty_containers_or_strings_that_hold_them() -> (
    None
):
    frame = {"t": "sub", "id": "s", "p": {"topics": [{"ch": "a", "opts": {"x": [1, 2, 3]}}]}}
    assert json_values_over_count(json.dumps(frame)) == _values(frame)


def _at_values(values: int) -> str:
    """A `ping` that `json_values_over_count` puts at `values` exactly."""
    head, tail = '{"t":"ping","id":"p","p":{"pad":[0', "]}}"
    text = head + ",0" * (values - json_values_over_count(head + tail)) + tail
    assert json_values_over_count(text) == values
    return text


def test_decode_a_json_frame_at_the_value_bound_is_decoded(handed: _Handed) -> None:
    text = _at_values(MAX_MSGPACK_VALUES)
    assert _decode(_connection(JSON[0], authed=True), text)["t"] == "ping"
    assert handed.decoded == [("json", len(text))]


def test_decode_a_json_frame_one_past_the_value_bound_is_malformed_and_never_decoded(
    handed: _Handed,
) -> None:
    """After `auth_ok`; before it the 8 KiB cap holds fewer values than the bound."""
    conn = _connection(JSON[0], authed=True)
    assert _decode(conn, _at_values(MAX_MSGPACK_VALUES + 1)) == []
    assert handed.nothing and not conn.closing


def test_gateway_a_json_frame_past_the_value_bound_is_a_frame_malformed_strike() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        assert _auth(ws)["t"] == "auth_ok"
        ws.send_text(_at_values(MAX_MSGPACK_VALUES + 1))
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        _send(ws, {"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"  # one strike of three: the socket is served


def test_limits_value_bound_holds_the_widest_schema_valid_sub_and_ctl_with_room() -> None:
    """The widest `sub` the schema allows (every list option full, 50 topics) and a `ctl` with all
    of one topic's options stay under two thirds of the bound, and are served."""
    sub = _widest_sub()
    ctl = {"t": "ctl", "id": "k", "ch": "t.0", "p": sub["p"]["topics"][0]["opts"]}
    for frame in (sub, ctl):
        text = json.dumps(frame)
        assert 3 * json_values_over_count(text) <= 2 * MAX_MSGPACK_VALUES
        assert _decode(_connection(JSON[0], authed=True), text)["t"] == frame["t"]


# -- the frame weight (#4924): one token, plus one per full 32 KiB, before decode -----------------


def test_inbound_frame_weight_is_one_plus_one_per_full_32_kib_and_4096_values() -> None:
    assert [inbound_frame_weight(n) for n in (0, 32_767, 32_768, 65_535, 65_536)] == [1, 1, 2, 2, 3]
    assert [inbound_frame_weight(0, v) for v in (4_095, 4_096, 16_384, 16_385)] == [1, 2, 5, 5]
    assert (
        inbound_frame_weight(MAX_PREAUTH_FRAME_BYTES) == inbound_frame_weight(MAX_PONG_BYTES) == 1
    )
    assert inbound_frame_weight(MAX_INBOUND_FRAME_BYTES) == 9 <= RATE_PER_SECOND  # always fits


def test_inbound_rate_limiter_counts_tokens_in_both_windows() -> None:
    limiter = InboundRateLimiter()
    assert [limiter.allow(0.0, 9) for _ in range(4)] == [True, True, True, False]  # 27 + 9 > 30
    assert limiter.allow(0.0, 3) and not limiter.allow(0.0, 1)  # 30 of 30: refused, unrecorded
    for second in range(1, 10):  # 30 more each second: the minute's 300 by second 9
        assert limiter.allow(float(second), 30)
    assert not limiter.allow(10.0, 1)
    assert limiter.allow(60.0, 30)  # second 0's 30 have left the minute


@_ENCODINGS
def test_charge_a_frame_whose_weight_the_tokens_left_cannot_cover_is_refused_unread(
    handed: _Handed, encoding: str
) -> None:
    """Three frames near the cap take 27 of the second's 30; the fourth (9) is refused before it is
    decoded, as the rate refuses any frame, while a small one still fits."""
    conn = _connection(encoding, authed=True)
    big = _wire(encoding, {"t": "ping", "id": "b", "p": {"pad": "x" * 250_000}})
    assert inbound_frame_weight(len(big)) == 8
    for _ in range(3):
        assert _decode(conn, big)["t"] == "ping"
    handed.clear()
    _queued(conn)
    assert _decode(conn, big) is _REFUSED and handed.nothing  # 24 + 8 > 30
    (err,) = _queued(conn)
    assert (err["p"]["code"], "id" in err) == ("client_rate_limited", False)
    assert _decode(conn, _wire(encoding, {"t": "ping", "id": "s"}))["t"] == "ping"


def test_charge_a_reconnect_re_subscribing_its_set_with_the_widest_subs_is_never_refused() -> None:
    """§9.2: no resumption, so a client reconnecting sends `hello`, `auth` and its whole set again:
    `MAX_SUBSCRIPTIONS` topics in `sub`s of `MAX_TOPICS_PER_SUB`, each here the widest the schema
    allows, all in the same instant. None is rate-limited: with their bytes and their values they
    take 18 of the second's 30 tokens."""
    sub = _widest_sub()
    frames = MAX_SUBSCRIPTIONS // MAX_TOPICS_PER_SUB
    text = json.dumps(sub)
    weight = inbound_frame_weight(len(text.encode()), json_values_over_count(text))
    assert weight == 4 and 2 + frames * weight <= RATE_PER_SECOND  # 18 of the second's 30
    w = _World()
    for _ in range(3):  # reconnecting, again and again: each socket's budget is its own
        with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            assert _hello(ws)["t"] == "welcome"
            assert _auth(ws)["t"] == "auth_ok"
            for n in range(frames):
                _send(ws, {**sub, "id": f"s{n}"})
                reply = _recv(ws)
                assert (reply["t"], reply["id"]) == ("sub_ok", f"s{n}")
            _send(ws, {"t": "ping", "id": "p"})
            assert _recv(ws)["t"] == "pong"


def _compact_at_bound(id: str) -> str:
    """A JSON `ping` at the value bound in under 32 KiB: the container cap's lists, then `0`s."""
    head, tail = f'{{"t":"ping","id":"{id}","p":{{"pad":[', "]}}"
    lists = ",".join(["[]"] * (MAX_JSON_CONTAINERS - 3))
    text = head + lists + ",0" * (MAX_MSGPACK_VALUES - json_values_over_count(head + lists + tail))
    text += tail
    assert json_values_over_count(text) == MAX_MSGPACK_VALUES and len(text) < 32 * 1024
    return text


def _msgpack_at_bound(id: str) -> bytes:
    """A MessagePack `ping` its decoder charges the value bound exactly, in about 16 KiB."""
    pad = [[None] * n for n in [128] * 125 + [119, 0]]
    packed: bytes = msgpack.packb({"t": "ping", "id": id, "p": {"pad": pad}})
    charged: list[int] = []
    decode_client_frame(packed, charged=charged)
    assert charged == [MAX_MSGPACK_VALUES]
    return packed


@pytest.mark.parametrize("encoding", [JSON[0], MSGPACK[0]], ids=["json-charged", "msgpack-debited"])
def test_charge_a_frame_at_the_value_bound_takes_five_tokens_however_small(encoding: str) -> None:
    """JSON: 1 + 0 + 4 before decode. MessagePack: 1 before decode, 4 debited right after it. So
    six fit the second's 30 and the seventh is refused before it is decoded."""
    conn = _connection(encoding, authed=True)
    build = _compact_at_bound if encoding == JSON[0] else _msgpack_at_bound
    answers = [_decode(conn, build(f"v{n}")) for n in range(7)]
    assert [a is _REFUSED for a in answers] == [False] * 6 + [True]
    assert all(a["t"] == "ping" for a in answers[:6])


def test_inbound_rate_limiter_debit_adds_to_the_last_frame_admitted() -> None:
    limiter = InboundRateLimiter()
    limiter.debit(5)  # nothing admitted yet: nothing to add to
    assert limiter.allow(0.0, 1)
    limiter.debit(28)  # 29 of 30
    assert limiter.allow(0.0, 1) and not limiter.allow(0.0, 1)
    assert limiter.allow(1.0, 30)  # the second has passed; the minute holds 60 of 300


@_ENCODINGS
def test_charge_a_small_frame_led_by_t_pong_that_decodes_to_another_kind_is_charged_to_the_rate(
    encoding: str,
) -> None:
    """From `auth_ok`, a frame that opens with `t: "pong"` takes the `pong` budget; one that turns
    out to be another kind (a later `t` wins) is then counted by the rate too, and refused as the
    rate refuses one when it has no room."""
    if encoding == JSON[0]:
        frame: str | bytes = '{"t":"pong","t":"ping","id":"x"}'
    else:  # a fixmap of 2: `t: "pong"`, then `t: "ping"`
        frame = b"\x82\xa1t\xa4pong\xa1t\xa4ping"
    roomy = _connection(encoding, authed=True)
    assert _decode(roomy, frame)["t"] == "ping"  # room: counted, and handled
    assert not roomy.rate.allow(0.0, RATE_PER_SECOND)  # the rate took one of its 30
    conn = _connection(encoding, authed=True)
    _spent(conn, encoding)
    _queued(conn)
    assert _decode(conn, frame) is _REFUSED
    (err,) = _queued(conn)
    assert (err["p"]["code"], conn.rate_strikes) == ("client_rate_limited", 1)


# -- the per-user decode budget (#4924): tokens past the first, shared by a user's sockets -------


def test_decode_budget_holds_its_burst_refills_and_carries_a_debt() -> None:
    budget = DecodeBudget(burst=10, per_second=2)
    assert budget.can(0.0, 10) and not budget.can(0.0, 11)
    budget.take(10)
    assert not budget.can(0.0, 1) and budget.can(0.5, 1)  # half a second: one token back
    budget.debit(0.5, 5)  # 1 - 5: in debt
    assert not budget.can(2.0, 0) and budget.can(2.5, 0)  # out of debt once refilled to 0


def test_decode_budget_burst_is_every_socket_re_subscribing_with_the_widest_subs() -> None:
    sub = json.dumps(_widest_sub())
    extra = inbound_frame_weight(len(sub.encode()), json_values_over_count(sub)) - 1
    assert extra == WIDEST_SUB_EXTRA_TOKENS
    subs = MAX_SUBSCRIPTIONS // MAX_TOPICS_PER_SUB
    assert DECODE_BUDGET_BURST == MAX_CONNECTIONS_PER_USER * subs * extra == 96


def test_hub_shares_one_budget_per_user_and_drops_it_with_the_last_socket() -> None:
    hub = GatewayHub()
    a, b, early = _connection(JSON[0]), _connection(JSON[0]), _connection(JSON[0])
    for conn in (a, b, early):
        hub.add(conn)
    user = uuid.uuid4()
    for conn in (a, b):  # what the first `auth_ok` does
        conn.user_id, conn.decode_budget = user, hub.decode_budget(user)
    assert a.decode_budget is b.decode_budget and early.decode_budget is None
    assert hub.decode_budget(uuid.uuid4()) is not a.decode_budget  # another user's is its own
    hub.discard(a)
    assert hub.decode_budget(user) is b.decode_budget  # kept while a socket of the user lives
    hub.discard(b)
    assert hub.decode_budget(user) is not b.decode_budget  # dropped with the last one


def test_charge_a_frame_past_one_token_is_refused_when_the_users_budget_is_spent() -> None:
    """Two sockets of one user: the first spends the shared budget with frames near the cap; the
    second's next such frame is refused on its own socket, as the rate refuses one, and counted;
    its frames of one token still pass on its own rate."""
    refused = delta("cv_ws_decode_budget_refused_total")
    budget = DecodeBudget(burst=14, per_second=1)
    first, second = (_connection(JSON[0], authed=True) for _ in range(2))
    first.decode_budget = second.decode_budget = budget
    big = json.dumps({"t": "ping", "id": "b", "p": {"pad": "x" * 250_000}})  # 8 tokens: 7 shared
    assert _decode(first, big)["t"] == "ping"
    assert _decode(second, big)["t"] == "ping"  # 14 of 14
    _queued(second)
    assert _decode(second, big) is _REFUSED
    (err,) = _queued(second)
    assert (err["p"]["code"], second.rate_strikes, refused()) == ("client_rate_limited", 1, 1)
    assert _decode(second, json.dumps({"t": "ping", "id": "s"}))["t"] == "ping"


def test_charge_a_msgpack_frame_that_may_owe_a_debit_waits_for_the_budget_out_of_debt() -> None:
    budget = DecodeBudget(burst=4, per_second=1)
    conn = _connection(MSGPACK[0], authed=True)
    conn.decode_budget = budget
    assert _decode(conn, _msgpack_at_bound("a"))["t"] == "ping"  # 0 before, 4 debited: 0 left
    assert _decode(conn, _msgpack_at_bound("b"))["t"] == "ping"  # 0 >= 0: admitted, -4 after
    assert _decode(conn, _msgpack_at_bound("c")) is _REFUSED  # in debt
    small = msgpack.packb({"t": "ping", "id": "s"})
    assert _decode(conn, small)["t"] == "ping"  # under 4 KiB: its socket's rate only


def test_gateway_every_socket_of_a_user_re_subscribing_with_the_widest_subs_is_never_refused() -> (
    None
):
    """All eight sockets a user may hold reconnect at the same instant and re-subscribe their whole
    sets with the widest `sub`s: every one is served, and the shared budget is spent exactly, so
    one more such `sub` on any of them is refused."""
    sub = _widest_sub()
    w = _World()
    with contextlib.ExitStack() as stack:
        sockets = [
            stack.enter_context(w.client.websocket_connect("/ws", subprotocols=JSON))
            for _ in range(MAX_CONNECTIONS_PER_USER)
        ]
        stack.enter_context(w.client)
        for ws in sockets:
            assert _hello(ws)["t"] == "welcome"
            assert _auth(ws)["t"] == "auth_ok"
        for ws in sockets:
            for n in range(MAX_SUBSCRIPTIONS // MAX_TOPICS_PER_SUB):
                _send(ws, {**sub, "id": f"s{n}"})
                assert _recv(ws)["t"] == "sub_ok"
        _send(sockets[0], {**sub, "id": "more"})
        assert _recv(sockets[0])["p"]["code"] == "client_rate_limited"
