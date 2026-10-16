"""Unit tests for the instrument catalogue core (E08-S01 Gherkin AC):
- "Refresh without restart" (unknown-symbol / TTL refresh)
- "Delisted symbol" (listing exclusion + detail flag)
- "Tick size changes" (version bump + event, incl. no-op when unchanged)
- "Refresh fails" (stale-since)
- "Refresh does not stall readers" (atomic swap)

Bybit-payload parsing itself is tested in
`tests/unit/exchange/bybit/test_instruments.py` (C-2.2: this module never
sees a raw Bybit field name, so its tests build fixtures via
`candleviewer.exchange.bybit.instruments.parse_instrument` only as a
convenient `Instrument` factory).
"""

from __future__ import annotations

import copy
from uuid import uuid4

from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.ingestion.instruments import (
    CatalogueSnapshot,
    InstrumentCatalogueCache,
    build_updated_event,
    diff_changed_fields,
    next_version,
)

_RAW_BTCUSDT = {
    "symbol": "BTCUSDT",
    "baseCoin": "BTC",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "status": "Trading",
    "launchTime": "1585STUB",  # replaced per-test where needed
    "priceScale": "2",
    "priceFilter": {"tickSize": "0.10", "minPrice": "0.10", "maxPrice": "999999.00"},
    "lotSizeFilter": {
        "qtyStep": "0.001",
        "minOrderQty": "0.001",
        "maxOrderQty": "100.000",
        "maxMktOrderQty": "50.000",
        "minNotionalValue": "5",
    },
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
    "fundingInterval": 480,
    "upperFundingRate": "0.00375",
    "lowerFundingRate": "-0.00375",
    "copyTrading": "utaOnly",
}


def _raw(**overrides: object) -> dict[str, object]:
    raw = copy.deepcopy({k: v for k, v in _RAW_BTCUSDT.items() if k != "launchTime"})
    raw["launchTime"] = "1585699200000"
    raw.update(overrides)
    return raw


# --- version-bump / no-op / event (Gherkin "Tick size changes") -----------


def test_next_version_starts_new_symbol_at_metadata_version_1() -> None:
    parsed = parse_instrument(_raw(), fetched_at_us=1)
    versioned, changed = next_version(None, parsed)
    assert versioned.metadata_version == 1
    assert changed == ()


def test_next_version_bumps_on_tick_size_change_and_reports_it() -> None:
    previous = parse_instrument(_raw(), fetched_at_us=1)
    changed_raw = _raw()
    changed_raw["priceFilter"]["tickSize"] = "0.50"  # type: ignore[index]
    parsed = parse_instrument(changed_raw, fetched_at_us=2)

    versioned, changed = next_version(previous, parsed)

    assert versioned.metadata_version == previous.metadata_version + 1
    assert changed == ("tick_size",)


def test_next_version_is_a_noop_when_nothing_versioned_changed() -> None:
    previous = parse_instrument(_raw(), fetched_at_us=1)
    # Same payload, later fetch: only fetched_at differs, which is not a
    # versioned field.
    parsed = parse_instrument(_raw(), fetched_at_us=999)

    versioned, changed = next_version(previous, parsed)

    assert versioned.metadata_version == previous.metadata_version
    assert changed == ()


def test_diff_changed_fields_reports_every_differing_versioned_field() -> None:
    previous = parse_instrument(_raw(), fetched_at_us=1)
    changed_raw = _raw()
    changed_raw["priceFilter"]["tickSize"] = "0.50"  # type: ignore[index]
    changed_raw["status"] = "Closed"
    parsed = parse_instrument(changed_raw, fetched_at_us=2)

    changed = diff_changed_fields(previous, parsed)

    assert set(changed) == {"tick_size", "status"}


def test_build_updated_event_carries_symbol_version_and_changed_fields() -> None:
    event = build_updated_event(
        event_id=uuid4(),
        symbol="BTCUSDT",
        metadata_version=2,
        changed_fields=("tick_size",),
        ts_now_us=123,
    )
    assert event.symbol == "BTCUSDT"
    assert event.metadata_version == 2
    assert event.changed_fields == ("tick_size",)
    assert event.source == "live"


# --- delisting (Gherkin "Delisted symbol") --------------------------------


def test_catalogue_snapshot_listing_excludes_non_trading_symbols() -> None:
    trading = parse_instrument(_raw(), fetched_at_us=1)
    closed = parse_instrument(_raw(symbol="ETHUSDT", status="Closed"), fetched_at_us=1)
    snapshot = CatalogueSnapshot(by_symbol={"BTCUSDT": trading, "ETHUSDT": closed}, fetched_at_us=1)

    listing = snapshot.listing()

    assert {i.symbol for i in listing} == {"BTCUSDT"}


def test_catalogue_snapshot_listing_can_include_delisted_when_asked() -> None:
    closed = parse_instrument(_raw(symbol="ETHUSDT", status="Closed"), fetched_at_us=1)
    snapshot = CatalogueSnapshot(by_symbol={"ETHUSDT": closed}, fetched_at_us=1)

    listing = snapshot.listing(include_delisted=True)

    assert {i.symbol for i in listing} == {"ETHUSDT"}


def test_catalogue_snapshot_get_still_returns_delisted_symbol_detail() -> None:
    closed = parse_instrument(_raw(symbol="ETHUSDT", status="Closed"), fetched_at_us=1)
    snapshot = CatalogueSnapshot(by_symbol={"ETHUSDT": closed}, fetched_at_us=1)

    detail = snapshot.get("ETHUSDT")

    assert detail is not None
    assert detail.status == "closed"


def test_catalogue_snapshot_get_returns_none_for_unknown_symbol() -> None:
    snapshot = CatalogueSnapshot(by_symbol={}, fetched_at_us=1)
    assert snapshot.get("NOSUCH") is None


# --- cache: TTL / stale / atomic swap (Gherkin "Refresh ..." scenarios) ----


def test_cache_reports_stale_when_empty() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=43_200)
    assert cache.is_stale(now_us=0) is True


def test_cache_reports_not_stale_within_ttl() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=43_200)
    cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=1_000_000))
    assert cache.is_stale(now_us=1_000_000 + 1) is False


def test_cache_reports_stale_after_ttl_elapses() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=1)
    cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=0))
    # ttl=1s -> 2_000_000us is well past it.
    assert cache.is_stale(now_us=2_000_000) is True


def test_cache_swap_is_a_single_atomic_assignment() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=43_200)
    first = CatalogueSnapshot(by_symbol={"A": object()}, fetched_at_us=1)  # type: ignore[arg-type]
    second = CatalogueSnapshot(by_symbol={"B": object()}, fetched_at_us=2)  # type: ignore[arg-type]

    cache.swap(first)
    observed_before = cache.current()
    cache.swap(second)
    observed_after = cache.current()

    # A reader holding `observed_before` never sees a mix of old/new data —
    # it's the same object it was handed, unaffected by the later swap.
    assert observed_before is first
    assert observed_after is second


def test_cache_mark_stale_keeps_serving_the_previous_snapshot() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=1)
    inst = parse_instrument(_raw(), fetched_at_us=1)
    cache.swap(CatalogueSnapshot(by_symbol={"BTCUSDT": inst}, fetched_at_us=1))

    cache.mark_stale(stale_since_us=5)

    snapshot = cache.current()
    assert snapshot is not None
    assert snapshot.get("BTCUSDT") is not None
    assert snapshot.stale_since_us == 5


def test_cache_mark_stale_is_a_noop_when_never_populated() -> None:
    cache = InstrumentCatalogueCache(ttl_seconds=1)
    cache.mark_stale(stale_since_us=5)
    assert cache.current() is None


def test_cache_marked_stale_is_stale_while_still_inside_the_ttl() -> None:
    """#2715: a failed refresh makes the catalogue stale at once, not only after the TTL."""
    cache = InstrumentCatalogueCache(ttl_seconds=43_200)
    cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=1_000_000))
    cache.mark_stale(stale_since_us=1_000_001)
    assert cache.is_stale(now_us=1_000_002) is True


def test_cache_successful_refresh_clears_the_stale_mark() -> None:
    """#2715: the next successful refresh swaps in a fresh, unmarked snapshot."""
    cache = InstrumentCatalogueCache(ttl_seconds=43_200)
    cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=1_000_000))
    cache.mark_stale(stale_since_us=1_000_001)
    cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=2_000_000))
    assert cache.is_stale(now_us=2_000_001) is False
