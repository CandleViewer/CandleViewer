"""The five REST read routes on the recorded-fixture backend (scenario 4), no network.

`build_app(cold_root)` mounts the *real* routers (`/instruments`, `/market/klines`,
`/market/trades`, `/market/orderbook`, `/market/data-coverage`) over fixture-fed readers:

* instruments: `rest/instruments_before.json` through the production `parse_instrument`;
* klines: **cold** = the real `KlineReadService` + `ParquetKlineReader` (DuckDB scan of a
  Parquet partition written from the `rest/kline_BTCUSDT_1_page*.json` corpus, tiled to 30 days);
  **warm** = the same service answering from the in-memory hot tier (the cache-hit path);
* trades: a real `TradeStream` fed the clean BTCUSDT public-trade capture;
* orderbook: a real `BookStream` fed `ws/orderbook_BTCUSDT.jsonl`;
* data-coverage: the real `CoverageService` over the recorder test store.

Auth is a fixed bench principal with read permissions only (test-only identity, no credentials).
`serve()` binds 127.0.0.1 only (C-12.9); `assert_no_exchange_egress()` is the security-notes guard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import FastAPI, Request

from bench.ingestion.engine import T0_MS
from candleviewer.api.instruments import InstrumentsPrincipal, make_instruments_router
from candleviewer.api.market import make_market_router
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.api.orderbook import make_orderbook_router
from candleviewer.api.trades import make_trades_router
from candleviewer.bus.bus import Bus

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import ALLOWED_REST_HOSTS

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import parse_instrument

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.orderbook_wiring import BookStream
from candleviewer.recorder.coverage import CoverageService
from candleviewer.storage.cold.kline_reader import ColdKlineRow, ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.models import StreamKind

CAPTURE_DATE = "2026-10-05"
_FIXTURES = Path(__file__).resolve().parents[4] / "packages" / "fixtures"


def _corpus_root() -> Path:
    """The recorded exchange capture for `CAPTURE_DATE` (located by its manifest, so no
    exchange name is spelled outside the adapter)."""
    for d in sorted(_FIXTURES.iterdir()):
        if (d / CAPTURE_DATE / "manifest.json").is_file():
            return d / CAPTURE_DATE
    raise FileNotFoundError(f"no recorded capture {CAPTURE_DATE} under {_FIXTURES}")


CORPUS = _corpus_root()
SYMBOL, INTERVAL = "BTCUSDT", "1"
MIN_US = 60_000_000
#: Cold window: 30 days of 1m bars ending at the hot boundary (a 5000-bar request is cold).
COLD_DAYS = 30
HOT_BOUNDARY_US = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1_000_000)
HOT_BARS = 6_000


class _Principal:
    """Read-only bench identity; `has` is the routers' structural principal check."""

    def has(self, permission: str) -> bool:
        return permission in ("marketdata:read", "instruments:read")


class _Resolver:
    def resolve(self, request: Request) -> Any:
        return _Principal()


class _InstrumentsResolver:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal("bench", frozenset({"instruments:read"}))


class _Catalogue:
    def __init__(self, snap: CatalogueSnapshot) -> None:
        self._snap = snap

    def snapshot(self) -> CatalogueSnapshot:
        return self._snap

    async def ensure_symbol(self, symbol: str) -> Any:
        return self._snap.get(symbol)


class _HotTier:
    """In-memory hot tier (QuestDB stand-in): the cache-hit path."""

    def __init__(self, rows: list[ColdKlineRow]) -> None:
        self._rows = rows
        self._ts = [r.ts_us for r in rows]

    async def read_klines(
        self, sym: str, interval: str, rng: Any, tier: str = "auto", limit: int | None = None
    ) -> list[ColdKlineRow]:
        from bisect import bisect_left

        lo, hi = bisect_left(self._ts, rng.start_us), bisect_left(self._ts, rng.end_us)
        out = self._rows[lo:hi]
        return out if limit is None else out[-limit:]


class _CoverageStore:
    """One open recording session + one gap (recorder store shape), fixed timestamps."""

    async def sessions_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        start = datetime.fromtimestamp(HOT_BOUNDARY_US / 1e6 - 86_400 * COLD_DAYS, tz=UTC)
        return [{"started_at": start, "ended_at": None, "streams": ["trades", "orderbook_delta"]}]

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        g0 = datetime.fromtimestamp(HOT_BOUNDARY_US / 1e6 - 3_600, tz=UTC)
        g1 = datetime.fromtimestamp(HOT_BOUNDARY_US / 1e6 - 3_000, tz=UTC)
        return [{"stream": "trades", "gap_start": g0, "gap_end": g1, "cause": "process_restart"}]

    async def earliest_first_event(self, symbol: str) -> datetime | None:
        return None


def _corpus_lines(rel: str) -> list[str]:
    return (CORPUS / rel).read_text(encoding="utf-8").splitlines()


def _corpus_json(rel: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CORPUS / rel).read_text(encoding="utf-8"))
    return data


def _kline_template() -> list[list[str]]:
    rows = [
        r
        for i in range(3)
        for r in _corpus_json(f"rest/kline_BTCUSDT_1_page{i}.json")["result"]["list"]
    ]
    return sorted(rows, key=lambda r: int(r[0]))


def _rows(n: int, end_us: int) -> list[ColdKlineRow]:
    """`n` 1m bars ending at `end_us`, OHLCV tiled from the 600 corpus bars."""
    tpl = _kline_template()
    start = end_us - n * MIN_US
    out: list[ColdKlineRow] = []
    for i in range(n):
        o, h, lo, c, v, t = tpl[i % len(tpl)][1:7]
        out.append(ColdKlineRow(start + i * MIN_US, o, h, lo, c, v, t, True, "tape"))
    return out


def write_cold_lake(root: Path) -> int:
    """30 days of 1m bars as Parquet partitions (+ verified manifest) under `root`."""
    rows = _rows(COLD_DAYS * 1440, HOT_BOUNDARY_US)
    by_month: dict[str, list[ColdKlineRow]] = {}
    for r in rows:
        ym = datetime.fromtimestamp(r.ts_us / 1e6, tz=UTC).strftime("%Y-%m")
        by_month.setdefault(ym, []).append(r)
    for ym, part in by_month.items():
        paths = DatasetRegistry(root).resolve_partition(
            StreamKind.KLINES, partition_values={"symbol": SYMBOL, "interval": INTERVAL, "ym": ym}
        )
        paths.partition_dir.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "ts": pa.array([r.ts_us for r in part], type=pa.timestamp("us", tz="UTC")),
                **{
                    k: [float(getattr(r, k)) for r in part]
                    for k in ("open", "high", "low", "close", "volume", "turnover")
                },
                "confirmed": [True] * len(part),
                "source": ["tape"] * len(part),
            }
        )
        f = paths.partition_dir / "part-0000.parquet"
        pq.write_table(table, f)
        ManifestStore(paths.manifests_dir).append_reconciled(
            paths.partition_dir,
            paths.root,
            ManifestEntry(
                file=f.name,
                sha256=sha256_of(f),
                row_count=len(part),
                source_table="klines",
                export_run_id="e08-q04",
                exported_at_us=0,
            ),
        )
    return len(rows)


def _catalogue() -> CatalogueSnapshot:
    items = [
        parse_instrument(raw, fetched_at_us=T0_MS * 1000)
        for raw in _corpus_json("rest/instruments_before.json")["result"]["list"]
    ]
    return CatalogueSnapshot(by_symbol={i.symbol: i for i in items}, fetched_at_us=T0_MS * 1000)


async def _trades() -> TradeStream:
    now = T0_MS * 1000 + 3_600_000_000

    stream = TradeStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _d: None,
        parse_frame=parse_trade_frame,
        topic_for=trade_topic,
        is_listed=lambda s: s == SYMBOL,
        touch=lambda _t: None,
        tick_size=lambda _s: Decimal("0.1"),
        clock=lambda: 0.0,
        now_us=lambda: now,
    )
    stream.acquire("bench-rest", SYMBOL)
    for raw in _corpus_lines("ws/clean_publicTrade_BTCUSDT.jsonl"):
        await stream.handle_frame(raw)
    return stream


async def _book() -> BookStream:
    async def resub(_topic: str) -> None:
        return None

    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda f: parse_book_frame(f, lambda _s: Decimal("0.1")),
        topic_for=book_topic,
        resubscribe=resub,
        is_listed=lambda s: s == SYMBOL,
        touch=lambda _t: None,
        now_us=lambda: T0_MS * 1000,
    )
    stream.acquire("bench-rest", SYMBOL)
    for raw in _corpus_lines("ws/orderbook_BTCUSDT.jsonl")[:500]:  # before the deliberate hole
        await stream.handle_frame(raw)
    return stream


async def build_app(cold_root: Path) -> FastAPI:
    """The five read routes over fixture-fed real readers. `cold_root` must be pre-populated
    by `write_cold_lake` (kept separate so tests can time it)."""
    snap = _catalogue()
    listed = snap.get
    hot = _HotTier(_rows(HOT_BARS, HOT_BOUNDARY_US + HOT_BARS * MIN_US))
    svc = KlineReadService(
        hot,
        cold=ParquetKlineReader(DatasetRegistry(cold_root)),
        hot_boundary_us=lambda: HOT_BOUNDARY_US,
    )
    trades, book = await _trades(), await _book()
    coverage = CoverageService(_CoverageStore(), now_us=lambda: HOT_BOUNDARY_US + 86_400_000_000)
    app = FastAPI()
    app.include_router(
        make_instruments_router(
            lambda: _Catalogue(snap),
            principal_resolver=_InstrumentsResolver(),
            now_us=lambda: T0_MS * 1000,
        )
    )
    app.include_router(
        make_market_router(
            lambda: hot,
            principal_resolver=_Resolver(),
            read_service_provider=lambda: svc,
            symbol_listed=lambda s: listed(s) is not None,
            now_us=lambda: HOT_BOUNDARY_US + HOT_BARS * MIN_US,
        )
    )
    app.include_router(make_trades_router(lambda: trades, principal_resolver=_Resolver()))
    app.include_router(make_orderbook_router(lambda: book, principal_resolver=_Resolver()))
    app.include_router(
        make_data_coverage_router(
            lambda: coverage,
            principal_resolver=_Resolver(),
            symbol_listed=lambda s: listed(s) is not None,
        )
    )
    return app


def iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def requests_plan() -> dict[str, dict[str, Any]]:
    """The k6/in-process request set (route -> (path, params)), shared by both drivers."""
    warm_end = HOT_BOUNDARY_US + HOT_BARS * MIN_US
    cold_end = HOT_BOUNDARY_US - 86_400_000_000  # fully inside the cold lake
    return {
        "instruments": {"path": "/instruments", "params": {"limit": 100}},
        "klines_cold": {
            "path": "/market/klines",
            "params": {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "from": iso(cold_end - 5000 * MIN_US),
                "to": iso(cold_end),
                "limit": 5000,
            },
        },
        "klines_warm": {
            "path": "/market/klines",
            "params": {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "from": iso(warm_end - 1000 * MIN_US),
                "to": iso(warm_end),
                "limit": 1000,
            },
        },
        "klines_page_boundary": {
            "path": "/market/klines",
            "params": {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "from": iso(HOT_BOUNDARY_US - 500 * MIN_US),
                "to": iso(HOT_BOUNDARY_US + 500 * MIN_US),
                "limit": 1000,
            },
        },
        "trades": {"path": "/market/trades", "params": {"symbol": SYMBOL, "limit": 100}},
        "orderbook": {"path": "/market/orderbook", "params": {"symbol": SYMBOL, "depth": 50}},
        "data_coverage": {"path": "/market/data-coverage", "params": {"symbol": SYMBOL}},
    }


def assert_loopback_target(base_url: str) -> None:
    """Security notes guard: the load target must be the local fixture app. Any non-loopback
    host, and any exchange host in particular, is refused before a single request is sent."""
    from urllib.parse import urlsplit

    host = (urlsplit(base_url).hostname or "").lower()
    if host in ALLOWED_REST_HOSTS or any(
        host.endswith("." + h.split(".", 1)[1]) for h in ALLOWED_REST_HOSTS
    ):
        raise RuntimeError(f"refusing exchange host {host!r} as a bench target (C-13.5)")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"bench target {host!r} is not loopback (C-12.9)")
    for spec in requests_plan().values():
        if str(spec["path"]).startswith(("http:", "https:", "//")):
            raise RuntimeError("bench request plan must be target-relative")
