"""E21-X02 (#652) abuse cases over the raw client and the real `/ws` router (23 §5.2, §5.4, §16.2).

The Gherkin "Quota enforced and explained", AC-HM-10 and AC-HM-11 of the E21 model, the per-user
budget across a user's connections and under view-as (the acting user, §9.6), a refused `sub` that
takes nothing upstream, a `ctl` past a budget that changes nothing, the chaos scenarios C-13.6 #1,
#3 and #11 at the quota (a closed socket, a resync, a slow consumer's close), replay subscriptions
at their weight, HM-I04 (a refusal names nothing of another user's), a `ctl` that changes only
`price_grouping` past the user's distinct specs or a symbol's share, a `ctl` the rebuild budget
refuses (every charge kept), a revocation (§9.5, §7.5) and a release that raises (the charge given
back), and a structured heatmap at three times its binary weight. Each limit is written out as
23 §16.2 states it; every test runs under both subprotocols."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.quota import MESSAGES
from candleviewer.ws.rebuild_budget import topic_key
from candleviewer.ws.topics import parse_topic
from tests.contract.ws._harness import Client
from tests.security.marketdata.conftest import QuotaWorld
from tests.security.ws._raw import (
    Login,
    RawClient,
    authenticated,
    delta,
    delta_naming,
    raw_connect,
)
from tests.unit.ws._seq_support import ACC_A

#: 23 §16.2, interim: the points of a connection and of a user, and the counts.
POINTS_CONNECTION, POINTS_USER, HEATMAPS_CONNECTION, DEEP_BOOKS = 200, 400, 8, 4
#: Worked weights (23 §16.2): a depth-500 heatmap at 100 ms with a 50 ms throttle, and without,
#: each at grouping 2, a window that holds depth 500 (at grouping 1 it weighs three times).
HEAVY = {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2, "throttle_ms": 50}  # 160 points
DEEP = {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2}  # 80; its spec 80 for the server
RS = "bb000000-0000-4000-8000-000000000001"
SYMBOLS = tuple(f"S{n:02d}USDT" for n in range(40))
QUOTA = "cv_ws_subscription_quota_rejections_total"
#: The server's spec-points refusal at its 1 280 points (`orderflow/heatmap.py`), whole.
SERVER_SPENT = (
    "The server's heatmap budget of 1280 points is spent; use a slower bucket or a shallower depth."
)


@contextmanager
def socket(world: QuotaWorld, login: Login) -> Iterator[RawClient]:
    with raw_connect(world) as c:
        authenticated(c, login)
        yield c


def heatmap(symbol: str, **opts: Any) -> dict[str, Any]:
    return {"ch": f"heatmap.{symbol}", "opts": opts}


def results(c: Client, *topics: Any, **p: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = c.sub(*topics, **p)["p"]["results"]
    return found


def codes(found: list[dict[str, Any]]) -> list[str | None]:
    return [None if r["ok"] else r["error"]["code"] for r in found]


def refused(message: str) -> dict[str, Any]:
    """A quota refusal as §10.2 gives it: the limit code and a fixed message, nothing else."""
    return {"code": "subscription_limit", "message": message, "retryable": True}


def counted(*reasons: str) -> dict[str, Callable[[], float]]:
    return {r: delta(QUOTA, reason=r) for r in reasons}


# -- Gherkin "Quota enforced and explained" ------------------------------------------------------


def test_quota_enforced_and_explained_a_depth_500_book_past_the_deep_book_cap(
    world: QuotaWorld,
) -> None:
    """Given a client already holds the maximum number of deep-book subscriptions, when it
    subscribes to another depth-500 topic, the server rejects it with a typed error, counts it,
    and the message names the cap (the client's explanation: `apps/web` engine.quotaRefusal)."""
    alice = world.login("alice")
    seen = counted("deep_book_connection")
    with socket(world, alice) as c:
        assert codes(results(c, *(f"book.{s}.500" for s in SYMBOLS[:DEEP_BOOKS]))) == [None] * 4
        opened = len(world.upstream.opened)
        (fifth,) = results(c, f"book.{SYMBOLS[4]}.500")
    assert fifth == {"ch": f"book.{SYMBOLS[4]}.500", "ok": False, "error": refused(
        "At most 4 deep book subscriptions (depth 200 or more) per connection."
    )}  # fmt: skip
    assert seen["deep_book_connection"]() == 1
    assert len(world.upstream.opened) == opened  # nothing taken upstream for it


def test_quota_enforced_and_explained_a_depth_500_heatmap_past_the_connection_budget(
    world: QuotaWorld,
) -> None:
    alice = world.login("alice")
    seen = counted("points_connection")
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **HEAVY))) == [None]  # 160 of 200
        (second,) = results(c, heatmap(SYMBOLS[1], **HEAVY))
        assert second["error"] == refused(MESSAGES["points_connection"])
        assert codes(results(c, heatmap(SYMBOLS[1], depth=50, time_bucket_ms=1000))) == [None]
    assert seen["points_connection"]() == 1
    assert world.held(alice) == (0, 0, 0)  # the socket's end gave it all back


def test_structured_heatmaps_reach_the_connection_quota_at_a_third_of_the_binary_count(
    world: QuotaWorld,
) -> None:
    """23 §16.2: a structured subscription weighs three times its binary weight. At depth 500 and
    a 250 ms bucket a connection holds six binary heatmaps and two structured ones; the next of
    each is refused at the connection's points."""
    alice = world.login("alice")
    wide = {"depth": 500, "time_bucket_ms": 250, "price_grouping": 2}  # a window that holds it
    seen = counted("points_connection")
    for encoding, fit in (("binary", 6), ("structured", 2)):
        with socket(world, alice) as c:
            asked = (heatmap(s, encoding=encoding, **wide) for s in SYMBOLS[: fit + 1])
            found = results(c, *asked)
            assert codes(found) == [None] * fit + ["subscription_limit"]
            assert found[fit]["error"] == refused(MESSAGES["points_connection"])
            assert world.held(alice)[:2] == (192, fit)
    assert seen["points_connection"]() == 2


def test_binary_heatmaps_whose_window_cannot_hold_their_depth_weigh_three_times(
    world: QuotaWorld,
) -> None:
    """23 §16.2: a `heatmap.*` whose window cannot hold its depth weighs at the structured factor
    whatever its encoding. Binary depth-500 heatmaps at grouping 1 reach the connection's points at
    a third of the count of grouping-2 ones, whose window holds depth 500."""
    alice = world.login("alice")
    seen = counted("points_connection")
    for grouping, fit in ((2, 6), (1, 2)):
        with socket(world, alice) as c:
            wide = {"depth": 500, "time_bucket_ms": 250, "price_grouping": grouping}
            found = results(c, *(heatmap(s, **wide) for s in SYMBOLS[: fit + 1]))
            assert codes(found) == [None] * fit + ["subscription_limit"]
            assert found[fit]["error"] == refused(MESSAGES["points_connection"])
            assert world.held(alice)[:2] == (192, fit)
    assert seen["points_connection"]() == 2


def test_a_structured_heatmaps_ctl_keeps_its_factor(world: QuotaWorld) -> None:
    """§5.4, §16.2: a `ctl` on a structured heatmap, of a spec option or of `throttle_ms`, moves
    its charge to three times its new binary weight, in the subscription's, the connection's and
    the user's charge alike."""
    alice = world.login("alice")
    ch = f"heatmap.{SYMBOLS[0]}"
    with socket(world, alice) as c:
        asked = heatmap(SYMBOLS[0], depth=200, time_bucket_ms=500, encoding="structured")
        assert codes(results(c, asked)) == [None]  # 13 binary, 39 charged
        authz = world.authz(alice)
        (sub,) = (s for s in authz.by_id.values() if s.ch == ch)

        def charged() -> tuple[int, int, int]:
            return sub.quota_points, authz.quota.points, world.user_held(alice)[0]

        assert charged() == (39, 39, 39)
        respec = ctl(c, ch, 1, time_bucket_ms=1000)  # 7 binary
        assert respec["t"] == "ctl_ok" and charged() == (21, 21, 21)
        faster = ctl(c, ch, 2, throttle_ms=250)  # 25 binary
        assert faster["t"] == "ctl_ok" and charged() == (75, 75, 75)
        assert sub.effective["encoding"] == "structured"  # fixed at `sub`, kept by every `ctl`


def test_quota_per_user_budget_spans_the_users_connections(world: QuotaWorld) -> None:
    alice, bob = world.login("alice"), world.login("bob")
    seen = counted("points_user")
    with ExitStack() as stack:
        first, second, third = (stack.enter_context(socket(world, alice)) for _ in range(3))
        assert codes(results(first, heatmap(SYMBOLS[0], **HEAVY))) == [None]
        assert codes(results(second, heatmap(SYMBOLS[1], **HEAVY))) == [None]  # 320 of 400
        (over,) = results(third, heatmap(SYMBOLS[2], **HEAVY))
        assert over["error"] == refused(MESSAGES["points_user"])
        assert world.held(alice) == (320, 2, 2)
        theirs = stack.enter_context(socket(world, bob))  # another user's budget is its own
        assert codes(results(theirs, heatmap(SYMBOLS[2], **HEAVY))) == [None]
    assert seen["points_user"]() == 1


def test_quota_under_view_as_spends_the_viewers_budget(world: QuotaWorld) -> None:
    """§9.6: a viewing socket is served in its target's scope, and the viewer acts: it charges
    the viewer's budget, never the target's."""
    own, viewing = world.login("val"), world.login("val")  # one viewer, two sessions
    target = world.login("tom")
    world.view(viewing, target)
    with ExitStack() as stack:
        mine = stack.enter_context(socket(world, own))
        as_tom = stack.enter_context(socket(world, viewing))
        assert codes(results(mine, heatmap(SYMBOLS[0], **HEAVY))) == [None]
        assert codes(results(as_tom, heatmap(SYMBOLS[1], **HEAVY))) == [None]  # val's 320
        assert world.held(own) == (320, 2, 2) and world.held(target) == (0, 0, 0)
        more = stack.enter_context(socket(world, own))
        (over,) = results(more, heatmap(SYMBOLS[2], **HEAVY))
        assert over["error"] == refused(MESSAGES["points_user"])
        toms = [stack.enter_context(socket(world, target)) for _ in range(2)]
        for n, c in enumerate(toms):  # tom's own 320: his budget is untouched by the view
            assert codes(results(c, heatmap(SYMBOLS[3 + n], **HEAVY))) == [None]


# -- AC-HM-10 and AC-HM-11 -----------------------------------------------------------------------


def deep_flood(world: QuotaWorld, login: Login, sockets: int = 8) -> list[list[str | None]]:
    """AC-HM-10's profile: `sockets` connections of one user, each asking 40 `heatmap.*` at depth
    500, bucket 100, throttle 50 and window 900, then five `book.*.500` on top; the codes of each
    socket's two `sub` frames, in order. The sockets stay open until all have asked."""
    out: list[list[str | None]] = []
    with ExitStack() as stack:
        for _ in range(sockets):
            c = stack.enter_context(socket(world, login))
            wide = [heatmap(s, window_seconds=900, **HEAVY) for s in SYMBOLS]
            books = [f"book.{s}.500" for s in SYMBOLS[:5]]
            out.append(codes(results(c, *wide)) + codes(results(c, *books)))
    return out


def test_ac_hm_10_eight_sockets_of_deep_heatmaps_stop_at_the_budgets(world: QuotaWorld) -> None:
    """8 sockets x 40 deep heatmaps then deep books: refused past each budget, counted by
    reason, and another user's budgets hold."""
    alice, bob = world.login("alice"), world.login("bob")
    seen = counted("points_connection", "points_user", "deep_book_connection")
    sockets = deep_flood(world, alice)
    limit = "subscription_limit"
    for n, got in enumerate(sockets):
        first = None if n < 2 else limit  # 160 each: a third would take the user to 480 of 400
        assert got[:40] == [first] + [limit] * 39
        assert got[40:] == [None] * DEEP_BOOKS + [limit]  # 2 points each, then the deep-book cap
    assert seen["points_connection"]() == 2 * 39
    assert seen["points_user"]() == 6 * 40
    assert seen["deep_book_connection"]() == 8
    with socket(world, bob) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **HEAVY))) == [None]


def test_ac_hm_11_a_users_distinct_specs_stop_at_eight_and_the_server_budget_holds(
    world: QuotaWorld,
) -> None:
    """One symbol across sockets with every grouping: a user's third spec of one symbol, and its
    ninth in all, are refused; the symbol's four specs and the server's points hold for every
    user together, and the producer never holds more than they allow."""
    alice, bob, carol = (world.login(n) for n in ("alice", "bob", "carol"))
    light = {"depth": 50, "time_bucket_ms": 1000}  # 2 points: the counts bind, not the points
    seen = counted("heatmap_specs_user_symbol", "heatmap_specs_user", "heatmap_specs_symbol")
    with ExitStack() as stack:
        mine = [stack.enter_context(socket(world, alice)) for _ in range(3)]
        got = [codes(results(c, heatmap("BTCUSDT", price_grouping=g, **light))) for c, g in
               zip(mine, (1, 2, 5), strict=True)]  # fmt: skip
        assert got == [[None], [None], ["subscription_limit"]]
        wide = [heatmap(s, **light) for s in SYMBOLS[:7]]  # six more specs fit, the seventh not
        assert codes(results(mine[2], *wide)) == [None] * 6 + ["subscription_limit"]
        assert world.held(alice)[2] == 8
        for g in (5, 10):  # bob's own two specs of the symbol, a socket each (one per channel)
            theirs = stack.enter_context(socket(world, bob))
            assert codes(results(theirs, heatmap("BTCUSDT", price_grouping=g, **light))) == [None]
        hers = stack.enter_context(socket(world, carol))
        (fifth,) = results(hers, heatmap("BTCUSDT", price_grouping=20, **light))
        assert fifth["error"]["message"] == "At most 4 heatmap specs per symbol are served."
        assert len(world.heatmap._symbols["BTCUSDT"].specs) == 4
    assert (seen["heatmap_specs_user_symbol"](), seen["heatmap_specs_user"]()) == (1, 1)
    assert seen["heatmap_specs_symbol"]() == 1


def fill_server_points(world: QuotaWorld, stack: ExitStack) -> list[Login]:
    """16 depth-500, 100 ms specs from four users, two sockets each and two specs a socket (320 of
    each user's 400): the server's 1 280 points, every one admitted. The users, for the caller."""
    users = [world.login(f"u{n}") for n in range(4)]
    for n, user in enumerate(users):
        c1, c2 = (stack.enter_context(socket(world, user)) for _ in range(2))
        specs = SYMBOLS[4 * n : 4 * n + 4]
        assert codes(results(c1, *(heatmap(s, **DEEP) for s in specs[:2]))) == [None, None]
        assert codes(results(c2, *(heatmap(s, **DEEP) for s in specs[2:]))) == [None, None]
    assert world.heatmap._points == 1280
    return users


def test_the_servers_spec_points_hold_for_every_user_together(world: QuotaWorld) -> None:
    """16 depth-500, 100 ms specs fill the server's 1 280 points; the next is refused naming the
    budget, whoever asks, and a spec held already is shared at no cost."""
    seen = counted("points_server")
    with ExitStack() as stack:
        fill_server_points(world, stack)
        late = stack.enter_context(socket(world, world.login("late")))
        over, shared = results(late, heatmap(SYMBOLS[20], **DEEP), heatmap(SYMBOLS[0], **DEEP))
        assert over["error"] == refused(SERVER_SPENT)
        assert shared["ok"] and world.heatmap._points == 1280
    assert seen["points_server"]() == 1


# -- nothing upstream, nothing changed -----------------------------------------------------------


def test_a_refused_sub_takes_no_upstream_reference_lease_or_hold(world: QuotaWorld) -> None:
    alice = world.login("alice")
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **HEAVY))) == [None]
        assert codes(results(c, *(f"book.{s}.500" for s in SYMBOLS[1:5]))) == [None] * 4
        before = (list(world.upstream.opened), dict(world.heatmap._symbols), world.held(alice))
        found = results(
            c, heatmap(SYMBOLS[5], **HEAVY), f"book.{SYMBOLS[6]}.500", "bars.S07USDT.time.1"
        )
        assert codes(found) == ["subscription_limit", "subscription_limit", None]
        assert world.upstream.opened[: len(before[0])] == before[0]
        new = world.upstream.opened[len(before[0]) :]
        assert [k[0] for k in new] == ["S07USDT"]  # the bar series' trades: the one admitted
        assert dict(world.heatmap._symbols) == before[1] and world.held(alice) == before[2]
    assert world.series.ensured == []  # no series is held for a refused topic


def ctl(c: Client, ch: str, n: int, **p: Any) -> dict[str, Any]:
    c.send({"t": "ctl", "id": f"c{n}", "ch": ch, "p": p})
    while (frame := c.recv())["t"] not in {"ctl_ok", "err"}:
        pass
    return frame


def test_a_ctl_past_a_budget_changes_nothing(world: QuotaWorld) -> None:
    """Through `throttle_ms` and through a spec option (§5.4): `subscription_limit` with the
    fixed message, nothing applied, the lease and the charge as they were."""
    alice = world.login("alice")
    seen = counted("points_connection")
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **DEEP), heatmap(SYMBOLS[1], **DEEP))) == [
            None, None
        ]  # fmt: skip
        held, specs = world.held(alice), dict(world.heatmap._symbols)
        faster = ctl(c, f"heatmap.{SYMBOLS[0]}", 1, throttle_ms=50)  # 160 in place of 80: 240
        assert faster["t"] == "err" and faster["p"]["code"] == "subscription_limit"
        assert faster["p"]["message"] == MESSAGES["points_connection"]
        assert world.held(alice) == held and dict(world.heatmap._symbols) == specs
        light = f"heatmap.{SYMBOLS[2]}"
        assert codes(results(c, heatmap(SYMBOLS[2], depth=50, time_bucket_ms=1000))) == [None]
        rebuilds, key = world.authz(alice).rebuilds, topic_key(parse_topic(light), None)
        drawn = rebuilds.drawn(key)
        respec = ctl(c, light, 2, depth=500, time_bucket_ms=100)  # 240 in place of 2: 400
        assert respec["t"] == "err" and respec["p"]["message"] == MESSAGES["points_connection"]
        assert world.held(alice) == (162, 3, 3)
        assert rebuilds.drawn(key) == drawn  # §5.4: a `ctl` refused for a quota draws no rebuild
        assert {s.depth for s in world.heatmap._symbols[SYMBOLS[2]].specs} == {50}
        slower = ctl(c, f"heatmap.{SYMBOLS[0]}", 3, throttle_ms=1000)  # a lower weight: applied
        assert slower["t"] == "ctl_ok" and slower["p"]["effective"]["throttle_ms"] == 1000
    assert seen["points_connection"]() == 2


def specs_of(world: QuotaWorld, symbol: str) -> set[Any]:
    """The live specs of `symbol` in the producer, every user's."""
    return set(world.heatmap._symbols[symbol].specs)


def test_a_grouping_ctl_past_a_symbols_share_changes_nothing(world: QuotaWorld) -> None:
    """§5.4, §16.2: a `ctl` that changes only `price_grouping` (the weight unchanged) and so moves
    a subscription to a third spec of one symbol, the spec it leaves still held by another of the
    user's subscriptions, gets `subscription_limit` with the share's fixed message; the producer's
    specs and the user's ledger are as they were."""
    alice = world.login("alice")
    light = {"depth": 50, "time_bucket_ms": 1000}
    seen = counted("heatmap_specs_user_symbol")
    with ExitStack() as stack:
        one, two, three = (stack.enter_context(socket(world, alice)) for _ in range(3))
        for c, g in ((one, 1), (two, 2), (three, 1)):  # grouping 1 held twice, 2 once: the share
            assert codes(results(c, heatmap("BTCUSDT", price_grouping=g, **light))) == [None]
        before = (world.user_held(alice), specs_of(world, "BTCUSDT"))
        moved = ctl(three, "heatmap.BTCUSDT", 1, price_grouping=5)
        assert moved["t"] == "err" and moved["p"]["code"] == "subscription_limit"
        assert moved["p"]["message"] == MESSAGES["heatmap_specs_user_symbol"]
        assert (world.user_held(alice), specs_of(world, "BTCUSDT")) == before
    assert seen["heatmap_specs_user_symbol"]() == 1


def test_a_grouping_ctl_past_the_users_distinct_specs_changes_nothing(world: QuotaWorld) -> None:
    """The same through the user's eight distinct specs: a `ctl` of `price_grouping` alone moves a
    subscription off a spec another of the user's subscriptions holds, to a ninth spec, and gets
    `subscription_limit` with that limit's fixed message, nothing changed."""
    alice = world.login("alice")
    light = {"depth": 50, "time_bucket_ms": 1000}
    seen = counted("heatmap_specs_user")
    with ExitStack() as stack:
        wide, again = (stack.enter_context(socket(world, alice)) for _ in range(2))
        assert codes(results(wide, *(heatmap(s, **light) for s in SYMBOLS[:8]))) == [None] * 8
        assert codes(results(again, heatmap(SYMBOLS[0], **light))) == [None]  # spec 0, twice
        before = (world.user_held(alice), specs_of(world, SYMBOLS[0]))
        moved = ctl(again, f"heatmap.{SYMBOLS[0]}", 1, price_grouping=2)  # a ninth spec
        assert moved["t"] == "err" and moved["p"]["code"] == "subscription_limit"
        assert moved["p"]["message"] == MESSAGES["heatmap_specs_user"]
        assert (world.user_held(alice), specs_of(world, SYMBOLS[0])) == before
    assert seen["heatmap_specs_user"]() == 1


def test_a_ctl_the_rebuild_budget_refuses_keeps_every_charge(world: QuotaWorld) -> None:
    """§5.4, §7.5: once identity `ctl`s spend a stream's rebuild budget, a `ctl` that would raise
    or lower its weight is refused `resync_rate_limited`, and the subscription's, the connection's
    and the user's points are as they were: the charge moves only with a `ctl` that applies."""
    alice = world.login("alice")
    ch = f"heatmap.{SYMBOLS[0]}"
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], depth=200, time_bucket_ms=500))) == [None]
        for n in range(12):  # identity `ctl`s at one weight, until the stream's budget refuses
            spent = ctl(c, ch, n, price_grouping=1 + n % 2)
            if spent["t"] == "err":
                break
        assert spent["t"] == "err" and spent["p"]["code"] == "resync_rate_limited"
        authz = world.authz(alice)
        (sub,) = (s for s in authz.by_id.values() if s.ch == ch)
        held = (sub.quota_points, authz.quota.points, world.user_held(alice))
        assert held[0] == 13
        for n, bucket in enumerate((100, 1000)):  # 63 points, then 7: up, then down
            refused_ = ctl(c, ch, 20 + n, time_bucket_ms=bucket)
            assert refused_["t"] == "err" and refused_["p"]["code"] == "resync_rate_limited"
            assert (sub.quota_points, authz.quota.points, world.user_held(alice)) == held


# -- C-13.6 #1, #3 and #11 -----------------------------------------------------------------------


def test_a_closed_socket_releases_its_quota_and_its_reconnect_is_admitted(
    world: QuotaWorld,
) -> None:
    """C-13.6 #1: the quota a socket held is given back at its close, and the same subscriptions
    on a new socket are admitted, never refused falsely."""
    alice = world.login("alice")
    with socket(world, alice) as keep:
        assert codes(results(keep, heatmap(SYMBOLS[0], **HEAVY))) == [None]
        for _ in range(2):  # the dropped socket, then its reconnect
            with socket(world, alice) as c:
                assert codes(results(c, heatmap(SYMBOLS[1], **HEAVY))) == [None]
                assert world.held(alice) == (320, 2, 2)
            assert world.held(alice) == (160, 1, 1)
    assert world.held(alice) == (0, 0, 0) and len(world.registry.services.user_quota) == 0


def test_a_resync_resnapshot_spends_no_quota(world: QuotaWorld) -> None:
    """C-13.6 #3: a resync re-snapshots the stream; it charges nothing and the budget left is
    still admitted."""
    alice = world.login("alice")
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **DEEP))) == [None]
        held = world.held(alice)
        for n in range(3):
            c.send({"t": "resync", "id": f"r{n}", "ch": f"heatmap.{SYMBOLS[0]}",
                    "p": {"reason": "sequence_gap"}})  # fmt: skip
            assert c.next_of("snap")["ch"] == f"heatmap.{SYMBOLS[0]}"
        assert world.held(alice) == held
        assert codes(results(c, heatmap(SYMBOLS[1], **DEEP))) == [None]  # 160 of 200


def test_a_slow_consumer_close_releases_its_quota(world: QuotaWorld) -> None:
    """C-13.6 #11: a `slow_consumer` close (4429, §8.4) gives the socket's quota back."""
    alice = world.login("alice", ACC_A)
    body = delta_naming("orders", ACC_A)
    with socket(world, alice) as c:
        orders = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}}
        assert codes(results(c, orders, heatmap(SYMBOLS[0], **HEAVY))) == [None, None]
        assert world.held(alice) == (160, 1, 1)
        world.call(lambda: [world.hub.publish("orders", body, account=ACC_A) for _ in range(2500)])
        while (frame := c.recv(validate=False))["t"] != "bye":
            pass
        assert (frame["p"]["reason"], c.closed()) == ("slow_consumer", 4429)
    assert world.held(alice) == (0, 0, 0)
    with socket(world, alice) as again:
        assert codes(results(again, heatmap(SYMBOLS[0], **HEAVY))) == [None]


# -- revocation and a release that raises --------------------------------------------------------


def hold_both(world: QuotaWorld, c: Client, login: Login) -> None:
    """A depth-500 heatmap (80 points) and a depth-500 book (2), held and charged."""
    assert codes(results(c, heatmap(SYMBOLS[0], **DEEP), f"book.{SYMBOLS[1]}.500")) == [None] * 2
    assert world.held(login) == (82, 1, 1)


def nothing_held(world: QuotaWorld, login: Login) -> bool:
    """The ledger's empty shape for the user, and no user kept at all (C-2.18)."""
    return world.user_held(login) == (0, 0, {}) and len(world.registry.services.user_quota) == 0


def test_a_marketdata_withdrawal_gives_the_quota_back(world: QuotaWorld) -> None:
    """§9.5: `marketdata:read` withdrawn, the heatmap and the deep book are revoked
    `permission_revoked`, and each gives its weight back."""
    alice = world.login("alice")
    with socket(world, alice) as c:
        hold_both(world, c, alice)
        world.perms = world.perms - {Permission.MARKETDATA_READ}  # read at the next load
        world.call(world.registry.roles_changed, alice.user_id)
        ends = [c.next_of_raw("revoked") for _ in range(2)]
        assert {(f["ch"], f["p"]["reason"]) for f in ends} == {
            (f"heatmap.{SYMBOLS[0]}", "permission_revoked"),
            (f"book.{SYMBOLS[1]}.500", "permission_revoked"),
        }
        assert nothing_held(world, alice)


def test_a_resync_loop_revoke_gives_the_quota_back(world: QuotaWorld) -> None:
    """§7.5: a stream that asks `resync` past its rebuild budget is revoked `resync_rate_limited`
    and gives its weight back at once; the deep book keeps its own until the socket ends."""
    alice = world.login("alice")
    ch = f"heatmap.{SYMBOLS[0]}"
    with socket(world, alice) as c:
        hold_both(world, c, alice)
        for m in range(12):  # each `resync` answered before the `pong` of the `ping` after it
            c.send({"t": "resync", "id": f"r{m}", "ch": ch, "p": {"reason": "sequence_gap"}})
            c.send({"t": "ping", "id": f"p{m}"})
            seen = []
            while (frame := c.recv(validate=False))["t"] != "pong":
                seen.append(frame)
            ended = [f for f in seen if f["t"] == "revoked" and f["ch"] == ch]
            if ended:
                break
        assert [f["p"]["reason"] for f in ended] == ["resync_rate_limited"]
        assert world.user_held(alice) == (2, 0, {})
    assert nothing_held(world, alice)


def test_a_release_that_raises_still_gives_the_quota_back(
    world: QuotaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2735: the heatmap's release raises inside `release_all` at the socket's end; the rest go
    on, and the charge, given back before any release, leaves the user holding nothing."""
    alice = world.login("alice")

    def raising(*_: object) -> None:
        raise RuntimeError("the heatmap release failed")

    with socket(world, alice) as c:
        hold_both(world, c, alice)
        monkeypatch.setattr(world.heatmap, "release", raising)
    assert nothing_held(world, alice)


# -- replay, and HM-I04 --------------------------------------------------------------------------


def test_replay_subscriptions_count_at_their_weight(world: QuotaWorld) -> None:
    """A replay deep book is charged its weight as a live one is (BQ-3), so it counts toward the
    connection's points: with four of them held, a heatmap that fits without them is refused."""
    alice = world.login("alice")
    probe = heatmap(SYMBOLS[9], depth=200, time_bucket_ms=500, throttle_ms=175)  # 36 points
    with socket(world, alice) as c:
        assert codes(results(c, heatmap(SYMBOLS[0], **HEAVY))) == [None]  # 160
        replay = [f"book.{s}.500" for s in SYMBOLS[1:5]]
        assert codes(results(c, *replay, replay_session_id=RS)) == [None] * 4  # 4 x 2 points
        assert world.held(alice) == (168, 1, 1)
        (over,) = results(c, probe)
        assert over["error"] == refused(MESSAGES["points_connection"])  # 204 of 200
        c.send({"t": "unsub", "id": "u", "rs": RS, "p": {"topics": replay}})
        c.next_of("unsub_ok")
        assert world.held(alice) == (160, 1, 1)
        assert codes(results(c, probe)) == [None]  # 196 of 200


def test_a_refusal_message_names_no_other_users_subscription_or_spec(world: QuotaWorld) -> None:
    """HM-I04 and BQ-6's rider: a refusal carries the limit code and a fixed message only, the
    same whoever holds what; nothing of another user's subscriptions or specs is in it."""
    bob, alice = world.login("bob"), world.login("alice")
    light = {"depth": 50, "time_bucket_ms": 1000}
    with ExitStack() as stack:
        marks = [heatmap("XRPUSDT", price_grouping=7, **light), "book.XRPUSDT.500"]
        marks += [heatmap("ADAUSDT", price_grouping=17, **light)]
        assert codes(results(stack.enter_context(socket(world, bob)), *marks)) == [None] * 3
        other = stack.enter_context(socket(world, bob))  # a second spec of the symbol
        assert codes(results(other, heatmap("XRPUSDT", price_grouping=9, **light))) == [None]
        c = stack.enter_context(socket(world, alice))
        found = results(c, *(heatmap(s, **light) for s in SYMBOLS[:9]))  # the ninth: per socket
        found += results(c, heatmap("XRPUSDT", price_grouping=11, **light))
        found += results(c, *(f"book.{s}.500" for s in SYMBOLS[9:14]))  # the fifth: the cap
        frames = [ctl(c, f"heatmap.{SYMBOLS[n]}", n, **HEAVY) for n in range(2)]  # 182, then 340
    with ExitStack() as stack:  # the server's spec points, spent by four other users' specs
        others = fill_server_points(world, stack)
        (spent,) = results(stack.enter_context(socket(world, alice)), heatmap(SYMBOLS[20], **DEEP))
    assert [f["t"] for f in frames] == ["ctl_ok", "err"]
    errors = [r["error"] for r in found if not r["ok"]] + [frames[1]["p"], spent["error"]]
    fixed = {
        MESSAGES["heatmap_connection"],
        MESSAGES["points_connection"],
        "At most 4 deep book subscriptions (depth 200 or more) per connection.",
        SERVER_SPENT,
    }
    assert len(errors) == 5 and {e["message"] for e in errors} == fixed
    assert spent["error"] == refused(SERVER_SPENT)  # the whole text, nothing appended to it
    for e in errors:  # the code, the fixed message and the catalogue's members only
        assert e["code"] == "subscription_limit" and e["retryable"] is True
        assert set(e) <= {"code", "message", "retryable", "close"}, e
    text = json.dumps(errors)
    held = [*SYMBOLS[:16], *(str(u.user_id) for u in others)]  # the other users' specs and ids
    for named in (str(bob.user_id), "XRPUSDT", "ADAUSDT", "17", " 7", " 9", *held):
        assert named not in text
