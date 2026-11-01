"""E12-X02 caps and cost (#452; X01 AC-01, AC-02, AC2; SR-E12-01/02/03): each cap at its boundary
on `/market/bars` and `/market/klines`, every refusal made before the storage call it protects
(the `stores` spies count them), and a refusal's cost bounded.

The numbers are written out as X01 §7 states them, so a constant changed in the code cannot move
the number under test (`test_caps_match_model` ties them to the model). The `check_*` helpers are
the defended outcomes; `test_negative_controls` runs them with each defence removed.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Final

import httpx
import pytest

from candleviewer.storage.repositories.rows import TradeTotals
from tests.contract._market_world import (
    KLINES_NOW_US,
    NO_SESSION,
    NOW,
    READER,
    T0,
    response_ceiling,
)
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars.conftest import BAR_READ, HOT_READ, TOTALS, Stores

DAY_US: Final = 86_400_000_000
MIN_US: Final = 60_000_000
TIME_DAYS, NON_TIME_DAYS, MAX_BARS, MAX_LIMIT = 400, 31, 250_000, 5_000
#: #452 BQ-5, proposed into X01 §3 as SR-E12-01's rejection-cost bound: the median CPU time one
#: refused `tick:1` request adds over a 401, in process. The one place the number lives.
REJECTION_CPU_BUDGET_S: Final = 0.002
F1: Final = "#452 findings row F1: a pre-epoch `from` is measured from the epoch, not from `from`"
F3: Final = "#452 findings row F3: no per-user rate limit or single-flight on the REST bar reads"
F6: Final = "#452 findings row F6: from/to accept ISO 8601 forms that are not RFC 3339"


def bars(bar_type: str, param: str, from_us: int, to_us: int, **extra: object) -> dict[str, object]:
    q = {"symbol": "BTCUSDT", "bar_type": bar_type, "param": param, "limit": 10}
    return {**q, "from": _iso(from_us), "to": _iso(to_us), **extra}


def klines(from_us: int, to_us: int, **extra: object) -> dict[str, object]:
    q = {"symbol": "BTCUSDT", "interval": "D", "limit": 10, "from": _iso(from_us)}
    return {**q, "to": _iso(to_us), **extra}


def assert_problem(resp: httpx.Response, status: int, code: str) -> None:
    assert (resp.status_code, resp.json().get("code")) == (status, code), resp.text[:300]


# -- defended outcomes, reused by the negative controls --------------------------------------


def check_time_window_cap(stores: Stores) -> None:
    """400 d of daily time bars is served; 1 µs more is 422 before any bar read."""
    start = NOW - TIME_DAYS * DAY_US
    assert stores.get("getBars", bars("time", "D", start, NOW)).status_code == 200
    reads = stores.calls[BAR_READ]
    over = stores.get("getBars", bars("time", "D", start - 1, NOW))
    assert_problem(over, 422, "bar_window_too_large")
    assert stores.calls[BAR_READ] == reads


def check_time_estimate_cap(stores: Stores) -> None:
    """250 000 one-minute bars is served; a window one µs wider estimates 250 001: 422, no read."""
    start = NOW - MAX_BARS * MIN_US
    assert stores.get("getBars", bars("time", "1", start, NOW)).status_code == 200
    reads = stores.calls[BAR_READ]
    assert_problem(stores.get("getBars", bars("time", "1", start - 1, NOW)), 422,
                   "bar_window_too_large")  # fmt: skip
    assert stores.calls[BAR_READ] == reads


def check_non_time_window_cap(stores: Stores) -> None:
    """31 d of tick bars from the recording start is served; 1 µs more is 422 before the print
    count and the bar read (the window check precedes both)."""
    end = T0 + NON_TIME_DAYS * DAY_US
    assert stores.get("getBars", bars("tick", "100", T0, end)).status_code == 200
    before = (stores.calls[TOTALS], stores.calls[BAR_READ])
    assert_problem(stores.get("getBars", bars("tick", "100", T0, end + 1)), 422,
                   "bar_window_too_large")  # fmt: skip
    assert (stores.calls[TOTALS], stores.calls[BAR_READ]) == before


def check_estimate_cap(stores: Stores) -> None:
    """A tick:100 window whose stored prints make 250 001 bars is 422 with no bar read; one that
    makes 250 000 is read."""
    prints = [MAX_BARS * 100 + 100, MAX_BARS * 100]

    async def totals() -> TradeTotals:
        return TradeTotals(prints.pop(0), Decimal(0))

    stores.faults[TOTALS] = totals
    assert_problem(stores.get("getBars", bars("tick", "100", T0, NOW)), 422, "bar_window_too_large")
    assert stores.calls[BAR_READ] == 0
    assert stores.get("getBars", bars("tick", "100", T0, NOW)).status_code == 200
    assert stores.calls[BAR_READ] == 1


def check_limit_over_max_refused(stores: Stores) -> None:
    """`limit` 5001 is refused on both routes before any storage call."""
    for op, query in (
        ("getBars", bars("tick", "100", T0, NOW, limit=MAX_LIMIT + 1)),
        ("getKlines", klines(KLINES_NOW_US - DAY_US, KLINES_NOW_US, limit=MAX_LIMIT + 1)),
    ):
        assert stores.get(op, query).status_code in (400, 422), op
    assert stores.total() == 0


def check_tick_1_refused_before_any_read(stores: Stores) -> None:
    """X01 AC-02 / #452 AC2: `tick:1` over 30 d is 400 `validation_failed` naming the bound, and
    no storage call is made (no recording start, no print count, no bar read)."""
    resp = stores.get("getBars", bars("tick", "1", NOW - 30 * DAY_US, NOW))
    assert_problem(resp, 400, "validation_failed")
    assert "100" in resp.json()["detail"]
    assert stores.total() == 0


# -- the cases ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check",
    [
        check_time_window_cap,
        check_time_estimate_cap,
        check_non_time_window_cap,
        check_estimate_cap,
        check_limit_over_max_refused,
        check_tick_1_refused_before_any_read,
    ],
)
def test_caps_boundary_holds_and_refuses_before_the_read(
    stores: Stores, check: Callable[[Stores], None]
) -> None:
    check(stores)


def test_caps_klines_window_over_400_days_refused_before_the_hot_read(stores: Stores) -> None:
    start = KLINES_NOW_US - TIME_DAYS * DAY_US
    assert stores.get("getKlines", klines(start, KLINES_NOW_US)).status_code == 200
    reads = stores.calls[HOT_READ]
    over = stores.get("getKlines", klines(start - 1, KLINES_NOW_US))
    assert_problem(over, 422, "bar_window_too_large")
    assert stores.calls[HOT_READ] == reads


@pytest.mark.parametrize("op", ["getBars", "getKlines"])
def test_caps_page_over_the_response_ceiling_is_refused_never_truncated(
    stores: Stores, op: str
) -> None:
    query = (
        bars("time", "1", T0, NOW, limit=MAX_LIMIT)
        if op == "getBars"
        else klines(KLINES_NOW_US - 3 * DAY_US, KLINES_NOW_US, interval="1", limit=MAX_LIMIT)
    )
    with response_ceiling(2_048):
        resp = stores.get(op, query)
    assert_problem(resp, 422, "response_too_large")
    assert "bars" not in resp.json()


#: SR-E12-03 at each floor and ceiling (X01 §7): `(bar_type, param, served)`.
_BOUNDS: Final = [
    ("tick", "99", False), ("tick", "100", True), ("tick", "1000000", True),
    ("tick", "1000001", False), ("range", "1", False), ("range", "2", True),
    ("range", "100000", True), ("range", "100001", False), ("renko", "1", False),
    ("renko", "2", True), ("renko", "100000", True), ("renko", "100001", False),
    ("volume", "0.009", False), ("volume", "1", True), ("volume", "1000000000000", True),
    ("volume", "1000000000001", False), ("delta", "0.009", False), ("delta", "1", True),
    ("delta", "1000000000001", False), ("tick", "9" * 18, False), ("tick", "9" * 19, False),
]  # fmt: skip


@pytest.mark.parametrize(("bar_type", "param", "served"), _BOUNDS)
def test_caps_param_bound_is_enforced_at_its_edge_on_rest(
    stores: Stores, bar_type: str, param: str, served: bool
) -> None:
    resp = stores.get("getBars", bars(bar_type, param, T0, NOW))
    if served:
        assert resp.status_code == 200, resp.text[:300]
        return
    assert_problem(resp, 400, "validation_failed")
    assert stores.total() == 0  # refused before the recording start, the count and the read


def test_caps_param_bound_is_enforced_on_the_ws_subscribe_path(wire: str) -> None:
    """The WS `sub` shares `check_param_bounds` (#2709): below a floor is `invalid_topic_format`,
    and no lease is taken for it."""
    from tests.contract.ws import _harness as h
    from tests.contract.ws.test_ws_bars_contract import _Rig

    rig = _Rig({})
    topics = ("bars.BTCUSDT.tick.99", "bars.BTCUSDT.range.1", "bars.BTCUSDT.tick.100")
    with h.connect(rig.w) as c:
        results = c.sub(*topics)["p"]["results"]
    assert [r["ok"] for r in results] == [False, False, True]
    assert {r["error"]["code"] for r in results[:2]} == {"invalid_topic_format"}
    assert len(rig.leases.registered) == 1


@pytest.mark.perf
def test_caps_tick_1_refusal_costs_under_the_cpu_budget(stores: Stores) -> None:
    """#452 BQ-5: the median CPU time a refused `tick:1` request adds over the cheapest refusal
    through the same in-process client (no session: 401, no parse) is within the budget. The
    harness's own cost (about 5 ms a round trip here) is the floor both share; medians of 200
    interleaved pairs, since the VPS is shared. The primary signal is structural: no storage call.
    """
    query = bars("tick", "1", NOW - 30 * DAY_US, NOW)
    costs: dict[bool, list[float]] = {True: [], False: []}
    for n in range(402):
        hostile = n % 2 == 0
        began = time.process_time()
        stores.get("getBars", query, READER if hostile else NO_SESSION)
        if n >= 2:  # the first pair warms the route
            costs[hostile].append(time.process_time() - began)
    added = statistics.median(costs[True]) - statistics.median(costs[False])
    assert added <= REJECTION_CPU_BUDGET_S, (added, statistics.median(costs[False]))
    assert stores.total() == 0


@pytest.mark.xfail(strict=True, reason=F1)
def test_caps_pre_epoch_window_is_measured_from_its_from(stores: Stores) -> None:
    """X01 AC-01: `from=1900-01-01 to=1970-06-01` spans about 70 years, over the 400-day cap. The
    route measures it from 1970-01-01 (`max(start_us, after_us + 1)` with no cursor), so it serves
    it and reads storage over the whole window."""
    query = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1", "limit": 10,
             "from": "1900-01-01T00:00:00Z", "to": "1970-06-01T00:00:00Z"}  # fmt: skip
    assert_problem(stores.get("getBars", query), 422, "bar_window_too_large")
    assert stores.calls[BAR_READ] == 0


@pytest.mark.xfail(strict=True, reason=F6)
@pytest.mark.parametrize("value", ["2023-11-14", "20231114T220000Z", "2023-W46-2T22:00:00Z"])
@pytest.mark.parametrize("op", ["getBars", "getKlines"])
def test_caps_from_that_is_not_rfc_3339_is_refused(stores: Stores, op: str, value: str) -> None:
    query = (
        bars("time", "1", T0, NOW)
        if op == "getBars"
        else klines(KLINES_NOW_US - DAY_US, KLINES_NOW_US)
    )
    assert_problem(stores.get(op, {**query, "from": value}), 400, "validation_failed")


@pytest.mark.xfail(strict=True, reason=F3)
def test_caps_one_session_looping_maximal_pages_is_throttled(stores: Stores) -> None:
    """BR-36: one session looping `limit=5000` pages serialises every other session's reads behind
    its own on the `bars` pgwire lock. 60 back-to-back pages in one burst meet no 429; the fix is
    contract-first (22-api declares no 429 on getBars/getKlines)."""
    query = bars("time", "1", T0, NOW, limit=MAX_LIMIT)
    statuses = [stores.get("getBars", query).status_code for _ in range(60)]
    assert 429 in statuses
    assert stores.calls[BAR_READ] < 60
