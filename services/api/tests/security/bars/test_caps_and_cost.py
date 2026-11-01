"""E12-X02 caps and cost (#452; X01 AC-01, AC-02, AC2; SR-E12-01/02/03): each cap at its boundary
on `/market/bars` and `/market/klines`, every refusal made before the storage call it protects,
and a refusal's cost bounded. The `stores` spies give each refusal's exact call set: none for
`tick:1`, `limit`, the param bounds and authz; one recording-start read for the cap refusals of
`/market/bars` (`market_bars.py` reads it before the window check, for every bar type), plus the
print count for the non-time estimate refusal; none for the klines window refusal.

The numbers are written out as X01 §7 states them, so a constant changed in the code cannot move
the number under test (`test_caps_match_model` ties them to the model). The `check_*` helpers are
the defended outcomes; `test_negative_controls` runs them with each defence removed.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from typing import Final

import httpx
import pytest

from candleviewer.api import market, market_bars
from candleviewer.bars.errors import BarParamOutOfRange
from candleviewer.bars.models import BarSpec
from candleviewer.bars.spec import check_param_bounds
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
from tests.security.bars.conftest import BAR_READ, HOT_READ, RECORDING, TOTALS, Stores

DAY_US: Final = 86_400_000_000
MIN_US: Final = 60_000_000
TIME_DAYS, NON_TIME_DAYS, MAX_BARS, MAX_LIMIT = 400, 31, 250_000, 5_000
#: #452 BQ-5, proposed into X01 §3 as SR-E12-01's rejection-cost bound: the median CPU time one
#: refused `tick:1` request adds over a 401, in process. The one place the number lives.
REJECTION_CPU_BUDGET_S: Final = 0.002
F1: Final = "#452 findings row F1: a pre-epoch `from` is measured from the epoch, not from `from`"
F3: Final = "#452 findings row F3: no per-user rate limit or single-flight on the REST bar reads"
F8: Final = (
    "#452 findings row F8: the applied floor is 1 for qty_step < 0.1; the documented 10 x qty_step"
    " floor is unreachable over the integer wire grammar"
)


def bars(bar_type: str, param: str, from_us: int, to_us: int, **extra: object) -> dict[str, object]:
    q = {"symbol": "BTCUSDT", "bar_type": bar_type, "param": param, "limit": 10}
    return {**q, "from": _iso(from_us), "to": _iso(to_us), **extra}


def klines(from_us: int, to_us: int, **extra: object) -> dict[str, object]:
    q = {"symbol": "BTCUSDT", "interval": "D", "limit": 10, "from": _iso(from_us)}
    return {**q, "to": _iso(to_us), **extra}


def assert_problem(resp: httpx.Response, status: int, code: str) -> None:
    assert (resp.status_code, resp.json().get("code")) == (status, code), resp.text[:300]


def refusal_calls(
    stores: Stores, op: str, query: dict[str, object], status: int, code: str
) -> Counter[str]:
    """The storage calls one refused request made (`Counter` subtraction drops the zeros)."""
    before = stores.calls.copy()
    assert_problem(stores.get(op, query), status, code)
    return stores.calls - before


_CAP: Final = (422, "bar_window_too_large")
#: A cap refusal of /market/bars reads the recording start first, and only that (m1).
_RECORDING_ONLY: Final = Counter({RECORDING: 1})


# -- defended outcomes, reused by the negative controls --------------------------------------


def check_time_window_cap(stores: Stores) -> None:
    """400 d of daily time bars is served; 1 µs more is 422, after the recording-start read
    only."""
    start = NOW - TIME_DAYS * DAY_US
    assert stores.get("getBars", bars("time", "D", start, NOW)).status_code == 200
    over = bars("time", "D", start - 1, NOW)
    assert refusal_calls(stores, "getBars", over, *_CAP) == _RECORDING_ONLY


def check_time_estimate_cap(stores: Stores) -> None:
    """250 000 one-minute bars is served; a window one µs wider estimates 250 001: 422, after
    the recording-start read only."""
    start = NOW - MAX_BARS * MIN_US
    assert stores.get("getBars", bars("time", "1", start, NOW)).status_code == 200
    over = bars("time", "1", start - 1, NOW)
    assert refusal_calls(stores, "getBars", over, *_CAP) == _RECORDING_ONLY


def check_non_time_window_cap(stores: Stores) -> None:
    """31 d of tick bars from the recording start is served; 1 µs more is 422 before the print
    count and the bar read (the window check precedes both; the recording start precedes it)."""
    end = T0 + NON_TIME_DAYS * DAY_US
    assert stores.get("getBars", bars("tick", "100", T0, end)).status_code == 200
    over = bars("tick", "100", T0, end + 1)
    assert refusal_calls(stores, "getBars", over, *_CAP) == _RECORDING_ONLY


def check_estimate_cap(stores: Stores) -> None:
    """A tick:100 window whose stored prints make 250 001 bars is 422 after the recording start
    and the print count, with no bar read; one that makes 250 000 is read."""
    prints = [MAX_BARS * 100 + 100, MAX_BARS * 100]

    async def totals() -> TradeTotals:
        return TradeTotals(prints.pop(0), Decimal(0))

    stores.faults[TOTALS] = totals
    query = bars("tick", "100", T0, NOW)
    assert refusal_calls(stores, "getBars", query, *_CAP) == Counter({RECORDING: 1, TOTALS: 1})
    assert stores.get("getBars", query).status_code == 200
    assert stores.calls[BAR_READ] == 1


def check_limit_over_max_refused(stores: Stores) -> None:
    """`limit` 5001 is refused on both routes before any storage call."""
    for op, query in (
        ("getBars", bars("tick", "100", T0, NOW, limit=MAX_LIMIT + 1)),
        ("getKlines", klines(KLINES_NOW_US - DAY_US, KLINES_NOW_US, limit=MAX_LIMIT + 1)),
    ):
        assert stores.get(op, query).status_code in (400, 422), op
    assert stores.calls == Counter()


def check_tick_1_refused_before_any_read(stores: Stores) -> None:
    """X01 AC-02 / #452 AC2: `tick:1` over 30 d is 400 `validation_failed` naming the bound, and
    no storage call is made (no recording start, no print count, no bar read)."""
    resp = stores.get("getBars", bars("tick", "1", NOW - 30 * DAY_US, NOW))
    assert_problem(resp, 400, "validation_failed")
    assert "100" in resp.json()["detail"]
    assert stores.calls == Counter()


#: The lowered ceiling the probe page exceeds (`_market_world.response_ceiling`).
CEILING_PROBE_BYTES: Final = 2_048


def check_response_ceiling(stores: Stores) -> None:
    """A page over the 2 MiB ceiling (lowered, so recorded data exceeds it) is 422
    `response_too_large`, a Problem and never a truncated page."""
    with response_ceiling(CEILING_PROBE_BYTES):
        resp = stores.get("getBars", bars("time", "1", T0, NOW, limit=MAX_LIMIT))
    assert_problem(resp, 422, "response_too_large")
    assert "bars" not in resp.json()


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
        check_response_ceiling,
    ],
)
def test_caps_boundary_holds_and_refuses_before_the_read(
    stores: Stores, check: Callable[[Stores], None]
) -> None:
    check(stores)


@pytest.mark.parametrize(
    ("op", "query", "tiers"),
    [
        ("getBars", bars("time", "1", T0, NOW), {RECORDING, BAR_READ}),
        ("getBars", bars("tick", "100", T0, NOW), {RECORDING, TOTALS, BAR_READ}),
        ("getKlines", klines(KLINES_NOW_US - DAY_US, KLINES_NOW_US, interval="1"),
         {HOT_READ, RECORDING}),
    ],
)  # fmt: skip
def test_caps_served_request_reaches_only_the_spied_tiers(
    stores: Stores, op: str, query: dict[str, object], tiers: set[str]
) -> None:
    """Guard on the spies: a served read of each kind reaches exactly the tiers the suite counts,
    so a "no storage call" assertion cannot pass because a read went to an unspied callable."""
    assert stores.get(op, query).status_code == 200
    assert set(stores.calls) == tiers, stores.calls


def test_caps_klines_window_over_400_days_refused_before_the_hot_read(stores: Stores) -> None:
    start = KLINES_NOW_US - TIME_DAYS * DAY_US
    assert stores.get("getKlines", klines(start, KLINES_NOW_US)).status_code == 200
    assert stores.calls[HOT_READ] >= 1  # the served window reads: the refusal below does not
    over = klines(start - 1, KLINES_NOW_US)
    assert refusal_calls(stores, "getKlines", over, *_CAP) == Counter()


def test_caps_klines_page_over_the_response_ceiling_is_refused_never_truncated(
    stores: Stores,
) -> None:
    query = klines(KLINES_NOW_US - 3 * DAY_US, KLINES_NOW_US, interval="1", limit=MAX_LIMIT)
    with response_ceiling(CEILING_PROBE_BYTES):
        resp = stores.get("getKlines", query)
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
    assert stores.calls == Counter()  # before the recording start, the count and the read


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
    """#452 BQ-5: the added cost over an unauthenticated refusal, the median CPU time a refused
    `tick:1` request adds over a 401 (no session, no parse) through the same in-process client,
    is within the budget. The
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
    assert stores.calls == Counter()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=F1)
def test_caps_pre_epoch_window_is_measured_from_its_from(stores: Stores) -> None:
    """X01 AC-01: `from=1900-01-01 to=1970-06-01` spans about 70 years, over the 400-day cap. The
    route measures it from 1970-01-01 (`max(start_us, after_us + 1)` with no cursor), so it serves
    it and reads storage over the whole window."""
    query = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1", "limit": 10,
             "from": "1900-01-01T00:00:00Z", "to": "1970-06-01T00:00:00Z"}  # fmt: skip
    assert_problem(stores.get("getBars", query), 422, "bar_window_too_large")
    assert stores.calls[BAR_READ] == 0


#: ISO 8601 forms that are not RFC 3339, per field, each later than the window's other end.
_LENIENT: Final = [
    ("from", "2023-11-14"), ("from", "20231114T220000Z"), ("from", "2023-W46-2T22:00:00Z"),
    ("to", "2023-11-15"), ("to", "20231115T060000Z"), ("to", "2023-W46-3T06:00:00Z"),
]  # fmt: skip


@pytest.mark.parametrize(("field", "value"), _LENIENT)
@pytest.mark.parametrize("op", ["getBars", "getKlines"])
def test_caps_non_rfc_3339_time_is_served_accepted_f6(
    stores: Stores, op: str, field: str, value: str
) -> None:
    """#452 F6, accepted by the coordinator; X01 note: `datetime.fromisoformat` takes a superset
    of RFC 3339 (date-only, basic format, week dates) and the superset is harmless, so a `from`
    or `to` in those forms is served. Pinned so a stricter parser is a reviewed change."""
    start = 1_699_833_600_000_000  # 2023-11-13T00:00:00Z: before every `to` above
    query = bars("time", "1", start, NOW) if op == "getBars" else klines(start, KLINES_NOW_US)
    assert stores.get(op, {**query, field: value}).status_code == 200


#: `_LENIENT`'s values as the instant both routes' parsers give them (UTC µs).
_INSTANTS: Final = {
    "2023-11-14": 1_699_920_000_000_000, "20231114T220000Z": 1_699_999_200_000_000,
    "2023-W46-2T22:00:00Z": 1_699_999_200_000_000, "2023-11-15": 1_700_006_400_000_000,
    "20231115T060000Z": 1_700_028_000_000_000, "2023-W46-3T06:00:00Z": 1_700_028_000_000_000,
}  # fmt: skip


@pytest.mark.parametrize(("field", "value"), _LENIENT)
def test_caps_non_rfc_3339_time_parses_to_its_instant_accepted_f6(field: str, value: str) -> None:
    """#452 F6, accepted by the coordinator; X01 note: the accepted forms are not only served but
    read as the instant they name (a date-only value is its UTC midnight), by the parser each route
    calls for `from` and `to` alike (`market_bars._ts_us`, `market._parse_time`)."""
    klines_at = market._parse_time(value, default=None)
    assert klines_at is not None, field
    assert market_bars._ts_us(value) == _INSTANTS[value]
    assert int(klines_at.timestamp() * 1_000_000) == _INSTANTS[value]


@pytest.mark.xfail(strict=True, raises=BarParamOutOfRange, reason=F8)
@pytest.mark.parametrize(
    ("kind", "field"), [("volume", "volume_threshold"), ("delta", "delta_threshold")]
)
def test_caps_qty_floor_is_ten_qty_steps(kind: str, field: str) -> None:
    """X01 §7 SR-E12-03: `volume`/`delta` floor at 10 x the symbol's `qty_step`, for BTCUSDT
    0.01. The wire grammar takes whole numbers only (no dot), and `check_param_bounds` also floors
    both kinds at the integer 1, so below a `qty_step` of 0.1 the documented floor is never the one
    applied: a spec at exactly 10 qty steps is refused."""
    spec = BarSpec.model_validate({"kind": kind, field: Decimal("0.01")})
    check_param_bounds(spec, kind, qty_step=Decimal("0.001"))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=F3)
def test_caps_one_session_looping_maximal_pages_is_throttled(stores: Stores) -> None:
    """BR-36: one session looping `limit=5000` pages serialises every other session's reads behind
    its own on the `bars` pgwire lock. 60 back-to-back pages in one burst meet no 429; the fix is
    contract-first (22-api declares no 429 on getBars/getKlines)."""
    query = bars("time", "1", T0, NOW, limit=MAX_LIMIT)
    statuses = [stores.get("getBars", query).status_code for _ in range(60)]
    assert 429 in statuses
    assert stores.calls[BAR_READ] < 60
