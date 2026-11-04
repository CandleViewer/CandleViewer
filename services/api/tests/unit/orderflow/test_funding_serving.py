"""E24-S03 (#778) serving slice: `getFundingHistory`'s rate bounds, `annualised_pct` and
`meta.coverage`, through the real `FundingService`, the in-memory store and the real router, on
the recorded BTCUSDT settlements (`rest/funding_history_BTCUSDT_8h.json`) and instrument
(`rest/instruments_after.json`). Ruling 6612964585 Q4; 22 `getFundingHistory` / `FundingPageMeta`.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Any, cast

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.funding import make_funding_router
from candleviewer.domain.events import Instrument
from candleviewer.domain.funding import FundingSettlement, settle
from candleviewer.exchange.bybit.funding import parse_funding_page
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.orderflow import funding
from candleviewer.orderflow.funding import FundingService, FundingStore, TimeWindow
from candleviewer.storage.questdb.funding_store import InMemoryFundingStore
from tests._corpus import rest

_HISTORY = rest("rest/funding_history_BTCUSDT_8h.json")
NOW_S = _HISTORY["time"] / 1000  # the recording's own clock
NOW_US = int(NOW_S * 1_000_000)
_HOUR = 3_600 * 1_000_000
_SETTLED = sorted(parse_funding_page(_HISTORY, symbol="BTCUSDT"), key=lambda s: s.ts_us)
FIRST, LAST = _SETTLED[0].ts_us, _SETTLED[-1].ts_us


def _wire(drop: Sequence[str] = (), **over: object) -> dict[str, Any]:
    """The recorded BTCUSDT instrument; `drop` removes keys to stand for a reply without them
    (no recorded reply lacks a bound: fixture gap, see the PR), and `over` replaces a recorded
    value where a test says so (a later listing, a shorter interval)."""
    rows = rest("rest/instruments_after.json")["result"]["list"]
    wire: dict[str, Any] = copy.deepcopy(next(r for r in rows if r["symbol"] == "BTCUSDT"))
    for key in drop:
        wire.pop(key)
    return wire | over


def _instrument(drop: Sequence[str] = (), **over: object) -> Instrument:
    return parse_instrument(_wire(drop, **over), fetched_at_us=NOW_US)


@dataclass(frozen=True)
class _Tick:
    """The ticker's two funding fields the service reads; no rate held, only the next time."""

    next_funding_time: int | None
    funding_rate: Decimal | None = None
    ts_event: int = NOW_US


class _Tickers:
    def __init__(self, tick: _Tick | None) -> None:
        self.tick = tick

    def latest(self, symbol: str) -> _Tick | None:
        return self.tick


class _Fetcher:
    def __init__(self, rows: Sequence[FundingSettlement]) -> None:
        self.rows = sorted(rows, key=lambda r: -r.ts_us)

    async def __call__(
        self, symbol: str, start_us: int, end_us: int, limit: int
    ) -> list[FundingSettlement]:
        return [r for r in self.rows if start_us <= r.ts_us <= end_us][:limit]


def _service(
    store: InMemoryFundingStore,
    rows: Sequence[FundingSettlement] = _SETTLED,
    instrument: Instrument | None = None,
    next_us: int | None = None,
) -> FundingService:
    inst = instrument or _instrument()
    tickers = _Tickers(None if next_us is None else _Tick(next_us))
    return FundingService(
        store=cast("FundingStore", store),  # the in-memory store takes the concrete `TimeRange`
        fetcher=_Fetcher(rows),
        instruments=lambda s: inst,
        tickers=lambda: tickers,
        clock_s=lambda: NOW_S,
    )


async def _read(svc: FundingService, start: int, end: int = NOW_US, **kw: Any) -> Any:
    params: dict[str, Any] = {"start_us": start, "end_us": end, "limit": 100, "cursor": None}
    return await svc.series("BTCUSDT", **(params | kw))


async def test_the_bounds_come_from_instrument_info() -> None:
    series = await _read(_service(InMemoryFundingStore()), FIRST)
    wire = _wire()
    assert str(series.upper_funding_rate) == wire["upperFundingRate"]
    assert str(series.lower_funding_rate) == wire["lowerFundingRate"]
    assert series.funding_interval_minutes == wire["fundingInterval"]


async def test_a_bound_instrument_info_lacks_is_none_never_zero() -> None:
    inst = _instrument(drop=("upperFundingRate", "lowerFundingRate"))
    assert inst.upper_funding_rate is None and inst.lower_funding_rate is None
    series = await _read(_service(InMemoryFundingStore(), instrument=inst), FIRST)
    assert series.upper_funding_rate is None and series.lower_funding_rate is None


async def test_nothing_fetched_is_no_coverage_not_an_empty_covered_page() -> None:
    cov = (await _read(_service(InMemoryFundingStore()), FIRST - _HOUR)).coverage
    assert cov.no_coverage and cov.first_available_us is None
    assert (cov.covered_from_us, cov.covered_to_us, cov.gaps) == (None, None, ())


async def test_a_backfilled_window_is_covered_with_no_gap() -> None:
    svc = _service(store := InMemoryFundingStore())
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))
    series = await _read(svc, FIRST - _HOUR)
    cov = series.coverage
    assert not cov.no_coverage and cov.first_available_us == FIRST
    assert (cov.covered_from_us, cov.covered_to_us) == (FIRST - _HOUR, NOW_US)
    assert cov.gaps == () and len(series.settled) == len(store) == 4


async def test_a_missing_settlement_is_a_gap_between_its_stored_neighbours() -> None:
    kept = [s for i, s in enumerate(_SETTLED) if i != 1]
    svc = _service(InMemoryFundingStore(), rows=kept)
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))
    cov = (await _read(svc, FIRST - _HOUR)).coverage
    assert cov.gaps == ((_SETTLED[0].ts_us, _SETTLED[2].ts_us),)


async def test_a_covered_window_before_the_listing_is_covered_and_empty() -> None:
    listed = _instrument().launch_time
    window = TimeWindow(listed - 48 * _HOUR, listed - _HOUR)
    svc = _service(InMemoryFundingStore(), rows=[])
    await svc.backfill("BTCUSDT", window)
    series = await _read(svc, window.start_us, window.end_us)
    assert series.settled == () and not series.coverage.no_coverage
    assert series.coverage.gaps == ()  # nothing was due before the listing


async def test_the_stored_extent_alone_answers_after_a_restart() -> None:
    store = InMemoryFundingStore()
    await _service(store).backfill("BTCUSDT", TimeWindow(FIRST, NOW_US))
    cov = (await _read(_service(store), FIRST - 10 * _HOUR)).coverage  # a fresh process
    assert (cov.covered_from_us, cov.covered_to_us) == (FIRST, LAST)


async def test_a_disjoint_older_backfill_keeps_the_fresher_span() -> None:
    svc = _service(InMemoryFundingStore())
    await svc.backfill("BTCUSDT", TimeWindow(LAST, NOW_US))  # stores LAST only
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - 99 * _HOUR, FIRST - 98 * _HOUR))  # older
    cov = (await _read(svc, FIRST - 100 * _HOUR)).coverage
    # Had the older window replaced the fresher one, the covered part would start at it.
    assert (cov.covered_from_us, cov.covered_to_us) == (LAST, NOW_US)


async def test_a_page_capped_backfill_covers_only_what_it_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(funding, "PAGE_LIMIT", 1)
    monkeypatch.setattr(funding, "MAX_PAGES_PER_RUN", 2)
    svc = _service(InMemoryFundingStore())
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))  # fetches the two newest
    cov = (await _read(svc, FIRST - _HOUR)).coverage
    assert (cov.covered_from_us, cov.covered_to_us) == (_SETTLED[2].ts_us, NOW_US)


@pytest.mark.parametrize("first_stored", [True, False])
async def test_the_listing_bounds_a_gap_as_a_stored_settlement_does(first_stored: bool) -> None:
    """The window spans the listing, an hour before the first settlement (`launchTime` replaced)."""
    listed_us = FIRST - _HOUR
    inst = _instrument(launchTime=str(listed_us // 1000))
    rows = _SETTLED if first_stored else _SETTLED[1:]
    svc = _service(InMemoryFundingStore(), rows=rows, instrument=inst)
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - 10 * _HOUR, NOW_US))
    cov = (await _read(svc, FIRST - 10 * _HOUR)).coverage
    assert cov.covered_from_us == FIRST - 10 * _HOUR  # covered before the listing, nothing due
    expected = () if first_stored else ((listed_us, _SETTLED[1].ts_us),)
    assert cov.gaps == expected


async def test_gaps_joined_across_pages_equal_the_one_shot_answer() -> None:
    """Gaps are listed within each page's span (22): resuming after the cursor's settlement, an
    open tail while `has_more`; a client joining the pages' lists has the one-shot list."""
    step = 8 * _HOUR
    due = [FIRST - 48 * _HOUR + i * step for i in range(10)]
    kept = [FundingSettlement(t, "BTCUSDT", Decimal("0.0001")) for i, t in enumerate(due)
            if i not in (1, 4, 5, 8)]  # fmt: skip
    assert len(kept) == 6
    svc = _service(InMemoryFundingStore(), rows=kept)
    start = due[0] - _HOUR
    await svc.backfill("BTCUSDT", TimeWindow(start, NOW_US))
    one_shot = (await _read(svc, start)).coverage.gaps
    paged: list[tuple[int, int]] = []
    cursor, pages = None, 0
    while True:
        series = await _read(svc, start, limit=2, cursor=cursor)
        paged.extend(series.coverage.gaps)
        pages += 1
        if not series.has_more:
            break
        cursor = series.next_cursor
    assert pages == 3 and len(one_shot) == 3
    assert tuple(paged) == one_shot


async def test_after_an_interval_shortening_the_older_history_reads_as_gaps() -> None:
    """24 §19.110 (PROPOSED as accepted): gaps are judged on the current interval, on the grid of
    the ticker's next settlement. The recorded 8 h history under a 4 h interval (`fundingInterval`
    replaced) reads as a gap between each pair, and since the last one."""
    inst = _instrument(fundingInterval=240)
    svc = _service(InMemoryFundingStore(), instrument=inst, next_us=LAST + 8 * _HOUR)
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))
    cov = (await _read(svc, FIRST - _HOUR)).coverage
    edges = [s.ts_us for s in _SETTLED]
    assert cov.gaps == (*pairwise(edges), (LAST, NOW_US))


async def test_a_settled_item_is_annualised_at_the_responses_interval() -> None:
    """22 (C-6.1): `funding_interval_minutes` of the response, not the row's stamped interval."""
    store = InMemoryFundingStore()
    await store.write_settled([settle("BTCUSDT", FIRST, Decimal("0.0001"), 240)])
    body = (
        _client(_service(store), frozenset({"marketdata:read"}))
        .get("/market/funding", params={"symbol": "BTCUSDT", "from": "2023-11-13T00:00:00Z"})
        .json()
    )
    assert body["funding_interval_minutes"] == 480
    assert [i["annualised_pct"] for i in body["items"]] == ["10.95"]  # not 21.9 (240 min)


# --- the router -------------------------------------------------------------------------------


@dataclass
class _Principal:
    perms: frozenset[str]

    def has(self, permission: str) -> bool:
        return permission in self.perms


class _Resolver:
    def __init__(self, principal: _Principal | None) -> None:
        self.principal = principal

    def resolve(self, request: Request) -> _Principal | None:
        return self.principal


def _client(svc: FundingService, perms: frozenset[str]) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_funding_router(lambda: svc, principal_resolver=_Resolver(_Principal(perms)))
    )
    return TestClient(app)


def _schema() -> tuple[Any, Any]:
    spec: Any = load_openapi_spec()
    op = spec["paths"]["/market/funding"]["get"]["responses"]["200"]["content"]
    return spec, op["application/json"]["schema"]


async def test_the_served_answer_conforms_to_22_and_carries_every_new_member() -> None:
    kept = [s for i, s in enumerate(_SETTLED) if i != 1]
    svc = _service(InMemoryFundingStore(), rows=kept)
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))
    params = {"symbol": "BTCUSDT", "from": "2023-11-13T12:00:00Z", "to": "2023-11-15T06:33:20Z"}
    response = _client(svc, frozenset({"marketdata:read"})).get("/market/funding", params=params)
    assert response.status_code == 200
    body = response.json()
    spec, schema = _schema()
    jsonschema.validate(body, {**schema, "components": spec["components"]})
    assert (body["upper_funding_rate"], body["lower_funding_rate"]) == ("0.00375", "-0.00375")
    assert [i["annualised_pct"] for i in body["items"]] == ["13.14", "8.76", "10.95"]
    cov = body["meta"]["coverage"]
    assert cov["no_coverage"] is False and cov["first_available_ts"] == "2023-11-14T00:00:00Z"
    assert cov["gaps"] == [{"from": "2023-11-14T00:00:00Z", "to": "2023-11-14T16:00:00Z"}]


async def test_a_bound_is_served_null_and_an_unrecorded_window_no_coverage() -> None:
    inst = _instrument(drop=("upperFundingRate",))
    svc = _service(InMemoryFundingStore(), instrument=inst)
    body = (
        _client(svc, frozenset({"marketdata:read"}))
        .get("/market/funding", params={"symbol": "BTCUSDT"})
        .json()
    )
    assert body["upper_funding_rate"] is None and body["lower_funding_rate"] == "-0.00375"
    assert body["items"] == [] and body["meta"]["coverage"]["no_coverage"] is True
    spec, schema = _schema()
    jsonschema.validate(body, {**schema, "components": spec["components"]})


def test_a_caller_without_marketdata_read_is_refused_before_any_read() -> None:
    svc = _service(InMemoryFundingStore())
    response = _client(svc, frozenset({"positions:read"})).get(
        "/market/funding", params={"symbol": "BTCUSDT"}
    )
    assert response.status_code == 403 and response.json()["code"] == "forbidden"
    assert "upper_funding_rate" not in response.text


async def test_the_generated_model_reads_the_served_meta() -> None:
    svc = _service(InMemoryFundingStore())
    await svc.backfill("BTCUSDT", TimeWindow(FIRST - _HOUR, NOW_US))
    body = (
        _client(svc, frozenset({"marketdata:read"}))
        .get("/market/funding", params={"symbol": "BTCUSDT"})
        .json()
    )
    meta = api.FundingPageMeta.model_validate(body["meta"])
    assert meta.coverage is not None and meta.coverage.no_coverage is False
