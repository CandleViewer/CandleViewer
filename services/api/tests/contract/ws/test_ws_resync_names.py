"""#3218 through the real gateway (`23-ws-protocol.md` §5.2 to §5.4, §7.5, §9.5, §11, §16.6 W10): a
`resync`, `ctl` or `unsub` names its stream by `ch` and the envelope `rs` (no `rs`: the live one), a
`resync`'s `p.sub_id` is a pin, the refusals come in §7.5's order and change nothing, a live and a
replay stream of one `ch` keep their own snapshots and resync limits, and the server's frames name
their subscription. Every row runs on both wires (conftest.py); every frame received is validated
against §13."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.limits import SUB_ID_MAX_LEN
from tests.contract.ws._harness import SCHEMAS, Client, World, connect, current_offer, publish

BOOK, TICKER, TRADES = "book.BTCUSDT.50", "ticker.BTCUSDT", "trades.BTCUSDT"
RS, OTHER_RS = "bb000000-0000-4000-8000-000000000001", "bb000000-0000-4000-8000-000000000002"
LIMIT = 5  # §7.5: resyncs a minute per stream
FLAGS = pytest.mark.parametrize(
    "backpressure", [None, BackpressureConfig()], ids=["flag_off", "flag_on"]
)
#: §7.5: not the §13 `$defs/uuid` form, though `uuid.UUID` reads all of them but the last.
NOT_UUIDS = {
    "urn": f"urn:uuid:{RS}",
    "braces": "{" + RS + "}",
    "no-hyphens": RS.replace("-", ""),
    "extra-hyphen": RS[:28] + "-" + RS[28:],
    "non-ascii-digit": RS[:-1] + chr(0x661),  # ARABIC-INDIC DIGIT ONE
    "trailing-newline": RS + "\n",
}
#: The fixed `message` of each refusal: no value the client sent is ever in it.
TOLD = {
    "not_subscribed": ERROR_META[ErrorCode.NOT_SUBSCRIBED].title,
    "rs": "rs must be a uuid.",
    "sub_id": f"sub_id must be a string of 1 to {SUB_ID_MAX_LEN} characters.",
}


def _replay(c: Client, *topics: str, rs: Any = RS, conform: bool = True) -> list[dict[str, Any]]:
    """One replay `sub` (§11); its results."""
    entries = [{"ch": t} for t in topics]
    p = {"topics": entries, "replay_session_id": rs}
    c.send({"t": "sub", "id": "r", "p": p}, conform=conform)
    results: list[dict[str, Any]] = c.next_of("sub_ok")["p"]["results"]
    return results


def _fenced(c: Client) -> list[dict[str, Any]]:
    """Every frame sent before a fresh topic's first `snap`, but that topic's `sub_ok`. The `snap`
    queues behind every earlier one, on the normal lane too, so this fence holds with the
    backpressure flag on, where a `pong` could overtake a `snap` (§8.4 Lanes)."""
    fence = f"trades.F{len(c.seen)}USDT"
    c.send({"t": "sub", "id": "fence", "p": {"topics": [{"ch": fence}]}})
    out: list[dict[str, Any]] = []
    while not ((f := c.recv())["t"] == "snap" and f["ch"] == fence):
        if f.get("id") != "fence":
            out.append(f)
    return out


def _twins(c: Client) -> tuple[str, str]:
    """A live and a replay stream of BOOK (§11): their `sub_id`s, once both first snaps are in."""
    live = c.sub(BOOK)["p"]["results"][0]["sub_id"]
    (replay,) = _replay(c, BOOK)
    _fenced(c)
    return live, replay["sub_id"]


def _resync(c: Client, rid: str, *, conform: bool = True, **fields: Any) -> None:
    """A `resync` of BOOK: `rs`, when given (`None` too), on the envelope; the rest in `p`."""
    head = {"rs": fields.pop("rs")} if "rs" in fields else {}
    p = {"reason": "manual", **fields}
    c.send({"t": "resync", "id": rid, "ch": BOOK, **head, "p": p}, conform=conform)


def _snaps(frames: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    meta = [f.get("meta", {}) for f in frames]
    return [
        (f["t"], f.get("rs"), f.get("s"), m.get("reason"), m.get("previous_seq"))
        for f, m in zip(frames, meta, strict=True)
    ]


def _err(rid: str, told: str, rs: str | None = None) -> dict[str, Any]:
    """The `err` a refused `resync` of BOOK gets (§7.5): its `id` and `ch`, the request's `rs` when
    that is a uuid, and a fixed message."""
    p: dict[str, Any] = {"code": "not_subscribed", "message": TOLD[told]}
    if told != "not_subscribed":
        p |= {"code": "invalid_options", "field": told}
    frame = {"t": "err", "id": rid, "ch": BOOK, "p": p | {"retryable": False, "close": False}}
    return frame | ({"rs": rs} if rs else {})


def _all_left(c: Client) -> None:
    """Each stream of BOOK still has all of its resyncs in the window (§7.5)."""
    for i in range(LIMIT):
        _resync(c, f"r{i}", rs=RS)
        _resync(c, f"l{i}")
    assert [(f["t"], f.get("rs")) for f in _fenced(c)] == [("snap", RS), ("snap", None)] * LIMIT


def test_the_sub_id_bound_is_the_schema_s() -> None:
    sub_id = SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]["subId"]
    assert (sub_id["minLength"], sub_id["maxLength"]) == (1, SUB_ID_MAX_LEN)


@FLAGS
def test_a_loss_on_the_replay_stream_resnapshots_the_replay_stream_only(
    backpressure: BackpressureConfig | None,
) -> None:
    """Gherkin: a `resync` naming the replay stream by `rs` (with its `sub_id` pin) gets one `snap`
    with that `rs`; the live stream gets none, and none of its limit is spent."""
    with connect(World(backpressure=backpressure)) as c:
        _, replay = _twins(c)
        _resync(c, "c-92", rs=RS, sub_id=replay, reason="sequence_gap", last_seq=1)
        assert _snaps(_fenced(c)) == [("snap", RS, 2, "client_resync", 1)]
        for i in range(LIMIT):
            _resync(c, f"l{i}")
        frames = _fenced(c)  # a later `snap` may replace a queued one with the flag on (§8.4)
        assert {(f["t"], f.get("rs")) for f in frames} == {("snap", None)}


def test_a_second_replay_consumer_s_client_restart_gets_the_replay_baseline() -> None:
    """Gherkin: `rs` names the replay stream whatever the `reason`. It is matched in either letter
    case, and the `snap` carries it in canonical lower case."""
    with connect(World()) as c:
        _twins(c)
        _resync(c, "c-95", rs=RS.upper(), reason="client_restart")
        assert _snaps(_fenced(c)) == [("snap", RS, 2, "client_resync", 1)]


def test_an_unknown_rs_is_refused_with_the_typed_error() -> None:
    """Gherkin: `not_subscribed` with the request `id`, `ch` and `rs`. Nothing is re-snapshotted,
    drawn or revoked, and it is no strike (§4.4: three close), however often it is sent."""
    with connect(World()) as c:
        _twins(c)
        for _ in range(LIMIT + 1):
            _resync(c, "c-96", rs=OTHER_RS)
        assert _fenced(c) == [_err("c-96", "not_subscribed", OTHER_RS)] * (LIMIT + 1)
        _all_left(c)


def test_a_sub_id_must_belong_to_the_resync_s_ch() -> None:
    """Gherkin: the `sub_id` of a trades subscription on a `resync` of BOOK: `not_subscribed`."""
    with connect(World()) as c:
        trades = c.sub(TRADES)["p"]["results"][0]["sub_id"]
        _twins(c)
        _resync(c, "c-97", sub_id=trades)
        assert _fenced(c) == [_err("c-97", "not_subscribed")]


@pytest.mark.parametrize(
    ("fields", "told", "echo"),
    [
        pytest.param({"sub_id": "replay"}, "not_subscribed", None, id="replay-sub-id-without-rs"),
        pytest.param({"sub_id": "live", "rs": RS}, "not_subscribed", RS, id="live-sub-id-with-rs"),
        pytest.param({"sub_id": "replay", "rs": OTHER_RS}, "not_subscribed", OTHER_RS, id="other"),
        pytest.param({"sub_id": "s_99"}, "not_subscribed", None, id="unknown-sub-id"),
        pytest.param({"sub_id": "x" * SUB_ID_MAX_LEN}, "not_subscribed", None, id="at-the-bound"),
        pytest.param({"rs": "not-a-uuid"}, "rs", None, id="rs-not-a-uuid"),
        pytest.param({"rs": 5}, "rs", None, id="rs-not-a-string"),
        pytest.param({"sub_id": ""}, "sub_id", None, id="sub-id-empty"),
        pytest.param({"sub_id": "x" * (SUB_ID_MAX_LEN + 1)}, "sub_id", None, id="too-long"),
        pytest.param({"sub_id": ["s_01"], "rs": RS.upper()}, "sub_id", RS, id="not-a-string"),
    ],
)
def test_a_resync_naming_no_stream_of_its_ch_is_refused_and_changes_nothing(
    fields: dict[str, Any], told: str, echo: str | None
) -> None:
    """§7.5: a `sub_id` is a pin, valid only for the stream `ch` and `rs` name; else, or for an
    unknown one, `not_subscribed`. A malformed `rs` or `sub_id` gets `invalid_options` naming the
    field. No refusal re-snapshots, draws, revokes or is a strike, and none echoes a malformed
    value: the `err` carries the request's `rs` only when it is a uuid, in lower case."""
    with connect(World()) as c:
        own = dict(zip(("live", "replay"), _twins(c), strict=True))
        sent = {k: own.get(v, v) if isinstance(v, str) else v for k, v in fields.items()}
        for _ in range(LIMIT + 1):
            _resync(c, "c-96", conform=False, **sent)
        assert _fenced(c) == [_err("c-96", told, echo)] * (LIMIT + 1)
        _all_left(c)


@pytest.mark.parametrize(
    ("frame", "named"),
    [
        pytest.param({"ch": 7, "p": 3}, ("invalid_options", "ch", None, None), id="ch-then-p"),
        pytest.param({"rs": "x", "p": {}}, ("frame_malformed", None, None, None), id="no-ch"),
        pytest.param(
            {"ch": BOOK, "rs": "x", "p": {"reason": "?"}},
            ("frame_malformed", None, BOOK, None),
            id="reason-then-rs",
        ),
        pytest.param(  # a `reason` that is no string is no known one (§7.5 refusal 2)
            {"ch": BOOK, "rs": "x", "p": {"reason": ["manual"]}},
            ("frame_malformed", None, BOOK, None),
            id="list-reason-then-rs",
        ),
        pytest.param(
            {"ch": BOOK, "rs": RS.upper(), "p": {"reason": {"manual": 1}, "sub_id": ""}},
            ("frame_malformed", None, BOOK, RS),
            id="map-reason-then-sub-id",
        ),
        pytest.param(
            {"ch": BOOK, "rs": RS.upper(), "p": {"reason": "manual", "last_seq": "1"}},
            ("frame_malformed", None, BOOK, RS),
            id="last-seq-then-stream",
        ),
        pytest.param(
            {"ch": BOOK, "rs": "x", "p": {"reason": "manual", "sub_id": ""}},
            ("invalid_options", "rs", BOOK, None),
            id="rs-then-sub-id",
        ),
        pytest.param(
            {"ch": TICKER, "rs": OTHER_RS, "p": {"reason": "manual", "sub_id": ""}},
            ("invalid_options", "sub_id", TICKER, OTHER_RS),
            id="sub-id-then-stream",
        ),
    ],
)
def test_a_resync_breaking_two_rules_is_refused_by_the_first(
    frame: dict[str, Any], named: tuple[Any, ...]
) -> None:
    """§7.5: the refusals come in order (`ch`, the payload, `rs`, `sub_id`, the stream)."""
    with connect(World()) as c:
        _twins(c)
        c.send({"t": "resync", "id": "o", **frame}, conform=False)
        (err,) = _fenced(c)
        assert (err["p"]["code"], err["p"].get("field"), err.get("ch"), err.get("rs")) == named


def test_an_unsub_is_refused_by_its_shape_before_a_malformed_rs() -> None:
    """§5.3: the shape checks come before `rs`. Each `unsub` with `rs` "x" and a broken shape gets
    the shape's `field`, with no `rs`; nothing is unsubscribed, and none is a strike (§4.3)."""
    with connect(World()) as c:
        _twins(c)
        shapes: list[Any] = [{"topics": []}, {"topics": ["Bad Topic"]}, {"topics": [BOOK], "x": 1}]
        for p in shapes:
            c.send({"t": "unsub", "id": "u", "rs": "x", "p": p}, conform=False)
        answers = [(f["p"]["code"], f["p"]["field"], "rs" in f) for f in _fenced(c)]
        assert answers == [("invalid_options", f, False) for f in ("topics", "topics[0]", "p")]
        _all_left(c)  # both streams of BOOK are still held, with all of their resyncs


@pytest.mark.parametrize("fields", [{}, {"rs": None, "sub_id": None}], ids=["neither", "nulls"])
def test_a_resync_with_neither_rs_nor_sub_id_names_the_live_stream(fields: dict[str, Any]) -> None:
    """Gherkin: only the live stream is re-snapshotted (`null` counts as absent). With only the
    replay subscription of `ch` left, the answer is `not_subscribed`: no fallback to it."""
    with connect(World()) as c:
        live, _ = _twins(c)
        _resync(c, "c-97", conform=not fields, **fields)
        assert _snaps(_fenced(c)) == [("snap", None, 2, "client_resync", 1)]
        c.send({"t": "unsub", "id": "u", "p": {"topics": [BOOK]}})  # the live one only (§5.3)
        _resync(c, "c-98", conform=not fields, **fields)
        _resync(c, "c-99", rs=RS)
        unsub_ok, err, snap = _fenced(c)
        assert unsub_ok["p"]["results"] == [{"ch": BOOK, "ok": True, "ended": [{"sub_id": live}]}]
        assert err == _err("c-98", "not_subscribed")
        assert _snaps([snap]) == [("snap", RS, 2, "client_resync", 1)]  # the replay one is held


def test_the_resync_limit_is_kept_per_ch_and_rs() -> None:
    """Gherkin: the replay stream's five leave the live stream's five. A sixth `resync` of a stream
    is its own loop: `err` (with its `rs` on replay), then a `revoked` that names that stream alone
    by `p.sub_id` and, on replay, `rs` (§7.5, §9.5)."""
    with connect(World()) as c:
        live, replay = _twins(c)
        for sub_id, rs in ((replay, RS), (live, None)):
            named: dict[str, Any] = {"rs": rs} if rs else {}
            for i in range(LIMIT + 1):
                _resync(c, f"c-{i}", **named)
            *snaps, err, revoked = _fenced(c)
            assert [(f["t"], f.get("rs")) for f in snaps] == [("snap", rs)] * LIMIT
            assert (err["p"]["code"], err.get("rs")) == ("resync_rate_limited", rs)
            named_by = (revoked["t"], revoked.get("rs"), revoked["p"]["sub_id"])
            assert named_by == ("revoked", rs, sub_id)


def test_the_control_frames_name_their_subscription() -> None:
    """Gherkin: each result of a replay `sub` but `system`'s carries `rs`, accepted or refused, in
    lower case, and an accepted one its `sub_id`; `ctl_ok` carries `p.sub_id` and a replay one's
    envelope `rs`; each `unsub_ok` result lists in `ended` the subscription it ended (§5.2-§5.4).
    `revoked`: test_the_resync_limit_is_kept_per_ch_and_rs, and `replay_session_ended` in
    test_ws_contract.py."""
    with connect(World()) as c:
        live = c.sub(BOOK)["p"]["results"][0]
        book, ticker, system, nope = _replay(c, BOOK, TICKER, "system", "nope.X", rs=RS.upper())
        assert (book["rs"], ticker["rs"], nope["ok"], nope["rs"], "rs" in live) == (
            (RS, RS, False, RS, False)
        )
        assert system == {"ch": "system", "ok": True, "sub_id": "system"}
        _fenced(c)
        c.send({"t": "ctl", "id": "k1", "ch": BOOK, "p": {"throttle_ms": 200}})
        c.send({"t": "ctl", "id": "k2", "ch": BOOK, "rs": RS, "p": {"throttle_ms": 200}})
        assert [(f["id"], f["p"]["sub_id"], f.get("rs")) for f in _fenced(c)] == [
            ("k1", live["sub_id"], None),
            ("k2", book["sub_id"], RS),
        ]
        c.send({"t": "unsub", "id": "u1", "p": {"topics": [BOOK, "system", TRADES]}})
        c.send({"t": "unsub", "id": "u2", "rs": RS, "p": {"topics": [BOOK, TICKER]}})
        u1, u2 = _fenced(c)
        assert [(r["ch"], r["ok"], r.get("ended")) for r in u1["p"]["results"]] == [
            (BOOK, True, [{"sub_id": live["sub_id"]}]),
            ("system", False, None),
            (TRADES, True, None),  # a `noop` ends nothing
        ]
        assert [r["ended"] for r in u2["p"]["results"]] == [
            [{"sub_id": book["sub_id"], "rs": RS}],
            [{"sub_id": ticker["sub_id"], "rs": RS}],
        ]


@FLAGS
def test_ctl_and_unsub_name_their_stream_like_resync(
    backpressure: BackpressureConfig | None,
) -> None:
    """Gherkin (W10): a `ctl` or `unsub` with the envelope `rs` retunes or ends that replay stream
    alone, the live one unchanged; with no `rs`, each reaches the live one only (§5.3, §5.4), so
    with only a replay stream left a `ctl` gets `not_subscribed` and an `unsub` is a `noop`. An
    `rs` naming no stream: `not_subscribed` carrying it in lower case, or a `noop`."""
    w = World(backpressure=backpressure)
    with connect(w) as c:
        live, replay = _twins(c)
        c.send({"t": "ctl", "id": "k1", "ch": BOOK, "rs": RS.upper(), "p": {"paused": True}})
        c.send({"t": "ctl", "id": "k2", "ch": BOOK, "rs": OTHER_RS.upper(), "p": {"paused": True}})
        ok, missing = _fenced(c)
        assert (ok["p"]["sub_id"], ok["rs"], ok["p"]["effective"]["paused"]) == (replay, RS, True)
        assert (missing["p"]["code"], missing["ch"], missing["rs"]) == (
            ("not_subscribed", BOOK, OTHER_RS)
        )
        publish(w, "book", BOOK, replay=RS, ts_ms=1)  # the paused replay stream sends nothing
        publish(w, "book", BOOK)
        assert [(f["t"], f.get("rs"), f["s"]) for f in _fenced(c)] == [("d", None, 2)]
        for rid, rs in (("u1", OTHER_RS), ("u2", RS)):
            c.send({"t": "unsub", "id": rid, "rs": rs, "p": {"topics": [BOOK]}})
        noop, done = _fenced(c)
        assert noop["p"]["results"] == [{"ch": BOOK, "ok": True, "noop": True}]
        ended = [{"sub_id": replay, "rs": RS}]
        assert done["p"]["results"] == [{"ch": BOOK, "ok": True, "ended": ended}]
        w.clock.now += 0.1  # flag on: past the 50 ms window the first delta opened (§8.1)
        publish(w, "book", BOOK)
        assert [(f["t"], f.get("rs"), f["s"]) for f in _fenced(c)] == [("d", None, 3)]
        c.send({"t": "unsub", "id": "u3", "p": {"topics": [BOOK]}})
        (u3,) = _fenced(c)
        assert u3["p"]["results"] == [{"ch": BOOK, "ok": True, "ended": [{"sub_id": live}]}]
        _replay(c, BOOK)  # a replay stream of BOOK alone
        c.send({"t": "ctl", "id": "k3", "ch": BOOK, "p": {"throttle_ms": 500}})
        c.send({"t": "unsub", "id": "u4", "p": {"topics": [BOOK]}})
        answers = {f.get("id"): f for f in _fenced(c)}  # and the replay stream's first `snap`
        assert (answers["k3"]["p"]["code"], "rs" in answers["k3"]) == ("not_subscribed", False)
        assert answers["u4"]["p"]["results"] == [{"ch": BOOK, "ok": True, "noop": True}]


@pytest.mark.parametrize("spelling", list(NOT_UUIDS.values()), ids=list(NOT_UUIDS))
def test_an_rs_or_replay_session_id_in_another_spelling_is_refused(spelling: str) -> None:
    """§7.5: a uuid is the §13 `$defs/uuid` form (8-4-4-4-12 ASCII hex, either case). Any other
    spelling is refused where a request names a stream (`invalid_options`, `field` `rs`; an `unsub`
    whole) and in a `sub` (§5.2: per topic, `invalid_options`, `field` `replay_session_id`, and no
    `rs` on the result). Nothing echoes it, and nothing changes."""
    with connect(World()) as c:
        _twins(c)
        (result,) = _replay(c, TICKER, rs=spelling, conform=False)
        refused = (result["ok"], result["error"]["code"], result["error"]["field"], "rs" in result)
        assert refused == (False, "invalid_options", "replay_session_id", False)
        _resync(c, "y", conform=False, rs=spelling)
        ctl = {"t": "ctl", "id": "k", "ch": BOOK, "rs": spelling, "p": {"paused": True}}
        c.send(ctl, conform=False)
        c.send({"t": "unsub", "id": "u", "rs": spelling, "p": {"topics": [BOOK]}}, conform=False)
        answers = _fenced(c)
        assert [(f["id"], f["p"]["field"], f.get("ch"), "rs" in f) for f in answers] == [
            ("y", "rs", BOOK, False),
            ("k", "rs", BOOK, False),
            ("u", "rs", None, False),
        ]
        told = {(f["p"]["code"], f["p"]["message"]) for f in answers}
        assert (told, result["error"]["message"]) == (
            {("invalid_options", TOLD["rs"])},
            "replay_session_id must be a uuid.",
        )
        _all_left(c)  # both streams are still there, with all of their limits


def test_a_sub_id_or_rs_of_another_connection_never_resolves() -> None:
    """Security (IDOR): a request resolves among its own connection's subscriptions only. The `rs`
    and `sub_id`s of another connection of the same user reach nothing of it, even where this
    connection's own id is the same string; the answers name no subscription of it, and the other
    connection hears nothing."""
    w = World()
    with connect(w) as a:
        live, replay = _twins(a)
        with w.client.websocket_connect("/ws", subprotocols=current_offer()) as ws:
            b = Client(ws)
            b.open()
            assert b.sub(TRADES)["p"]["results"][0]["sub_id"] == live  # ids are per connection
            _fenced(b)
            names: list[dict[str, Any]] = [
                {"rs": RS},
                {"sub_id": live},
                {"sub_id": replay},
                {"rs": RS, "sub_id": replay},
            ]
            for i, fields in enumerate(names):
                _resync(b, f"b-{i}", **fields)
            b.send({"t": "ctl", "id": "k", "ch": BOOK, "rs": RS, "p": {"paused": True}})
            b.send({"t": "unsub", "id": "u", "rs": RS, "p": {"topics": [BOOK]}})
            *errs, k, u = _fenced(b)
            rs_of = [RS, None, None, RS]
            assert errs == [_err(f"b-{i}", "not_subscribed", rs_of[i]) for i in range(4)]
            assert (k["p"]["code"], u["p"]["results"][0].get("noop")) == ("not_subscribed", True)
        assert _fenced(a) == []
