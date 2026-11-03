"""E21-X02 (#652; 23 §5.4, §16.2): the subscription quota's weights and ledgers (`ws/quota.py`).

The weights against 23 §16.2's worked values; the per-connection and per-user ledgers at their
edges, counting `heatmap.*` subscriptions and a user's distinct specs (of one symbol too); a user
kept only while it holds something (C-2.18); every refusal of the quota family counted once under
its reason, the deep-book cap's and the spec caps' included, through the gateway's own admission
(`ConnectionAuthz`); and a hypothesis run of admits, refusals, `ctl`s and drops in which a ledger
always holds the sum of its live charges and never passes a budget."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bus.bus import Bus
from candleviewer.orderflow.heatmap import (
    HEATMAP_MAX_POINTS_PER_SERVER,
    HEATMAP_MAX_SPECS_PER_SERVER,
    HEATMAP_MAX_SPECS_PER_SYMBOL,
    QUOTA_ROWS_PER_POINT,
    ROW_BYTES,
    ROWS,
    STRUCTURED_ROW_BYTES,
    HeatmapSpec,
    HeatmapTopic,
    column_points,
    spec_points,
)
from candleviewer.ws import limits
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.quota import (
    FREE,
    MESSAGES,
    REASONS,
    Charge,
    ConnectionQuota,
    QuotaReason,
    UserQuota,
    charge_of,
)
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.topics import FAMILIES, effective_options, parse_topic, validate_options
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import heatmap_part

ALICE, BOB = uuid.UUID(int=1), uuid.UUID(int=2)
SYMBOLS = tuple(f"S{n:02d}USDT" for n in range(24))
_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "23-ws-protocol.md"


def weight(ch: str, **opts: Any) -> Charge:
    """The charge of a `sub` of `ch` with `opts`, as the gateway weighs it: validated, effective."""
    topic = parse_topic(ch)
    return charge_of(topic, effective_options(topic, validate_options(topic.family, opts)))


def heatmap(symbol: str = "BTCUSDT", **opts: Any) -> Charge:
    return weight(f"heatmap.{symbol}", **opts)


# -- the weights ---------------------------------------------------------------------------------

#: 23 §16.2's worked values: (topic, options, points), in the table's order.
WORKED = [
    ("heatmap.BTCUSDT", {"depth": 50, "time_bucket_ms": 1000}, 2),
    ("heatmap.BTCUSDT", {"depth": 200, "time_bucket_ms": 500}, 13),
    ("heatmap.BTCUSDT", {"depth": 200, "time_bucket_ms": 500, "encoding": "structured"}, 39),
    ("heatmap.BTCUSDT", {"depth": 200, "time_bucket_ms": 100}, 63),
    ("heatmap.BTCUSDT", {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2}, 80),
    ("heatmap.BTCUSDT", {"depth": 500, "time_bucket_ms": 100, "price_grouping": 1}, 240),
    (
        "heatmap.BTCUSDT",
        {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2, "throttle_ms": 50},
        160,
    ),
    ("book.BTCUSDT.200", {}, 1),
    ("book.BTCUSDT.500", {}, 2),
]


@pytest.mark.parametrize(("ch", "opts", "points"), WORKED)
def test_weights_match_the_contract_worked_values(
    ch: str, opts: dict[str, Any], points: int
) -> None:
    assert weight(ch, **opts).points == points


def test_the_measured_server_case_weighs_twice_the_servers_budget() -> None:
    """23 §16.2: 32 specs at 100 ms and 512 rows, the case #4922 measured on one loaded core."""
    assert 32 * spec_points(HeatmapSpec("BTCUSDT", 500, 1, 100)) == 2560
    assert HEATMAP_MAX_POINTS_PER_SERVER == 1280


def _option(value: str) -> int | str:
    return int(value.replace(" ", "")) if value[0].isdigit() else value


def test_the_contract_states_the_worked_values_the_code_weighs() -> None:
    """The worked values table below 23 §16.2's limits is the one `WORKED` holds, and its last row,
    the server's measured case, is 32 depth-500 specs at 100 ms and twice the server's budget."""
    text = _DOC.read_text(encoding="utf-8")
    sec = text[text.index("### 16.2 Limits summary") : text.index("### 16.3 ")]
    rows = re.findall(r"^\| (`heatmap\.\*`[^|]*|deep `book\.\*`[^|]*?)\s*\| (\d+)\s*\|$", sec, re.M)
    stated = []
    for what, points in rows:
        pairs = re.findall(r"`(\w+)` (\d[\d ]*\d|\d|[a-z]+)", what)
        opts = {k: _option(v) for k, v in pairs}
        ch = "heatmap.BTCUSDT" if what.startswith("`heatmap") else f"book.BTCUSDT.{what[-3:]}"
        stated.append((ch, opts, int(points)))
    assert stated == WORKED
    server = re.search(
        r"^\| (\d+) heatmap specs at `time_bucket_ms` (\d+) and (\d+) rows \(the server's\)\s*"
        r"\| (\d[\d ]*\d)\s*\|$",
        sec,
        re.M,
    )
    assert server is not None
    specs, bucket, rows_, points = (int(g.replace(" ", "")) for g in server.groups())
    assert (specs, rows_) == (HEATMAP_MAX_SPECS_PER_SERVER, ROWS)
    assert points == specs * spec_points(HeatmapSpec("BTCUSDT", 500, 1, bucket))
    assert points == 2 * HEATMAP_MAX_POINTS_PER_SERVER


@pytest.mark.parametrize(
    "opts",
    [
        {"depth": 50, "time_bucket_ms": 1000},
        {"depth": 200, "time_bucket_ms": 500},
        {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2, "throttle_ms": 50},
    ],
)
def test_a_structured_heatmap_weighs_three_times_its_binary_points(opts: dict[str, Any]) -> None:
    """23 §16.2: a structured subscription weighs three times its binary weight, the per-row bound
    ratio of G-03, in the connection's and the user's ledgers; its spec, and so the server's spec
    points, are the same in both encodings."""
    binary, structured = heatmap(**opts), heatmap(encoding="structured", **opts)
    assert heatmap(encoding="binary", **opts) == binary  # binary is the family's default
    assert structured.points == limits.STRUCTURED_HEATMAP_WEIGHT * binary.points
    spec = structured.spec
    assert spec is not None and spec == binary.spec  # the producer's cost: its bucket, either way
    assert spec_points(spec) == column_points(spec.depth, opts["time_bucket_ms"])


@pytest.mark.parametrize(
    ("depth", "grouping", "factor"),
    [(500, 1, limits.STRUCTURED_HEATMAP_WEIGHT), (500, 2, 1), (200, 1, 1), (50, 1, 1)],
)
def test_a_heatmap_whose_window_cannot_hold_its_depth_weighs_at_the_structured_factor(
    depth: int, grouping: int, factor: int
) -> None:
    """23 §16.2: a `heatmap.*` whose window, the grid's rows centred on the mid at
    `price_grouping` ticks a row, cannot hold its `depth` levels a side weighs at the structured
    factor whatever its `encoding`, once; one whose window holds its depth keeps its binary weight
    in the binary encoding. Its spec, the server's points, is the same either way."""
    assert limits.HEATMAP_WINDOW_ROWS_A_SIDE == ROWS // 2 == 256
    edge = limits.heatmap_window_cannot_hold
    assert (edge(256, 1), edge(257, 1), edge(512, 2), edge(513, 2)) == (False, True, False, True)
    opts: dict[str, Any] = {"depth": depth, "price_grouping": grouping, "time_bucket_ms": 100}
    binary, structured = heatmap(**opts), heatmap(encoding="structured", **opts)
    assert limits.heatmap_window_cannot_hold(depth, grouping) is (factor == 3)
    assert binary.points == factor * column_points(depth, 100)
    assert structured.points == limits.STRUCTURED_HEATMAP_WEIGHT * column_points(depth, 100)  # once
    assert binary.spec == structured.spec == HeatmapSpec("BTCUSDT", depth, grouping, 100)


def test_depth_500_and_a_100ms_bucket_weigh_more_than_depth_50_at_1000ms() -> None:
    """The ticket's sentence: depth 500 and a 100 ms bucket count more than depth 50 at 1 000 ms."""
    shallow, deep = heatmap(depth=50, time_bucket_ms=1000), heatmap(depth=500, time_bucket_ms=100)
    assert deep.points > shallow.points
    assert heatmap(depth=500, time_bucket_ms=1000).points > shallow.points  # depth alone
    assert heatmap(depth=50, time_bucket_ms=100).points > shallow.points  # bucket alone


def test_rows_are_capped_at_512() -> None:
    """24 §6.1's `rows`: depth 500 sends at most 512 rows, never 1 000."""
    deep = heatmap(depth=500, time_bucket_ms=1000, price_grouping=2)  # a window that holds it
    assert deep.points == 8  # ⌈512 ÷ 64⌉, never ⌈1 000 ÷ 64⌉
    assert column_points(500, 1000) == column_points(256, 1000) == -(-512 // QUOTA_ROWS_PER_POINT)
    assert column_points(200, 1000) == 7  # 400 rows: under the cap, 2 x depth


def test_a_throttle_above_the_bucket_still_weighs_one_frame_per_column() -> None:
    at_bucket = heatmap(depth=200, time_bucket_ms=100)
    slower = heatmap(depth=200, time_bucket_ms=100, throttle_ms=1000)
    assert slower.points == at_bucket.points == 63  # one column a bucket, whatever the throttle
    faster = heatmap(depth=200, time_bucket_ms=1000, throttle_ms=100)
    assert faster.points == 63 > heatmap(depth=200, time_bucket_ms=1000).points == 7


def test_the_throttle_floor_sets_the_frame_rate() -> None:
    """A throttle below 50 ms is the 50 ms floor (§5.1), in `effective` and in the weight alike."""
    asked = heatmap(depth=200, time_bucket_ms=100, throttle_ms=10)
    assert asked.points == heatmap(depth=200, time_bucket_ms=100, throttle_ms=50).points == 125
    raw = charge_of(parse_topic("heatmap.BTCUSDT"), {"throttle_ms": 1, "time_bucket_ms": 100})
    assert raw.points == 125  # floored even if an effective throttle came below it


def test_only_book_and_heatmap_weigh_and_system_never() -> None:
    assert weight("book.BTCUSDT.50") == weight("book.BTCUSDT.1") == FREE
    assert weight("trades.BTCUSDT") == weight("ticker.BTCUSDT") == FREE
    assert charge_of(parse_topic("system"), {}) == FREE
    spec = heatmap(depth=50, time_bucket_ms=1000).spec
    assert spec == HeatmapSpec("BTCUSDT", 50, 1, 1000) and weight("book.BTCUSDT.500").spec is None


def test_the_deep_book_rows_scale_by_depth_from_the_measured_depth() -> None:
    assert limits.DEEP_BOOK_ROWS_PER_PUBLISH == 5 and limits.DEEP_BOOK_MEASURED_DEPTH == 200
    assert limits.DEEP_BOOK_PUBLISHES_PER_S == 10
    rows_500 = Decimal(limits.DEEP_BOOK_ROWS_PER_PUBLISH) * 500 / 200  # 12.5: an extrapolation
    assert weight("book.BTCUSDT.500").points == math.ceil(rows_500 * 10 / QUOTA_ROWS_PER_POINT) == 2


def test_the_budgets_are_the_interim_values() -> None:
    """Each value pinned, so a change is a reviewed diff (23 §16.2; the Owner ratifies them)."""
    assert (limits.QUOTA_POINTS_PER_CONNECTION, limits.QUOTA_POINTS_PER_USER) == (200, 400)
    assert (limits.MAX_HEATMAP_SUBSCRIPTIONS, limits.MAX_HEATMAP_SUBSCRIPTIONS_PER_USER) == (8, 16)
    assert (limits.MAX_HEATMAP_SPECS_PER_USER, limits.MAX_HEATMAP_SPECS_PER_USER_SYMBOL) == (8, 2)
    assert QUOTA_ROWS_PER_POINT == 64
    assert limits.STRUCTURED_HEATMAP_WEIGHT == STRUCTURED_ROW_BYTES // ROW_BYTES == 3  # G-03's
    assert limits.HEATMAP_WINDOW_ROWS_A_SIDE == ROWS // 2  # the window's rows a side of the mid


# -- the ledgers ----------------------------------------------------------------------------------


def _quota(users: UserQuota, user: uuid.UUID = ALICE) -> ConnectionQuota:
    return ConnectionQuota(users, user, clock=lambda: 0.0)


def _spec(n: int, symbol: str | None = None) -> HeatmapSpec:
    return HeatmapSpec(symbol or SYMBOLS[n], 50, 1, 1000)


def test_the_budget_edge_admits_the_budget_and_refuses_one_more() -> None:
    users = UserQuota()
    first, second, third = _quota(users), _quota(users), _quota(users)
    assert first.refusal(Charge(199)) is None
    first.charge(Charge(199))
    assert first.refusal(Charge(1)) is None  # to the connection's 200 exactly
    first.charge(Charge(1))
    assert first.refusal(Charge(1)) == "points_connection"
    second.charge(Charge(199))
    assert second.refusal(Charge(1)) is None  # to the user's 400 exactly
    second.charge(Charge(1))
    assert third.refusal(Charge(1)) == "points_user"
    assert _quota(users, BOB).refusal(Charge(200)) is None  # another user's budget is its own


def test_heatmap_count_caps_per_connection_and_per_user() -> None:
    users = UserQuota()
    first, second, third = _quota(users), _quota(users), _quota(users)
    for n in range(8):
        assert first.refusal(Charge(1, _spec(n))) is None
        first.charge(Charge(1, _spec(n)))
    assert first.refusal(Charge(1, _spec(0))) == "heatmap_connection"
    for n in range(8):  # the same specs: no new one for the user
        assert second.refusal(Charge(1, _spec(n))) is None
        second.charge(Charge(1, _spec(n)))
    assert third.refusal(Charge(1, _spec(0))) == "heatmap_user"
    assert third.refusal(Charge(2)) is None  # a deep book is no heatmap
    assert users.held(ALICE)[:2] == (16, 16)


def test_distinct_specs_per_user_count_specs_not_subscriptions() -> None:
    users = UserQuota()
    first, second = _quota(users), _quota(users)
    for n in range(8):
        first.charge(Charge(1, _spec(n)))
    for n in range(4):  # more subscriptions of the same specs fit
        assert second.refusal(Charge(1, _spec(n))) is None
        second.charge(Charge(1, _spec(n)))
    assert second.refusal(Charge(1, _spec(8))) == "heatmap_specs_user"  # a ninth spec does not
    first.credit(Charge(1, _spec(0)))  # spec 0 is still second's: still eight
    assert second.refusal(Charge(1, _spec(8))) == "heatmap_specs_user"
    first.credit(Charge(1, _spec(1)))
    second.credit(Charge(1, _spec(1)))  # spec 1's last subscription: seven
    assert second.refusal(Charge(1, _spec(8))) is None


def test_a_users_specs_of_one_symbol_stop_at_two() -> None:
    """The per-user, per-symbol share: a third spec of one symbol is refused, another user fits."""
    users = UserQuota()
    quota = _quota(users)
    one, two, three = (HeatmapSpec("BTCUSDT", 200, g, 500) for g in (1, 2, 5))
    for spec in (one, two):
        assert quota.refusal(Charge(8, spec)) is None
        quota.charge(Charge(8, spec))
    assert quota.refusal(Charge(8, one)) is None  # a held spec again: no new one
    assert quota.refusal(Charge(8, three)) == "heatmap_specs_user_symbol"
    assert quota.refusal(Charge(8, HeatmapSpec("ETHUSDT", 200, 5, 500))) is None
    assert _quota(users, BOB).refusal(Charge(8, three)) is None
    assert quota.refusal(Charge(8, three), Charge(8, two)) is None  # a ctl moving off `two` fits


def test_a_ctl_off_a_spec_held_twice_keeps_counting_that_spec() -> None:
    """A spec another subscription of the user still holds stays the user's: moving one of its two
    subscriptions to a new spec adds one, refused past the user's eight distinct specs and past one
    symbol's two; once the spec is held once, the same move only replaces it."""
    users = UserQuota()
    first, second = _quota(users), _quota(users)
    for n in range(8):
        first.charge(Charge(1, _spec(n)))
    second.charge(Charge(1, _spec(0)))  # spec 0, held twice
    assert second.refusal(Charge(1, _spec(8)), Charge(1, _spec(0))) == "heatmap_specs_user"
    first.credit(Charge(1, _spec(0)))  # held once: moving off it frees it
    assert second.refusal(Charge(1, _spec(8)), Charge(1, _spec(0))) is None
    users = UserQuota()
    a, b = _quota(users), _quota(users)
    one, two, three = (HeatmapSpec("BTCUSDT", 200, g, 500) for g in (1, 2, 5))
    for quota, spec in ((a, one), (a, two), (b, one)):  # `one` held twice
        quota.charge(Charge(8, spec))
    assert b.refusal(Charge(8, three), Charge(8, one)) == "heatmap_specs_user_symbol"
    a.credit(Charge(8, one))
    assert b.refusal(Charge(8, three), Charge(8, one)) is None


def test_a_ctl_is_checked_less_its_own_charge_and_a_lower_one_always_fits() -> None:
    users = UserQuota()
    quota = _quota(users)
    held = Charge(103, _spec(0))
    quota.charge(held)
    assert quota.refusal(Charge(200, _spec(0)), held) is None  # 200 in place of its own 103
    assert quota.refusal(Charge(201, _spec(0)), held) == "points_connection"
    quota.charge(Charge(97))
    assert quota.points == 200
    assert quota.refusal(Charge(52, _spec(0)), held) is None  # lowering is never refused


def test_a_user_with_nothing_held_is_forgotten() -> None:
    """C-2.18: a user is kept only while it holds a charge."""
    users = UserQuota()
    quota, other = _quota(users), _quota(users, BOB)
    quota.charge(Charge(52, _spec(0)))
    other.charge(Charge(2))
    assert len(users) == 2
    quota.charge(Charge(52, _spec(1)), Charge(52, _spec(0)))  # a moved spec is still held
    quota.credit(Charge(52, _spec(1)))
    other.credit(Charge(2))
    assert len(users) == 0 and users.held(ALICE) == (0, 0, {})


_OP = st.tuples(
    st.sampled_from(("admit", "ctl", "drop")),
    st.integers(0, 2),  # which connection: two of alice's, one of bob's
    st.integers(0, 40),  # which held subscription, or the points of a new charge
    st.one_of(st.none(), st.integers(0, 9)),  # a heatmap's spec, or a deep book
)


@settings(max_examples=150, deadline=None)
@given(st.lists(_OP, max_size=60))
def test_a_ledger_holds_the_sum_of_its_live_weights(
    ops: list[tuple[str, int, int, int | None]],
) -> None:
    users = UserQuota()
    conns = [_quota(users, ALICE), _quota(users, ALICE), _quota(users, BOB)]
    live: list[list[Charge]] = [[], [], []]
    for op, c, n, spec in ops:
        quota, held = conns[c], live[c]
        new = Charge(n * 3, None if spec is None else _spec(spec, SYMBOLS[spec % 5]))
        if op == "admit" and new != FREE:
            if quota.refusal(new) is None:
                quota.charge(new)
                held.append(new)
        elif op == "ctl" and held:
            i = n % len(held)
            if quota.refusal(new, held[i]) is None and new != FREE:
                quota.charge(new, held[i])
                held[i] = new
        elif op == "drop" and held:
            quota.credit(held.pop(n % len(held)))
        for q, h in zip(conns, live, strict=True):
            assert q.points == sum(x.points for x in h) <= q.max_points
            assert q.heatmaps == sum(x.spec is not None for x in h) <= q.max_heatmaps
        for user, mine in ((ALICE, live[0] + live[1]), (BOB, live[2])):
            points, heatmaps, specs = users.held(user)
            assert points == sum(x.points for x in mine) <= users.points
            assert heatmaps == sum(x.spec is not None for x in mine) <= users.heatmaps
            assert len(specs) == len({x.spec for x in mine if x.spec is not None}) <= users.specs
    for quota, held in zip(conns, live, strict=True):
        while held:
            quota.credit(held.pop())
    assert len(users) == 0 and all(q.points == q.heatmaps == 0 for q in conns)


# -- the refusals, through the gateway's admission ------------------------------------------------


class _Sink:
    async def open(self, key: Any) -> None:
        return None

    async def drop(self, key: Any) -> None:
        return None


class _Hub:
    def publish(self, ch: str, body: Any = None, **kw: Any) -> int:
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


def _topic(caps: dict[str, int]) -> HeatmapTopic:
    return HeatmapTopic(
        _Hub(), engine=lambda _s: None, steps=lambda _s: (Decimal("0.1"), Decimal("0.001")),
        part=heatmap_part, body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608,
        queue_frames=2_000, clock_ms=lambda: 1_700_000_000_000.0,
        max_specs_per_symbol=caps.get("max_specs_per_symbol", HEATMAP_MAX_SPECS_PER_SYMBOL),
        max_specs_per_server=caps.get("max_specs_per_server", HEATMAP_MAX_SPECS_PER_SERVER),
        max_points_per_server=caps.get("max_points_per_server", HEATMAP_MAX_POINTS_PER_SERVER),
    )  # fmt: skip


def _conn(services: SubscriptionServices, user: int = 1) -> ConnectionAuthz:
    principal = PrincipalSnapshot(
        uuid.UUID(int=user), frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
    )
    return ConnectionAuthz(principal, services)


def _sub(conn: ConnectionAuthz, *topics: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    asyncio.run(handle_sub(conn, {"t": "sub", "id": "s", "p": {"topics": list(topics)}}, send))
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    return results


def _hm(symbol: str, **opts: Any) -> dict[str, Any]:
    return {"ch": f"heatmap.{symbol}", "opts": opts}


def _services(**caps: int) -> SubscriptionServices:
    return SubscriptionServices(
        upstream=UpstreamRefs(_Sink()), heatmap=_topic(caps), depth_500=True
    )


def _scenario(reason: QuotaReason) -> tuple[ConnectionAuthz, dict[str, Any]]:
    """A connection one `sub` entry short of `reason`'s refusal, and that entry."""
    deep = {"depth": 500, "time_bucket_ms": 100, "price_grouping": 2, "throttle_ms": 50}  # 160
    if reason == "deep_book_connection":
        conn = _conn(_services())
        _sub(conn, *({"ch": f"book.{s}.200"} for s in SYMBOLS[:4]))
        return conn, {"ch": f"book.{SYMBOLS[4]}.200"}
    if reason == "heatmap_connection":
        conn = _conn(_services())
        _sub(conn, *(_hm(s, depth=50, time_bucket_ms=1000) for s in SYMBOLS[:8]))
        return conn, _hm(SYMBOLS[8], depth=50, time_bucket_ms=1000)  # before the user's specs
    if reason == "heatmap_user":
        services = _services()
        for _ in range(2):
            _sub(_conn(services), *(_hm(s, depth=50, time_bucket_ms=1000) for s in SYMBOLS[:8]))
        return _conn(services), _hm(SYMBOLS[0], depth=50, time_bucket_ms=1000)
    if reason == "heatmap_specs_user":
        services = _services()
        _sub(_conn(services), *(_hm(s, depth=50, time_bucket_ms=1000) for s in SYMBOLS[:8]))
        return _conn(services), _hm(SYMBOLS[8], depth=50, time_bucket_ms=1000)
    if reason == "heatmap_specs_user_symbol":
        conn = _conn(_services())
        _sub(conn, _hm("BTCUSDT", price_grouping=2))
        _sub(_conn(conn.services), _hm("BTCUSDT", price_grouping=5))
        return _conn(conn.services), _hm("BTCUSDT", price_grouping=10)
    if reason == "points_connection":
        conn = _conn(_services())
        _sub(conn, _hm("BTCUSDT", **deep))
        return conn, _hm("ETHUSDT", **deep)
    if reason == "points_user":
        services = _services()
        for s in SYMBOLS[:2]:
            _sub(_conn(services), _hm(s, **deep))
        return _conn(services), _hm(SYMBOLS[2], **deep)
    if reason in {"heatmap_specs_symbol", "heatmap_specs_server", "points_server"}:
        caps = {"heatmap_specs_symbol": {"max_specs_per_symbol": 1},
                "heatmap_specs_server": {"max_specs_per_server": 1},
                "points_server": {"max_points_per_server": 13}}[reason]  # fmt: skip
        services = _services(**caps)
        _sub(_conn(services, user=2), _hm("BTCUSDT"))  # another user's spec: 13 points
        symbol = "BTCUSDT" if reason == "heatmap_specs_symbol" else "ETHUSDT"
        return _conn(services), _hm(symbol, price_grouping=2)
    raise AssertionError(reason)


#: Each reason's whole fixed message, at the caps `_scenario` gives it: the quota's own six, the
#: deep-book cap's and the producer's three, each naming its limit and remedy only (BQ-6's rider).
FIXED: dict[QuotaReason, str] = {
    **MESSAGES,
    "deep_book_connection": "At most 4 deep book subscriptions (depth 200 or more) per connection.",
    "heatmap_specs_symbol": "At most 1 heatmap specs per symbol are served.",
    "heatmap_specs_server": "At most 1 heatmap specs are served.",
    "points_server": (
        "The server's heatmap budget of 13 points is spent; use a slower bucket or a shallower "
        "depth."
    ),
}


def _counts() -> dict[str, float]:
    name = "cv_ws_subscription_quota_rejections_total"
    return {r: REGISTRY.get_sample_value(name, {"reason": r}) or 0.0 for r in REASONS}


@pytest.mark.parametrize("reason", REASONS)
def test_each_quota_refusal_counts_once_under_its_reason(reason: QuotaReason) -> None:
    conn, entry = _scenario(reason)
    before, held = _counts(), conn.services.user_quota.held(conn.actor_user_id)
    (refused,) = _sub(conn, entry)
    assert refused["error"]["code"] == "subscription_limit", refused
    assert conn.services.user_quota.held(conn.actor_user_id) == held  # it keeps no charge
    after = _counts()
    assert {r: after[r] - before[r] for r in REASONS} == {r: float(r == reason) for r in REASONS}
    assert set(FIXED) == set(REASONS)
    assert refused["error"]["message"] == FIXED[reason]  # the whole fixed text, nothing appended


def test_every_reason_series_exists_at_zero_from_import() -> None:
    assert set(_counts()) == set(REASONS) and all(v is not None for v in _counts().values())
    assert len(REASONS) == 10 and FAMILIES  # the closed set the catalogue caps at 10


def test_refusals_log_within_the_connections_refusal_log_budget() -> None:
    """One line per refusal up to the budget's 10 a window per reason, one `capped`, then none;
    each line names the connection, the acting user and the topic, never as a metric label."""
    quota = _quota(UserQuota())
    with capture_logs() as logs:
        for _ in range(12):
            quota.refused("points_connection", "heatmap.BTCUSDT", "c-1")
    lines = [e for e in logs if e["event"] == "ws subscription quota refused"]
    assert len(lines) == 11 and [e.get("capped") for e in lines] == [None] * 10 + [True]
    assert lines[0]["user_id"] == str(ALICE) and lines[0]["ch"] == "heatmap.BTCUSDT"
    assert lines[0]["connection_id"] == "c-1" and lines[0]["reason"] == "points_connection"


def test_a_ctl_moves_the_charge_and_the_drop_gives_back_the_new_one() -> None:
    """§5.4: a `ctl` that changes the weight moves the charge in the step that applies it; the
    subscription's end then gives back the weight it holds, once, however often it is dropped."""
    conn = _conn(_services())
    assert _sub(conn, _hm("BTCUSDT", depth=200, time_bucket_ms=1000))[0]["ok"]  # 7
    users = conn.services.user_quota
    assert users.held(conn.actor_user_id)[0] == conn.quota.points == 7
    _, resnapshot, sub = conn.ctl("heatmap.BTCUSDT", {"time_bucket_ms": 100})  # 63
    assert resnapshot and (sub.quota_points, conn.quota.points) == (63, 63)
    assert users.held(conn.actor_user_id)[:2] == (63, 1)
    conn.ctl("heatmap.BTCUSDT", {"throttle_ms": 50})  # 125: the throttle alone moves it too
    assert conn.quota.points == 125
    assert conn.unsubscribe("heatmap.BTCUSDT") is sub
    conn._drop(sub)  # #2896: a second drop of an ended subscription gives back nothing more
    assert (conn.quota.points, conn.quota.heatmaps, len(users)) == (0, 0, 0)
