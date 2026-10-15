"""E17-Q01 §16.4 contract, unit and integration rows (`23-ws-protocol.md` §16.4).

* every server frame validates against §13-§15 (the harness validates on receive; the matrix
  test below proves WHICH frame types were produced, so "validated" is not vacuous);
* binary/structured equivalence for all six CVWB body kinds, and a corrupted layout fails;
* error-catalogue closure (generated registry == the §10.2 column of the document);
* `heatmap_bucket_selection` (§6.1.1) and the server's `500` fallback;
* upstream `u` gap, token-expiry re-auth, replay seek integration rows;
* client -> server frames the server must reject.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import math
import sys
from typing import Any, Protocol, cast

import pytest
import yaml

from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.binary import FrameMalformedError, decode, decode_b64, encode, encode_b64
from candleviewer.ws.cvwb_vectors import structured, vector_frames
from candleviewer.ws.sequencing import UpstreamBookGuard
from candleviewer.ws.topics import FAMILIES, effective_options, parse_topic
from tests.contract.ws._harness import (
    MODES,
    OFFERS,
    PROTOCOL_DOC,
    SCHEMAS,
    SYM,
    World,
    check_schema,
    connect,
    entry,
    publish,
    structured_of,
    topic_fields,
    wire_error_codes,
)
from tests.unit.ws._seq_support import ACC_A, USER

RS = "bb000000-0000-4000-8000-000000000001"
_FRAMES = dict(vector_frames())
#: CVWB body kind -> (topic family, vector name carrying it)
_KINDS = {
    1: ("book", "book_snapshot"),
    2: ("book", "book_delta_extremes"),
    3: ("trades", "trades"),
    4: ("bars", "bars_v2"),
    5: ("footprint", "footprint"),
    6: ("heatmap", "heatmap_column"),
}


# -- every frame type the gateway can emit ------------------------------------------------------

#: Server -> client frame types, per the §13.1 envelope enum plus the one the gateway emits
#: outside it (`permission_change`, FINDING F3). `hello/auth/sub/unsub/ctl/resync` are client-only.
SERVER_TYPES = {
    "welcome", "auth_ok", "sub_ok", "unsub_ok", "ctl_ok", "snap", "d", "revoked", "ping",
    "pong", "err", "bye", "permission_change",
}  # fmt: skip


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_contract_every_server_frame_type_is_produced_and_validated_against_its_schema(
    offer: list[str],
) -> None:
    w = World()
    with connect(w, offer) as c:
        c.send({"t": "ping", "id": "p"})
        c.next_of("pong")
        c.sub("trades.BTCUSDT", {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        c.drain(2)
        publish(w, "trades", "trades.BTCUSDT")
        c.next_of("d")
        c.send({"t": "ctl", "id": "k", "ch": "trades.BTCUSDT", "p": {"throttle_ms": 200}})
        c.next_of("ctl_ok")
        c.send({"t": "unsub", "id": "u", "p": {"topics": ["trades.BTCUSDT"]}})
        c.next_of("unsub_ok")
        c.send({"t": "bogus"}, conform=False)
        c.next_of_raw("err")
        w.clock.now = 20.0
        c.recv(skip_ping=False)  # the unsolicited ping
        w.grants = (AccountGrant(ACC_A, False, False, False),)
        w.call(
            w.registry.grants_changed,
            USER,
        )
        c.recv_permission_change()
        c.next_of("revoked")
        w.call(w.revocation.revoke, w.session)
        c.bye_then_close()
    produced = {f["t"] for f in c.seen}
    assert SERVER_TYPES <= produced, f"never produced: {sorted(SERVER_TYPES - produced)}"
    assert produced <= SERVER_TYPES, f"unexpected frame types: {sorted(produced - SERVER_TYPES)}"


# -- binary / structured equivalence ------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_contract_cvwb_kind_decodes_and_its_structured_form_validates(kind: int) -> None:
    family, name = _KINDS[kind]
    frame = _FRAMES[name]
    assert frame.body_kind == kind
    body = {
        **topic_fields({"book": "book.BTCUSDT.50"}.get(family) or _topic(family)),
        **structured(decode(encode(frame))),
    }
    check_schema(f"cv://ws/v1/{family}.schema.json", body, f"kind {kind} ({name})")


def _topic(family: str) -> str:
    return {
        "trades": "trades.BTCUSDT",
        "bars": "bars.BTCUSDT.time.1",
        "footprint": "footprint.BTCUSDT.time.1",
        "heatmap": "heatmap.BTCUSDT",
    }[family]


def _corruptions(kind: int) -> list[Any]:
    """Layout corruptions every kind must reject. Trailing bytes are rejected only where §3.4/C10
    demand an exact length (bars, kind 4); other kinds are length-checked by their counts."""
    out = [
        lambda b: b.__setitem__(0, b[0] ^ 0xFF),  # magic
        lambda b: b.__setitem__(4, 99),  # unknown format_version
        lambda b: b.__setitem__(5, 99),  # unknown body_kind
        lambda b: b.__delitem__(slice(len(b) - 3, len(b))),  # truncated body
        lambda b: b.__delitem__(slice(20, len(b))),  # truncated inside the header
    ]
    if kind == 4:
        out.append(lambda b: b.extend(b"\x00"))
    return out


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_contract_a_corrupted_cvwb_layout_is_rejected_and_never_validates(kind: int) -> None:
    raw = bytes(encode(_FRAMES[_KINDS[kind][1]]))
    decode(raw)  # control: the pristine frame decodes
    for corrupt in _corruptions(kind):
        bad = bytearray(raw)
        corrupt(bad)
        with pytest.raises(FrameMalformedError):
            decode(bytes(bad))


def test_contract_a_corrupted_structured_twin_fails_schema_validation() -> None:
    twin = {**topic_fields("trades.BTCUSDT"), **structured(_FRAMES["trades"])}
    check_schema("cv://ws/v1/trades.schema.json", twin, "control")
    twin["trades"][0]["price"] = 100.5  # a JSON number, never a decimal string (§13 common)
    with pytest.raises(AssertionError, match="violates"):
        check_schema("cv://ws/v1/trades.schema.json", twin, "corrupted")


@pytest.mark.parametrize("family", ["trades", "bars", "footprint", "heatmap"])
def test_contract_binary_and_structured_snapshots_of_one_state_are_equivalent(family: str) -> None:
    """Same server state requested as `structured` and as `binary`: the binary body decoded and
    rendered must equal the structured payload (the §16.4 equivalence row, through the socket)."""
    w = World()
    seen = {}
    for mode in MODES:
        with connect(w) as c:
            e = entry(family, FAMILIES[family].shapes[0], mode)
            c.sub(e)
            seen[mode] = c.recv()
    structured_form = {k: v for k, v in seen["structured"]["p"].items() if k != "stale"}
    binary_form = structured_of(seen["binary"])
    assert seen["binary"]["e"] == "b64" and seen["structured"]["e"] == "j"
    assert binary_form == structured_form


def test_contract_b64_snapshot_parts_round_trip_byte_identical() -> None:
    w = World()
    with connect(w) as c:
        c.sub(entry("book", ("symbol", "depth"), "binary"))
        snap = c.recv()
    raw = base64.b64decode(snap["p"])
    assert encode(decode(raw)) == raw and encode_b64(decode_b64(snap["p"])) == snap["p"]


# -- error-catalogue closure --------------------------------------------------------------------


def test_contract_error_registry_equals_the_section_10_2_catalogue() -> None:
    doc = wire_error_codes()
    generated = {code.value for code in WS_ERROR_CODES}
    assert doc == generated, (sorted(doc ^ generated),)
    schema_codes = set(SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]["errorCode"]["enum"])
    assert doc <= schema_codes, sorted(doc - schema_codes)


def test_contract_every_bye_and_revoked_reason_is_in_its_closed_schema_set() -> None:
    from candleviewer.ws.lifecycle import CLOSE_REASONS, bye_frame
    from candleviewer.ws.revocation import _REVOKED_MESSAGES, revoked_frame

    for reason in sorted(CLOSE_REASONS):
        f = bye_frame(reason, now_ms=1)
        check_schema("cv://ws/v1/bye.schema.json", f["p"], f"bye {reason}")
    for reason in sorted(_REVOKED_MESSAGES):
        f = revoked_frame("positions", reason, now_ms=1)  # type: ignore[arg-type]  # str->Literal from the registry itself
        check_schema("cv://ws/v1/revoked.schema.json", f["p"], f"revoked {reason}")


# -- heatmap_bucket_selection (§6.1.1) ------------------------------------------------------------

_LADDER = (100, 250, 500, 1000, 5000)


def heatmap_bucket_ms(window_s: float, css_px: float, dpr: float) -> int:
    """The §6.1.1 reference algorithm, written from the document (there is no production
    implementation yet; the web client owns it, E21/E17-D03): ideal -> smallest rung >= ideal,
    then the normative upward clamp to 1000 ms whenever ideal_ms <= 2500."""
    ideal = (window_s * 1000) / (css_px * dpr / 3)
    rung = next((r for r in _LADDER if r >= ideal), _LADDER[-1])
    if rung == 5000 and ideal <= 2500:
        return 1000
    return rung


#: (display, pane CSS px, DPR, documented ideal_ms, documented selected) - the §6.1.1 table.
_TABLE = [
    ("4K 100%", 2380, 1.0, 1134, 1000),
    ("4K 150%", 1587, 1.5, 1134, 1000),
    ("2560x1440", 1587, 1.0, 1701, 1000),
    ("1920x1080", 1190, 1.0, 2269, 1000),
    ("MacBook 14in", 937, 2.0, 1441, 1000),
    ("half-width 1920", 595, 1.0, 4538, 5000),
]


@pytest.mark.parametrize(("display", "css", "dpr", "ideal", "selected"), _TABLE)
def test_heatmap_bucket_selection_matches_every_reference_row(
    display: str, css: int, dpr: float, ideal: int, selected: int
) -> None:
    computed = (900 * 1000) / (css * dpr / 3)
    assert math.floor(computed) == ideal or round(computed) == ideal, (display, computed)
    assert heatmap_bucket_ms(900, css, dpr) == selected, display


@pytest.mark.parametrize(
    ("ideal_ms", "expected"),
    [
        (2500, 1000),
        (2500.1, 5000),
        (1000, 1000),
        (1000.1, 1000),
        (500, 500),
        (50, 100),
        (6000, 5000),
    ],
)
def test_heatmap_bucket_selection_ladder_clamp_boundary(ideal_ms: float, expected: int) -> None:
    css = (900 * 1000) / ideal_ms * 3  # DPR 1 pane width that yields exactly `ideal_ms`
    assert heatmap_bucket_ms(900, css, 1.0) == expected


def test_heatmap_bucket_selection_server_applies_500_when_the_option_is_absent() -> None:
    eff = effective_options(parse_topic("heatmap.BTCUSDT"), {})
    assert eff["time_bucket_ms"] == 500  # §6.1.1 rule 3, real server code
    eff = effective_options(parse_topic("heatmap.BTCUSDT"), {"time_bucket_ms": 1000})
    assert eff["time_bucket_ms"] == 1000  # rule 1/2: an explicit value is never overridden


def test_heatmap_bucket_selection_server_accepts_exactly_the_ladder_rungs() -> None:
    w = World()
    with connect(w) as c:
        for i, rung in enumerate(_LADDER):
            ch = f"heatmap.{'BTCUSDT' if i == 0 else 'ETHUSDT'}"
            if i:
                w.source.bodies["heatmap"] = w.source.bodies["heatmap"]
            res = c.sub({"ch": ch, "opts": {"time_bucket_ms": rung}})["p"]["results"][0]
            if i == 0:
                assert res["ok"] and res["effective"]["time_bucket_ms"] == rung
                break
        res = c.sub({"ch": "heatmap.SOLUSDT", "opts": {"time_bucket_ms": 750}}, conform=False)["p"][
            "results"
        ][0]
        assert res["error"]["code"] == "invalid_options"


# -- integration rows ---------------------------------------------------------------------------


def test_integration_upstream_u_gap_produces_snap_with_reason_upstream_desync() -> None:
    w = World()
    guard = UpstreamBookGuard()
    with connect(w) as c:
        c.sub("book.BTCUSDT.50")
        c.drain(1)
        assert guard.observe(SYM, 10, snapshot=True) == "apply"
        assert guard.observe(SYM, 11, snapshot=False) == "apply"
        publish(w, "book", "book.BTCUSDT.50")
        assert c.recv()["s"] == 2
        verdict = guard.observe(SYM, 13, snapshot=False)  # u 12 never arrived
        assert verdict == "desync"
        assert w.call(w.hub.upstream_desync, SYM) == 1
        snap = c.recv()
        assert snap["t"] == "snap" and snap["s"] == 3  # no delta crossed the gap, no reuse
        assert snap["meta"] == {"reason": "upstream_desync", "source": "live", "previous_seq": 2}
        assert guard.observe(SYM, 14, snapshot=False) == "drop"  # held until the rebuild
        publish(w, "book", "book.BTCUSDT.50")
        assert c.recv()["s"] == 4


@pytest.mark.xfail(
    strict=True,
    reason="#2517: ctl paused:false sends no resnapshot and drops the paused updates; "
    "fixed by #2556 (remove this marker when it merges)",
)
def test_integration_ctl_pause_resume_resnapshots_with_the_paused_updates() -> None:
    """Scenario S1 (#409): resuming a paused book yields `ctl_ok resnapshot:true`, then a
    `snap reason:reconfigure` holding the paused updates, before any `d`; next `d` is `snap.s+1`."""
    w = World()
    ch = "book.BTCUSDT.50"
    with connect(w) as c:
        c.sub(ch)
        n = c.recv()["s"]
        c.send({"t": "ctl", "id": "p1", "ch": ch, "p": {"paused": True}})
        assert "resnapshot" not in c.next_of("ctl_ok")["p"]
        w.source.books[SYM].apply([["99.5", "7.000"]], [["101.5", "8.000"]])  # producer moves on
        assert publish(w, "book", ch) == 0  # paused: no d crosses
        assert publish(w, "book", ch) == 0
        c.send({"t": "ctl", "id": "p2", "ch": ch, "p": {"paused": False}})
        assert c.next_of("ctl_ok")["p"]["resnapshot"] is True
        snap = c.recv()
        assert snap["t"] == "snap" and snap["meta"]["reason"] == "reconfigure"
        assert snap["s"] > n
        assert ["99.5", "7.000"] in structured_of(snap)["bids"]  # the paused update is inside
        publish(w, "book", ch)
        d = c.recv()
        assert d["t"] == "d" and d["s"] == snap["s"] + 1


def test_integration_token_expiry_reauth_in_place_preserves_subscriptions_and_sequences() -> None:
    w = World()
    with connect(w) as c:
        c.sub("trades.BTCUSDT", {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        c.drain(2)
        publish(w, "trades", "trades.BTCUSDT")
        assert c.recv()["s"] == 2
        w.advance(c, 540.0)  # the client refreshes 60 s before expiry
        c.send({"t": "auth", "id": "re", "p": {"access_token": "good-" + "z" * 20}})
        ok = c.next_of("auth_ok")
        assert ok["id"] == "re" and ok["p"]["token_expires_at_ms"] == w.clock.wall_ms() + 600_000
        publish(w, "trades", "trades.BTCUSDT")
        d = c.recv()
        assert (d["t"], d["s"]) == ("d", 3)  # no snap, no new sub_ok; the sequence continued
        w.advance(c, 700.0)  # past the FIRST token's expiry, inside the second
        publish(w, "orders", "orders", account=ACC_A)
        assert (c.recv()["ch"]) == "orders"


def test_integration_without_reauth_an_expired_token_closes_with_bye_4401() -> None:
    w = World()
    with connect(w) as c:
        c.sub("trades.BTCUSDT")
        c.drain(1)
        w.clock.now = float(w.token_ttl_s)
        bye, code = c.bye_then_close()
        assert (bye["p"]["reason"], code) == ("token_expired", 4401)


def test_integration_replay_subscribe_and_seek_emit_the_documented_series() -> None:
    """§11 up to the seek, on a stubbed replay clock: `sub_ok`, `snap` (replay/initial), recorded
    `d`s, then `snap` reason `replay_seek` with the sequence continuing. Reaching `to` (the
    `revoked replay_session_ended` series) needs the E26 session service: see the plan, PENDING."""
    w = World()
    topics = [entry("trades", ("symbol",)), entry("ticker", ("symbol",))]
    with connect(w) as c:
        c.send({"t": "sub", "id": "r", "p": {"topics": topics, "replay_session_id": RS}})
        assert [r["ok"] for r in c.next_of("sub_ok")["p"]["results"]] == [True, True]
        snaps = c.drain(2)
        assert [(f["meta"]["reason"], f["meta"]["source"], f["s"]) for f in snaps] == [
            ("initial", "replay", 1)
        ] * 2
        for tick in (1000, 2000, 3000):
            publish(w, "trades", topics[0]["ch"], replay=RS, ts_ms=tick)
        ds = c.drain(3)
        assert [(d["s"], d["ts"], d["rs"]) for d in ds] == [
            (2, 1000, RS),
            (3, 2000, RS),
            (4, 3000, RS),
        ]
        assert w.call(w.hub.replay_seek, RS) == 2
        seek = c.drain(2)
        assert {f["meta"]["reason"] for f in seek} == {"replay_seek"}
        assert {f["ch"]: f["s"] for f in seek} == {"trades.BTCUSDT": 5, "ticker.BTCUSDT": 2}


class _ReplayHub(Protocol):
    """The hook E26-T05 (#628) is expected to add to `SequencingHub`; typed here so no `noqa` or
    `getattr` is needed. Until it lands, attribute access raises `AttributeError` (the xfail)."""

    def replay_finished(self, replay_session_id: str) -> int: ...


@pytest.mark.xfail(
    strict=True,
    reason="E26-T05: replay clock not yet implemented; no code ends a replay session on a "
    "socket, so the documented `revoked replay_session_ended` series cannot be produced",
)
def test_integration_replay_finish_emits_revoked_replay_session_ended_per_topic() -> None:
    """§11: reaching `to` emits one `revoked replay_session_ended` per replayed topic."""
    w = World()
    topics = [entry("trades", ("symbol",)), entry("ticker", ("symbol",))]
    with connect(w) as c:
        c.send({"t": "sub", "id": "r", "p": {"topics": topics, "replay_session_id": RS}})
        c.next_of("sub_ok")
        c.drain(2)
        finish = cast(_ReplayHub, w.hub).replay_finished  # E26-T05 (#628) adds it; absent today
        w.call(finish, RS)
        revoked = c.drain(2)
        assert {f["ch"] for f in revoked} == {"trades.BTCUSDT", "ticker.BTCUSDT"}
        assert {f["p"]["reason"] for f in revoked} == {"replay_session_ended"}


def test_integration_replay_end_revoked_frame_shape_is_schema_valid() -> None:
    """The frame §11 says closes a finished session, built by the real authz path. How it is
    triggered (E26) is out of reach today; its shape is not."""
    w = World()
    with connect(w) as c:
        c.send(
            {
                "t": "sub",
                "id": "r",
                "p": {"topics": [entry("trades", ("symbol",))], "replay_session_id": RS},
            }
        )
        c.next_of("sub_ok")
        c.drain(1)
        frame = w.call(_end_replay, w, RS)
        check_schema("cv://ws/v1/revoked.schema.json", frame["p"], "replay_session_ended")
        assert frame["p"]["reason"] == "replay_session_ended"


async def _end_replay(w: World, rs: str) -> dict[str, Any]:
    authz, _send, _close = w.registry._conns[next(iter(w.registry._conns))][0]
    sub = authz.find("trades.BTCUSDT", rs)
    assert sub is not None
    return authz.revoke(sub, "replay_session_ended", w.clock.wall_ms())


# -- client -> server frames the server must reject ---------------------------------------------

_BAD_CLIENT_FRAMES = [
    pytest.param({"no_type": 1}, "frame_malformed", id="missing-t"),
    pytest.param({"t": 7}, "frame_malformed", id="t-not-string"),
    pytest.param({"t": "bogus", "id": "x"}, "frame_malformed", id="unknown-t"),
    pytest.param([1, 2], "frame_malformed", id="array-not-object"),
    pytest.param("just a string", "frame_malformed", id="json-string"),
    *[
        pytest.param({"t": t, "id": "x"}, "frame_malformed", id=f"server-only-{t}")
        for t in (
            "welcome",
            "auth_ok",
            "sub_ok",
            "unsub_ok",
            "ctl_ok",
            "snap",
            "d",
            "revoked",
            "bye",
            "err",
        )
    ],
    pytest.param({"t": "resync", "id": "r"}, "frame_malformed", id="resync-no-ch"),
    pytest.param(
        {"t": "resync", "id": "r", "ch": "trades.BTCUSDT", "p": {"reason": "nope"}},
        "frame_malformed",
        id="resync-bad-reason",
    ),
    pytest.param(
        {"t": "resync", "id": "r", "ch": "trades.BTCUSDT", "p": {"reason": "manual"}},
        "not_subscribed",
        id="resync-unsubscribed",
    ),
    pytest.param(
        {"t": "ctl", "id": "k", "ch": "trades.BTCUSDT", "p": {"throttle_ms": 9}},
        "not_subscribed",
        id="ctl-unsubscribed",
    ),
    pytest.param({"t": "hello", "id": "again"}, "protocol_violation", id="second-hello"),
]


@pytest.mark.parametrize(("bad", "code"), _BAD_CLIENT_FRAMES)
def test_client_frames_the_server_must_reject_are_err_in_the_catalogue_and_non_fatal(
    bad: Any, code: str
) -> None:
    w = World()
    with connect(w) as c:
        c.send(bad, conform=False) if isinstance(bad, dict) else c.send_text(json.dumps(bad))
        err = c.recv_err()
        assert err["p"]["code"] == code
        assert err["p"]["code"] in wire_error_codes()
        assert "close" not in err["p"] or err["p"]["close"] is False
        c.send({"t": "ping", "id": "alive"})
        assert c.next_of("pong")["id"] == "alive"  # one strike is not fatal


@pytest.mark.parametrize("payload", ["not json", "{", "\x00\x01", '{"t":"ping"'])
def test_client_non_json_text_is_frame_malformed_not_a_crash(payload: str) -> None:
    w = World()
    with connect(w) as c:
        c.send_text(payload)
        assert c.recv_err()["p"]["code"] == "frame_malformed"


def test_client_deeply_nested_frame_is_a_violation_never_decoded() -> None:
    w = World()
    with connect(w) as c:
        c.send_text('{"t":"ping","p":' + "[" * 40 + "]" * 40 + "}")
        assert c.recv_err()["p"]["code"] == "frame_malformed"


def test_client_binary_ws_frame_is_malformed_not_a_crash() -> None:
    w = World()
    with connect(w) as c:
        c.ws.send_bytes(b"\x00\xff\xfe")
        assert c.recv_err()["p"]["code"] == "frame_malformed"


def test_client_three_strikes_close_with_bye_4400() -> None:
    w = World()
    with connect(w) as c:
        for _ in range(3):
            c.send({"t": "bogus"}, conform=False)
        bye, code = c.bye_then_close()
        assert (bye["p"]["reason"], code) == ("bad_client", 4400)


def test_client_frames_before_hello_close_with_bye_1002() -> None:
    w = World()
    with connect(w, handshake=False) as c:
        c.send({"t": "ping", "id": "p"})
        assert c.bye_then_close()[1] == 1002


def test_client_every_private_topic_requires_an_account_in_scope() -> None:
    """Raw-frame variant of the cross-account matrix (adversarial half is E17-X02)."""
    w = World()
    with connect(w) as c:
        for fam in ("orders", "positions", "executions", "wallet", "trade_groups"):
            res = c.sub({"ch": fam})["p"]["results"][0]  # no accounts at all
            assert res["ok"] is False and res["error"]["code"] in wire_error_codes()


def test_client_snapshot_and_replay_fields_are_type_checked() -> None:
    w = World()
    with connect(w) as c:
        for p in (
            {"snapshot": "yes"},
            {"replay_session_id": 5},
            {"replay_session_id": "not-a-uuid"},
        ):
            res = c.sub("trades.BTCUSDT", conform=False, **p)["p"]["results"][0]
            assert (res["ok"], res["error"]["code"]) == (False, "invalid_options")


# -- §16.4 unit rows owned elsewhere ------------------------------------------------------------
# "Coalescer produces state identical to applying every source update" (§8.2): E17-T03.
# "Book delta application incl. size-0 deletes and depth-window eviction" (§7.3): E17-S03, covered
# by tests/unit/ws/test_sequencing.py and test_sequencing_dod.py (10 000 seeded deltas). Listed in
# the PR's Partial; not duplicated here.

# -- §16.4 `ws_message_schemas` and `error_registry_single_source` ------------------------------

_REPO = PROTOCOL_DOC.parents[2]


def _gate() -> Any:
    """The blocking gate `tools/contracts/validate_ws_schemas.py`, imported (not re-implemented)."""
    spec = importlib.util.spec_from_file_location(
        "validate_ws_schemas", _REPO / "tools" / "contracts" / "validate_ws_schemas.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_ws_schemas"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_contract_ws_message_schemas_meta_validate_and_every_ref_resolves() -> None:
    errors = _gate().check_schemas(SCHEMAS)
    assert errors == [], errors[:5]


def test_contract_every_section_12_example_frame_validates_against_its_schema() -> None:
    gate = _gate()
    errors, count = gate.check_examples(SCHEMAS, PROTOCOL_DOC.read_text(encoding="utf-8"))
    assert errors == [], errors[:5]
    assert count >= 30  # a parser that finds nothing must not pass


def test_contract_error_registry_matches_openapi_x_error_codes_ws() -> None:
    """§16.4: the §10.2 codes == `x-error-codes-ws` + the dual-surface `x-error-codes` entries."""
    spec = yaml.safe_load((_REPO / "docs" / "plan" / "22-api-openapi.yaml").read_text("utf-8"))
    ws_only = {e["code"] for e in spec["x-error-codes-ws"]}
    dual = {e["code"] for e in spec["x-error-codes"] if "ws" in (e.get("surface") or ())}
    assert wire_error_codes() == ws_only | dual
    assert len(dual) == 6  # the six dual-surface codes the document names
