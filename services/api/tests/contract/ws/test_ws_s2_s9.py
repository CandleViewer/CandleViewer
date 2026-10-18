"""E17-Q01: one named test per normative server requirement S1-S13 (`23-ws-protocol.md` §16.1).

Every test drives the REAL gateway (`make_ws_router`, `ConnectionRegistry`, `SequencingHub`,
`TopicEmitter`) through a socket and validates every received frame against the §13-§15 schemas
(`_harness.validate_frame`). Test names start `test_sN_` so the coverage matrix in
`conftest.py` can report which requirements ran.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.binary import FLAG_ESTIMATED, FLAG_REPLAY
from candleviewer.ws.sequencing import TopicEmitter, causal_sort
from candleviewer.ws.topics import FAMILIES
from tests.contract.ws._harness import (
    ACCOUNTLESS_PRIVATE,
    MODES,
    OFFERS,
    PRIVATE_ORDER,
    SCHEMAS,
    SYM,
    World,
    all_private,
    assert_contiguous,
    connect,
    cvwb_part,
    delta_body,
    entry,
    publish,
    structured_of,
    validate_frame,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER

RS = "bb000000-0000-4000-8000-000000000001"
_ROWS = [
    pytest.param(f.family, shape, id=".".join((f.family, *shape)))
    for f in FAMILIES.values()
    for shape in f.shapes
    if f.family != "system"  # implicit, never a Subscription (§6.2); see S2 note in the plan
]
# -- S2 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("family", "shape"), _ROWS)
def test_s2_snap_precedes_any_delta_on_every_topic_row(
    family: str, shape: tuple[str, ...], mode: str
) -> None:
    """Parameterised over the topic registry (`FAMILIES`): a topic added later is covered."""
    w = World()
    e = entry(family, shape, mode)
    with connect(w) as c:
        assert c.sub(e)["p"]["results"][0]["ok"], e
        snap = c.recv()
        assert (snap["t"], snap["s"], snap["meta"]["reason"]) == ("snap", 1, "initial")
        assert publish(w, family, e["ch"], mode) == 1
        d = c.recv()
        assert (d["t"], d["ch"], d["s"]) == ("d", e["ch"], 2)
        # whatever the encoding, the body validated against its §14/§15 schema in `recv`
        assert structured_of(d) is not None


def test_s2_delta_is_suppressed_while_the_snapshot_cannot_be_built() -> None:
    w = World()
    w.source.unavailable.add(SYM)  # book engine still rebuilding
    with connect(w) as c:
        res = c.sub("book.BTCUSDT.50")["p"]["results"][0]
        assert res["ok"] and res["snapshot_pending"] is True
        assert publish(w, "book", "book.BTCUSDT.50", "structured") == 0  # no d crosses the gap
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # nothing but the pong arrived
        w.source.unavailable.clear()
        assert w.call(w.hub.flush_pending) == 1
        snap = c.recv()
        assert (snap["t"], snap["s"]) == ("snap", 1)


def test_s2_a_pending_machines_subscription_waits_for_a_publish_not_an_inbound_frame() -> None:
    """§6.4: no inbound frame retries it; the first publish on its topic wakes it."""
    w, ch = World(), "machines.kill_switch.state"
    w.source.unavailable.add("")  # no state yet for this symbol-less entity
    with connect(w) as c:
        assert c.sub(ch)["p"]["results"][0]["snapshot_pending"] is True
        w.source.unavailable.clear()
        c.sub("book.BTCUSDT.50")
        assert c.recv()["ch"] == "book.BTCUSDT.50"  # that topic's `snap`, and no machine one
        c.send({"t": "ctl", "id": "c", "ch": "book.BTCUSDT.50", "p": {"throttle_ms": 250}})
        assert c.recv()["t"] == "ctl_ok"  # a `ctl` retries no pending machines subscription either
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"
        assert w.call(lambda: w.hub.publish(ch, delta_body("machines"), wake=True)) == 1
        snap = c.recv()
        assert (snap["t"], snap["ch"], snap["meta"]["reason"]) == ("snap", ch, "initial")


def test_s2_a_resumed_machines_subscription_is_snapped_at_once() -> None:
    """A `ctl` that makes a `machines` subscription pending is answered with its `snap`."""
    w, ch = World(), "machines.kill_switch.state"
    with connect(w) as c:
        c.sub(ch)
        assert c.recv()["t"] == "snap"
        for paused in (True, False):
            c.send({"t": "ctl", "id": "c", "ch": ch, "p": {"paused": paused}})
            assert c.recv()["t"] == "ctl_ok"
        snap = c.recv()
        assert (snap["t"], snap["meta"]["reason"]) == ("snap", "reconfigure")


def test_s2_snapshot_false_attaches_to_deltas_only_when_continuity_is_provable() -> None:
    w = World()
    w.source.covered_from_ts = 1_789_132_000_000
    with connect(w) as c:
        ok = {"ch": "book.BTCUSDT.50", "opts": {"from_seq": 0, "from_ts_ms": 1_789_132_000_001}}
        res = c.sub(ok, snapshot=False)["p"]["results"][0]
        assert res["snapshot_pending"] is False and "snapshot_forced" not in res
        publish(w, "book", "book.BTCUSDT.50", "structured")
        assert c.recv()["t"] == "d"  # accepted `snapshot:false`: no snap owed


def test_s2_snapshot_false_without_continuity_is_forced_to_snap_first() -> None:
    w = World()
    w.source.covered_from_ts = 1_789_132_000_000
    with connect(w) as c:
        gap = {"ch": "book.BTCUSDT.50", "opts": {"from_seq": 0, "from_ts_ms": 1_789_000_000_000}}
        res = c.sub(gap, snapshot=False)["p"]["results"][0]
        assert res["snapshot_forced"] is True and res["snapshot_pending"] is True
        assert c.recv()["t"] == "snap"


# -- S3 ----------------------------------------------------------------------------------------


def _s3_scenario(w: World, offer: list[str] | None = None) -> list[dict[str, Any]]:
    """Concurrent writers on several topics plus resync/reconfigure re-snapshots mid-stream."""
    a, b = "trades.BTCUSDT", "ticker.BTCUSDT"
    with connect(w, offer) as c:
        c.sub({"ch": a}, {"ch": b}, {"ch": "heatmap.BTCUSDT"})
        c.drain(3)

        def writer(args: tuple[str, str]) -> None:
            fam, ch = args
            for _ in range(20):
                publish(w, fam, ch, "structured")

        jobs = [("trades", a), ("ticker", b)] * 4
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, jobs))
        c.send({"t": "resync", "id": "r", "ch": a, "p": {"reason": "manual"}})
        c.send({"t": "ctl", "id": "k", "ch": "heatmap.BTCUSDT", "p": {"time_bucket_ms": 1000}})
        publish(w, "trades", a, "structured")
        c.send({"t": "ping", "id": "fence"})
        while c.recv()["t"] != "pong":
            pass
        return list(c.seen)


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_s3_sequence_increments_by_exactly_one_per_topic_under_concurrent_writes(
    offer: list[str],
) -> None:
    frames = _s3_scenario(World(), offer)
    assert_contiguous(frames)
    by_topic: dict[str, list[int]] = {}
    for f in frames:
        if f["t"] in {"snap", "d"}:
            by_topic.setdefault(f["ch"], []).append(f["s"])
    assert len(by_topic["trades.BTCUSDT"]) == 1 + 80 + 1 + 1  # snap, 80 d, resync snap, last d
    assert by_topic["ticker.BTCUSDT"] == list(range(1, 82))
    assert by_topic["heatmap.BTCUSDT"] == [1, 2]  # reconfigure snap continues the domain


def test_s3_sequence_survives_resync_and_reconfigure_without_reuse() -> None:
    frames = _s3_scenario(World())
    snaps = [f for f in frames if f["t"] == "snap" and f["meta"]["reason"] != "initial"]
    assert {f["meta"]["reason"] for f in snaps} == {"client_resync", "reconfigure"}
    assert all(f["meta"]["previous_seq"] == f["s"] - 1 for f in snaps)


def test_s3_mutation_a_skipped_sequence_number_fails_the_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC "the suite catches a real regression": the generator is deliberately changed to skip a
    number under concurrency; the S3 oracle must fail on it."""
    real = TopicEmitter.delta
    calls = {"n": 0}

    def skipping(self: TopicEmitter, sub: Any, *a: Any, **k: Any) -> bool:
        calls["n"] += 1
        if calls["n"] % 7 == 0:
            sub.seq += 1  # skip one
        return real(self, sub, *a, **k)

    monkeypatch.setattr(TopicEmitter, "delta", skipping)
    with pytest.raises(AssertionError, match="skipped or reused"):
        assert_contiguous(_s3_scenario(World()))


def test_s3_mutation_a_reused_sequence_number_fails_the_oracle() -> None:
    frames = [
        {"t": "snap", "ch": "x", "s": 1},
        {"t": "d", "ch": "x", "s": 2},
        {"t": "d", "ch": "x", "s": 2},
    ]
    with pytest.raises(AssertionError, match="skipped or reused"):
        assert_contiguous(frames)


@pytest.mark.parametrize("family", sorted(ACCOUNTLESS_PRIVATE))
def test_s2_f5_delta_reaches_alerts_and_recorder_subscriptions(family: str) -> None:
    w = World()
    with connect(w) as c:
        c.sub({"ch": family})
        c.recv()
        assert publish(w, family, family) == 1
        assert c.recv()["t"] == "d"


# -- S4 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["orders", "executions"])
def test_s4_orders_and_executions_are_never_coalesced_or_throttled(family: str) -> None:
    w = World()
    asked = {"exchange_account_ids": [str(ACC_A)], "throttle_ms": 60_000, "coalesce": True}
    with connect(w) as c:
        eff = c.sub({"ch": family, "opts": asked})["p"]["results"][0]["effective"]
        assert eff["throttle_ms"] == 0 and eff["coalesce"] is False  # client request overridden
        c.next_of("snap")
        c.send({"t": "ctl", "id": "k", "ch": family, "p": {"throttle_ms": 5000, "coalesce": True}})
        ctl = c.next_of("ctl_ok")
        assert ctl["p"]["effective"]["throttle_ms"] == 0
        for _ in range(60):  # a burst: every update must be delivered individually
            assert publish(w, family, family, "structured") == 1
        frames = [c.recv() for _ in range(60)]
        assert [f["s"] for f in frames] == list(range(2, 62))
        assert not any("coalesced" in f["p"] or "coalesced_count" in f["p"] for f in frames)


@pytest.mark.parametrize("backpressure", [None, BackpressureConfig()], ids=["flag_off", "flag_on"])
def test_s4_coalescable_topics_do_mark_coalesced_deltas(
    backpressure: BackpressureConfig | None,
) -> None:
    """Control for S4: coalescing exists on market data and is flagged, so its absence on
    orders/executions above is a real property and not an artefact of the harness. With the flag
    on (#3268) the producer's own count goes through its window: the update leaves at once (the
    leading edge, D12) with the same frame as with the flag off."""
    w = World(backpressure=backpressure)
    with connect(w) as c:
        c.sub({"ch": "bars.BTCUSDT.time.1", "opts": {"encoding": "structured"}})
        c.recv()
        publish(w, "bars", "bars.BTCUSDT.time.1", "structured", coalesced_count=4)
        d = c.recv()
        assert d["p"]["coalesced"] is True and d["p"]["coalesced_count"] == 4
        assert d["s"] == 2  # a coalesced delta consumes exactly one sequence number


# -- S5 ----------------------------------------------------------------------------------------


def test_s5_private_frames_for_one_account_event_arrive_in_causal_order() -> None:
    w = World()
    with connect(w) as c:
        all_private(c, "trade_groups", "positions", "orders", "executions")
        scrambled = [
            ("trade_groups", delta_body("trade_groups")),
            ("positions", delta_body("positions")),
            ("orders", delta_body("orders")),
            ("executions", delta_body("executions")),
        ]
        sent = w.call(w.hub.publish_private, ACC_A, scrambled)
        assert sent == 4
        assert [c.recv()["ch"] for _ in range(4)] == PRIVATE_ORDER
        # a second event keeps the order, and sequence numbers stay per topic
        w.call(w.hub.publish_private, ACC_A, list(reversed(scrambled)))
        second = c.drain(4)
        assert [f["ch"] for f in second] == PRIVATE_ORDER and {f["s"] for f in second} == {3}


def test_s5_causal_sort_is_stable_and_leaves_other_topics_after_the_chain() -> None:
    items = [("x.a", 1), ("trade_groups", 2), ("orders", 3), ("x.b", 4), ("executions", 5)]
    assert [k for k, _ in causal_sort(items)] == [
        "executions",
        "orders",
        "trade_groups",
        "x.a",
        "x.b",
    ]


def test_s5_events_for_another_account_never_reach_this_subscription() -> None:
    w = World()
    with connect(w) as c:
        all_private(c, "orders")
        w.call(w.hub.publish_private, ACC_B, [("orders", delta_body("orders"))])
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # nothing was delivered before the pong


# -- S6 ----------------------------------------------------------------------------------------


#: §16.2 / §8.4: the SPEC's outbound budget (not the flag-off gateway's constant, 1 024: #2410).
SPEC_QUEUE_FRAMES = 2_000


def _flood(w: World, family: str, ch: str, n: int) -> int:
    body = delta_body(family)
    return int(w.call(lambda: sum(w.hub.publish(ch, body, account=ACC_A) for _ in range(n))))


@pytest.mark.parametrize("backpressure", [None, BackpressureConfig()], ids=["flag_off", "flag_on"])
def test_s6_orders_overflow_is_bounded_by_the_spec_budget_then_slow_consumer_4429(
    backpressure: BackpressureConfig | None,
) -> None:
    """§8.4 step 3: `orders` cannot be dropped, so on overflow the socket is closed with
    `bye slow_consumer` / 4429. Bound asserted against the SPEC budget (2 000 frames), produced in
    one event-loop turn so the writer cannot drain. Memory itself is E17-Q02. With the flag on
    (#412) the `orders` snapshot follows its `sub_ok` on the priority lane (§8.4 Lanes)."""
    w = World(backpressure=backpressure)
    with connect(w) as c:
        all_private(c, "orders")
        # Flag on, nothing is taken after the close (WS-D01): the update over budget is the last.
        taken = SPEC_QUEUE_FRAMES + (500 if backpressure is None else 1)
        assert _flood(w, "orders", "orders", SPEC_QUEUE_FRAMES + 500) == taken
        deltas = 0
        while (f := c.recv())["t"] != "bye":
            deltas += f["t"] == "d"
        assert deltas <= SPEC_QUEUE_FRAMES  # no growth path past the budget
        assert (f["p"]["reason"], f["p"]["code"]) == ("slow_consumer", 4429)
        assert c.closed() == 4429


def test_s6_coalescable_overflow_gets_backpressure_snap_and_no_close() -> None:
    """§8.4 steps 1-2 (#2409, with `CV_WS_BACKPRESSURE_ENABLED` on): a coalescable topic over
    budget is dropped and re-snapshotted with `reason: "backpressure"`; the socket is NOT closed
    (only orders/executions close it), so a `ping` still gets its `pong`."""
    w = World(backpressure=BackpressureConfig())
    with connect(w) as c:
        c.sub({"ch": "trades.BTCUSDT"})
        c.drain(1)
        from candleviewer.ws.coalescing import MAX_PENDING_ITEMS  # the bound this burst overflows

        n = MAX_PENDING_ITEMS + 2
        body = delta_body("trades")
        w.call(lambda: [w.hub.publish("trades.BTCUSDT", body) for _ in range(n)])
        seen: list[dict[str, Any]] = []
        while (f := c.recv(validate=False))["t"] != "bye" and len(seen) < n + 5:
            seen.append(f)
            if f["t"] == "snap" and f["meta"]["reason"] == "backpressure":
                validate_frame(f)
                c.send({"t": "ping", "id": "p"})
                assert c.next_of("pong")["id"] == "p"
                return
        raise AssertionError("no `snap reason:backpressure`; got a close or no snapshot")


def test_s6_coalescable_topic_is_not_cut_below_the_spec_budget() -> None:
    """§16.2 (#2410, with `CV_WS_BACKPRESSURE_ENABLED` on): up to 2 000 queued frames are
    legitimate; a burst of exactly that must all arrive."""
    w = World(backpressure=BackpressureConfig())
    with connect(w) as c:
        c.sub({"ch": "trades.BTCUSDT"})
        c.drain(1)
        body = delta_body("trades")
        w.call(lambda: [w.hub.publish("trades.BTCUSDT", body) for _ in range(SPEC_QUEUE_FRAMES)])
        w.clock.now += 0.1  # paced (§8.1): the prints after the first leave as one batch
        got = [len(c.recv(validate=False)["p"]["trades"]) for _ in range(2)]
        assert got == [1, SPEC_QUEUE_FRAMES - 1]


# -- S7 ----------------------------------------------------------------------------------------


def test_s7_grant_withdrawal_emits_revoked_and_other_topics_continue() -> None:
    w = World()
    with connect(w) as c:
        res = c.sub(
            {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}},
            {"ch": "trades.BTCUSDT"},
            {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}},
        )
        assert all(r["ok"] for r in res["p"]["results"])
        c.drain(3)
        w.grants = (AccountGrant(ACC_A, True, False, False),)
        w.call(w.registry.grants_changed, USER)
        revoked = c.next_validated("revoked")  # no assumption about other frames before it
        assert (revoked["ch"], revoked["p"]["reason"]) == ("positions", "account_scope_changed")
        assert revoked["p"]["removed_accounts"] == [str(ACC_B)]
        assert revoked["p"]["resubscribe_allowed"] is True  # scope narrowed, account A kept
        publish(w, "trades", "trades.BTCUSDT", "structured")
        publish(w, "orders", "orders", "structured", account=ACC_A)
        assert [(f["ch"], f["s"]) for f in c.drain(2)] == [("trades.BTCUSDT", 2), ("orders", 2)]


#: §16.4 (S7, §9.5): a grant change reaches the socket as `revoked` within this many real seconds.
REVOKE_BUDGET_S = 1.0


@pytest.mark.perf  # a wall-clock budget (C-13.9): the `py-perf` job and the contract job run it
def test_s7_grant_withdrawal_revoked_arrives_within_1s() -> None:
    """The fake clock is never advanced, so only real time sees a delayed revocation. Best of 3
    damps scheduler noise; the frame is validated after the timed span, not inside it."""
    delays: list[float] = []
    frames: list[dict[str, Any]] = []
    for _ in range(3):
        w = World()
        with connect(w) as c:
            c.sub({"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}})
            c.drain(1)
            w.grants = (AccountGrant(ACC_A, True, False, False),)
            t0 = time.monotonic()
            w.call(w.registry.grants_changed, USER)
            frames.append(c.next_of_raw("revoked"))
            delays.append(time.monotonic() - t0)
    for frame in frames:
        validate_frame(frame)
    assert min(delays) < REVOKE_BUDGET_S, delays


def test_s7_permission_loss_revokes_every_topic_of_that_family_only() -> None:
    w = World()
    with connect(w) as c:
        c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}}, "trades.BTCUSDT")
        c.drain(2)
        w.perms = frozenset({Permission.MARKETDATA_READ})
        w.call(w.registry.roles_changed, USER)
        revoked = c.next_validated("revoked")
        assert (revoked["ch"], revoked["p"]["reason"]) == ("orders", "permission_revoked")
        assert revoked["p"]["resubscribe_allowed"] is False
        publish(w, "trades", "trades.BTCUSDT", "structured")
        assert c.recv()["ch"] == "trades.BTCUSDT"


def test_s7_in_place_reauth_with_narrower_permissions_revokes_affected_topics() -> None:
    w = World()
    with connect(w) as c:
        c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        c.drain(1)
        w.perms = frozenset({Permission.MARKETDATA_READ})
        c.send({"t": "auth", "id": "a2", "p": {"access_token": "good-" + "y" * 20}})
        assert c.recv()["t"] == "auth_ok"
        assert c.next_validated("revoked")["ch"] == "orders"


def test_s7_session_revocation_closes_the_socket_with_bye_4401() -> None:
    w = World()
    with connect(w) as c:
        c.sub("trades.BTCUSDT")
        c.drain(1)
        assert w.call(w.revocation.revoke, w.session) == 1
        bye, code = c.bye_then_close()
        assert (bye["p"]["reason"], code) == ("session_revoked", 4401)


def test_s7_user_disabled_sends_bye_4403() -> None:
    w = World()
    with connect(w) as c:
        assert w.call(w.registry.user_disabled, USER) == 1
        bye, code = c.bye_then_close()
        assert (bye["p"]["reason"], code) == ("user_disabled", 4403)


def test_s7_kill_switch_transition_reevaluates_every_connected_user() -> None:
    w = World()
    with connect(w) as c:
        c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        c.drain(1)
        w.grants = ()  # the grant change landed while the kill switch fired
        w.call(w.registry.kill_switch_changed)
        assert c.next_validated("revoked")["p"]["reason"] in {
            "permission_revoked",
            "account_scope_changed",
        }


def test_s7_f3_permission_change_frame_validates_against_the_envelope() -> None:
    w = World()
    with connect(w) as c:
        w.grants = ()
        w.call(w.registry.grants_changed, USER)
        frame = c.recv_permission_change()  # validated against §13.4, not just the envelope
        assert frame["t"] == "permission_change"


# -- S8 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_s8_heuristic_heatmap_snapshot_is_tagged_estimated(mode: str) -> None:
    """The producing module marks the BODY heuristic; the gateway must carry that to the wire
    (the `estimated` payload field, or header flag bit0). The part itself is left unflagged so
    only the gateway's own tagging can satisfy the assertion."""
    w = World()
    plain = w.source.bodies["heatmap"]
    w.source.bodies["heatmap"] = replace(plain, estimated=True)
    with connect(w) as c:
        c.sub(entry("heatmap", ("symbol",), mode))
        snap = c.recv()
        if mode == "binary":
            assert snap["e"] == c.binary_e and cvwb_part(snap).flags & FLAG_ESTIMATED
        else:
            assert snap["p"]["estimated"] is True


@pytest.mark.parametrize("mode", MODES)
def test_s8_non_heuristic_heatmap_is_not_tagged_estimated(mode: str) -> None:
    w = World()
    with connect(w) as c:
        c.sub(entry("heatmap", ("symbol",), mode))
        snap = c.recv()
        if mode == "binary":
            assert snap["e"] == c.binary_e and not cvwb_part(snap).flags & FLAG_ESTIMATED
        else:
            assert snap["p"]["estimated"] is False


@pytest.mark.parametrize("mode", MODES)
def test_s8_metrics_payload_carries_estimated_per_series_where_heuristic(mode: str) -> None:
    """`metrics` series may be heuristic (§14.7); an `estimated:true` series must reach the wire."""
    w = World()
    snap = {"symbol": SYM, "series": [{"metric": "cvd", "estimated": True, "t_ms": 1, "v": "1"}]}
    w.source.bodies["metrics"] = replace(w.source.bodies["metrics"], structured=snap)
    with connect(w) as c:
        c.sub(entry("metrics", ("symbol",), mode))
        assert c.recv()["p"]["series"][0]["estimated"] is True


def test_s8_footprint_imbalance_carries_estimated_where_heuristic() -> None:
    """`footprint` bars may hold heuristic imbalances (§14.4 `bars[].imbalances[].estimated`); an
    `estimated:true` one must reach the wire. Structured only: a kind-5 body has no such bit."""
    w = World()
    plain = w.source.bodies["footprint"]
    bars = [{**bar} for bar in plain.structured["bars"]]
    bars[0]["imbalances"] = [
        {"price": "100.0", "direction": "buy", "ratio": "3.5", "estimated": True}
    ]
    w.source.bodies["footprint"] = replace(plain, structured={**plain.structured, "bars": bars})
    with connect(w) as c:
        c.sub(entry("footprint", FAMILIES["footprint"].shapes[0]))
        snap = c.recv()  # validated against §14.4 first: `estimated` is a declared boolean there
        assert snap["p"]["bars"][0]["imbalances"][0]["estimated"] is True


def _estimated_paths(node: Any, path: str) -> Iterator[str]:
    """Where a schema declares an `estimated` property, wherever it sits: `.name` per property,
    `[]` per array item, `/key` for any other keyword (`$defs`, `oneOf`, `additionalProperties`)."""
    if isinstance(node, list):
        for i, child in enumerate(node):
            yield from _estimated_paths(child, f"{path}/{i}")
    elif isinstance(node, dict):
        if "estimated" in (node.get("properties") or {}):
            yield path
        for key, child in node.items():
            if key == "properties" and isinstance(child, dict):
                for name, prop in child.items():
                    yield from _estimated_paths(prop, f"{path}.{name}")
            else:
                yield from _estimated_paths(child, path + ("[]" if key == "items" else f"/{key}"))


def test_s8_the_closure_walk_sees_every_shape_a_schema_can_take() -> None:
    declares = {"properties": {"estimated": {"type": "boolean"}}}
    schema = {
        "$defs": {"x": declares},
        "oneOf": [{}, declares],
        "properties": {"rows": {"items": declares}},
        "additionalProperties": declares,
    }
    assert sorted(_estimated_paths(schema, "s")) == [
        "s.rows[]",
        "s/$defs/x",
        "s/additionalProperties",
        "s/oneOf/1",
    ]


def test_s8_every_estimated_field_the_schemas_declare_has_a_row_in_this_suite() -> None:
    """S8 closure: `estimated` is declared in exactly the three places the rows above assert. A
    fourth heuristic field fails here until it has a row of its own."""
    declared = sorted(
        path
        for sid, schema in SCHEMAS.items()
        for path in _estimated_paths(schema, sid.rsplit("/", 1)[1].removesuffix(".schema.json"))
    )
    assert declared == ["footprint.bars[].imbalances[]", "heatmap", "metrics.series[]"]


# -- S9 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_s9_replay_frames_carry_source_rs_wt_and_the_recorded_ts(mode: str) -> None:
    w = World()
    e = entry("trades", ("symbol",), mode)
    with connect(w) as c:
        c.send({"t": "sub", "id": "r", "p": {"topics": [e], "replay_session_id": RS}})
        c.next_of("sub_ok")
        snap = c.recv()
        assert snap["meta"]["source"] == "replay" and snap["rs"] == RS and "wt" in snap
        recorded = 1_700_000_000_000
        assert publish(w, "trades", e["ch"], mode, replay=RS, ts_ms=recorded) == 1
        d = c.recv()
        assert (d["rs"], d["ts"]) == (RS, recorded)  # `ts` is the recorded time...
        assert d["wt"] == w.clock.wall_ms()  # ...`wt` the wall-clock send time
        if mode == "binary":
            assert cvwb_part(d).flags & FLAG_REPLAY  # header bit2 (§3.4)
            assert cvwb_part(snap).flags & FLAG_REPLAY


def test_s9_live_frames_never_carry_replay_markers() -> None:
    w = World()
    with connect(w) as c:
        c.sub(entry("trades", ("symbol",), "binary"))
        snap = c.recv()
        publish(w, "trades", "trades.BTCUSDT", "binary")
        d = c.recv()
        for f in (snap, d):
            assert "rs" not in f and "wt" not in f
            assert not cvwb_part(f).flags & FLAG_REPLAY
        assert snap["meta"]["source"] == "live"


def test_s9_replay_seek_snapshots_every_subscribed_topic_with_reason_replay_seek() -> None:
    w = World()
    with connect(w) as c:
        entries = [entry("trades", ("symbol",)), entry("ticker", ("symbol",))]
        c.send({"t": "sub", "id": "r", "p": {"topics": entries, "replay_session_id": RS}})
        c.next_of("sub_ok")
        c.drain(2)
        assert w.call(w.hub.replay_seek, RS) == 2
        seek = c.drain(2)
        assert {f["meta"]["reason"] for f in seek} == {"replay_seek"}
        assert all(f["rs"] == RS and f["s"] == 2 for f in seek)
