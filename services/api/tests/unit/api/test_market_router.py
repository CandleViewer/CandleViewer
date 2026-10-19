"""Unit tests for `candleviewer.api.market.make_market_router` (QA defect
#1622 blocker: "GET /market/klines REST endpoint (core ticket deliverable)
not implemented" — `grep -rln "market/klines" services/api/candleviewer/
**/*.py` outside `ingestion/` returned nothing before this fix, and no
`APIRouter` served the route).

PR #1626 review: the first cut served every request unauthenticated
despite `22-api-openapi.yaml`'s `x-rbac: {permissions: [marketdata:read]}`
(C-12.4). `TestGetKlinesAuthorization` covers the fail-closed
`PrincipalResolver` gate added in response to that finding, mirroring
`test_audit_router.py`'s own resolver tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TimeRange


@dataclass(slots=True)
class _FakeRow:
    ts_us: int
    open: str = "100"
    high: str = "101"
    low: str = "99"
    close: str = "100.5"
    volume: str = "10"
    turnover: str = "1000"
    confirmed: bool = True


@dataclass(slots=True)
class _FakeCache:
    rows: list[_FakeRow] = field(default_factory=list)
    calls: list[tuple[str, str, TimeRange]] = field(default_factory=list)

    async def read_klines(
        self, sym: str, interval: str, rng: TimeRange, tier: str = "auto", limit: int | None = None
    ) -> list[_FakeRow]:
        self.calls.append((sym, interval, rng))
        return [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]


class _FakeResolver:
    def __init__(self, principal: MarketDataPrincipal | None) -> None:
        self._principal = principal

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return self._principal


_AUTHORIZED = _FakeResolver(
    MarketDataPrincipal(user_id="u1", permissions=frozenset({"marketdata:read"}))
)


def _app(cache: _FakeCache | None, *, resolver: _FakeResolver | None = _AUTHORIZED) -> FastAPI:
    app = FastAPI()
    app.include_router(make_market_router(lambda: cache, principal_resolver=resolver))
    return app


def _client(
    cache: _FakeCache | None, *, resolver: _FakeResolver | None = _AUTHORIZED
) -> TestClient:
    return TestClient(_app(cache, resolver=resolver), client=("127.0.0.1", 50000))


class TestGetKlinesHappyPath:
    def test_returns_ascending_confirmed_bars_from_the_cache(self) -> None:
        cache = _FakeCache(rows=[_FakeRow(ts_us=0), _FakeRow(ts_us=60_000_000)])
        client = _client(cache)

        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1",
                "from": "1970-01-01T00:00:00Z",
                "to": "1970-01-01T00:01:00Z",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "BTCUSDT"
        assert body["interval"] == "1"
        assert len(body["bars"]) == 1
        assert body["bars"][0]["confirm"] is True
        assert body["meta"]["count"] == 1

    def test_unconfirmed_bar_excluded_unless_include_open(self) -> None:
        cache = _FakeCache(rows=[_FakeRow(ts_us=0, confirmed=False)])
        client = _client(cache)
        params = {
            "symbol": "BTCUSDT",
            "interval": "1",
            "from": "1970-01-01T00:00:00Z",
            "to": "1970-01-01T00:01:00Z",
        }

        resp_default = client.get("/market/klines", params=params)
        resp_open = client.get("/market/klines", params={**params, "include_open": "true"})

        assert resp_default.json()["bars"] == []
        assert len(resp_open.json()["bars"]) == 1
        assert resp_open.json()["bars"][0]["confirm"] is False


class TestGetKlinesValidation:
    def test_missing_from_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get("/market/klines", params={"symbol": "BTCUSDT", "interval": "1"})
        assert resp.status_code == 400
        assert resp.json()["title"] == "Bad request"

    def test_unsupported_interval_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "not-an-interval",
                "from": "1970-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 400

    def test_from_after_to_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1",
                "from": "1970-01-02T00:00:00Z",
                "to": "1970-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 400


class TestGetKlinesUnavailable:
    def test_no_cache_wired_is_503(self) -> None:
        client = _client(None)
        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 503

    def test_storage_not_started_yet_is_503_not_a_500(self) -> None:
        def _raise() -> None:
            raise StorageTierUnavailable("storage.start() has not been called")

        app = FastAPI()
        app.include_router(
            make_market_router(_raise, principal_resolver=_AUTHORIZED)  # type: ignore[arg-type]
        )
        client = TestClient(app, client=("127.0.0.1", 50000))

        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 503


class TestGetKlinesAuthorization:
    """PR #1626 review finding: this route served every request
    unauthenticated despite `x-rbac: {permissions: [marketdata:read]}`
    (C-12.4). Mirrors `test_audit_router.py`'s own resolver tests."""

    def test_no_principal_resolver_wired_is_501(self) -> None:
        client = _client(_FakeCache(), resolver=None)
        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 501

    def test_no_verified_session_is_401(self) -> None:
        client = _client(_FakeCache(), resolver=_FakeResolver(None))
        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 401

    def test_missing_permission_is_403(self) -> None:
        principal = MarketDataPrincipal(user_id="u1", permissions=frozenset())
        client = _client(_FakeCache(), resolver=_FakeResolver(principal))
        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 403

    def test_wildcard_permission_is_authorized(self) -> None:
        principal = MarketDataPrincipal(user_id="owner", permissions=frozenset({"*"}))
        cache = _FakeCache(rows=[_FakeRow(ts_us=0)])
        client = _client(cache, resolver=_FakeResolver(principal))
        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1",
                "from": "1970-01-01T00:00:00Z",
                "to": "1970-01-01T00:01:00Z",
            },
        )
        assert resp.status_code == 200


class TestGetKlinesReadService:
    """E12-S05: tier-merged reads; `meta.sources` and `meta.recording_started_at` on every
    response (OpenAPI `DataMeta`)."""

    _P: ClassVar[dict[str, str]] = {
        "symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z",
        "to": "1970-01-01T00:03:00Z",
    }  # fmt: skip

    def _client_with(self, service: object) -> TestClient:
        app = FastAPI()
        app.include_router(
            make_market_router(
                lambda: _FakeCache(),
                principal_resolver=_AUTHORIZED,
                read_service_provider=lambda: service,  # type: ignore[arg-type,return-value]  # duck-typed fake service
                symbol_listed=lambda s: s == "BTCUSDT",
            )
        )
        return TestClient(app, client=("127.0.0.1", 50000))

    def test_meta_sources_and_recording_started_at_from_read_service(self) -> None:
        from candleviewer.ingestion.kline_read import KlineRead

        class _Svc:
            async def read(
                self, symbol: str, interval: str, rng: object, limit: int | None = None
            ) -> KlineRead:
                rows = [_FakeRow(ts_us=0), _FakeRow(ts_us=60_000_000)]
                return KlineRead(rows, ["parquet", "questdb", "exchange_rest"],  # type: ignore[arg-type]  # _FakeRow lacks .source
                                 120_000_000, [], True)  # fmt: skip

        body = self._client_with(_Svc()).get("/market/klines", params=self._P).json()
        assert body["meta"]["sources"] == ["parquet", "questdb", "exchange_rest"]
        assert body["meta"]["recording_started_at"] == "1970-01-01T00:02:00+00:00"
        assert len(body["bars"]) == 2

    def test_cache_only_meta_is_questdb_and_null_recording_start(self) -> None:
        cache = _FakeCache(rows=[_FakeRow(ts_us=0)])
        body = _client(cache).get("/market/klines", params=self._P).json()
        assert body["meta"]["sources"] == ["questdb"]
        assert body["meta"]["recording_started_at"] is None
        empty = _client(_FakeCache()).get("/market/klines", params=self._P).json()
        assert empty["meta"]["sources"] == [] and "recording_started_at" in empty["meta"]

    def test_provider_returning_none_falls_back_to_cache(self) -> None:
        body = self._client_with(None).get("/market/klines", params=self._P).json()
        assert body["meta"]["sources"] == []


class TestGetKlinesSecurityReview:
    """#2045 security review: SR-E12-08 symbol gate (blocking) and the window cap (medium)."""

    _P: ClassVar[dict[str, str]] = {
        "interval": "1", "from": "1970-01-01T00:00:00Z", "to": "1970-01-01T00:03:00Z",
    }  # fmt: skip

    def _wired(self, listed: object) -> tuple[TestClient, object, object]:
        from candleviewer.exchange.base.models import KlineEvent
        from candleviewer.ingestion.kline_backfill import KlineBackfillService
        from candleviewer.ingestion.kline_read import KlineReadService

        fetches: list[str] = []

        async def fetch(symbol: str, *a: object, **kw: object) -> list[KlineEvent]:
            fetches.append(symbol)
            return []

        class _Hot:
            async def read_klines(self, *a: object, **kw: object) -> list[object]:
                return []

            async def write_klines(self, rows: object) -> None: ...

        backfill = KlineBackfillService(fetch_klines=fetch, cache=_Hot())  # type: ignore[arg-type]  # structural fakes
        service = KlineReadService(_Hot(), backfill=backfill)  # type: ignore[arg-type]  # structural fake
        app = FastAPI()
        app.include_router(
            make_market_router(
                lambda: _FakeCache(), principal_resolver=_AUTHORIZED,
                read_service_provider=lambda: service,
                symbol_listed=listed,  # type: ignore[arg-type]  # None or a predicate
            )
        )  # fmt: skip
        return TestClient(app, client=("127.0.0.1", 50000)), backfill, fetches

    def test_many_unknown_symbols_start_no_job_no_fetch_no_state(self) -> None:
        client, backfill, fetches = self._wired(lambda s: s == "BTCUSDT")
        for i in range(200):
            r = client.get("/market/klines", params={**self._P, "symbol": f"JUNK{i}"})
            assert r.status_code == 422
        assert fetches == []
        assert backfill._jobs == {} and backfill._locks == {}  # type: ignore[attr-defined]  # private state under test
        assert backfill.tracked_keys == 0  # type: ignore[attr-defined]  # backfill is typed object here

    def test_listed_symbol_is_served(self) -> None:
        client, backfill, _ = self._wired(lambda s: s == "BTCUSDT")
        r = client.get("/market/klines", params={**self._P, "symbol": "BTCUSDT"})
        assert r.status_code == 200
        assert backfill.tracked_keys == 1  # type: ignore[attr-defined]  # backfill is typed object here

    def test_read_service_without_catalogue_fails_closed_503(self) -> None:
        client, _, fetches = self._wired(None)
        r = client.get("/market/klines", params={**self._P, "symbol": "BTCUSDT"})
        assert r.status_code == 503 and fetches == []

    def test_window_spanning_more_than_limit_bars_is_422(self) -> None:
        cache = _FakeCache()
        client = _client(cache)
        params = {"symbol": "BTCUSDT", "interval": "1", "from": "2020-01-01T00:00:00Z",
                  "to": "2024-01-01T00:00:00Z", "limit": "5000"}  # fmt: skip
        assert client.get("/market/klines", params=params).status_code == 422
        assert cache.calls == []  # rejected before any read
        ok = {**params, "from": "2023-12-29T00:00:00Z"}  # 3 days = 4 320 bars <= 5 000
        assert client.get("/market/klines", params=ok).status_code == 200


class TestGetKlinesFutureWindow:
    """#3808: the server bounds the window at its own now. The part after now is never read,
    paged or backfilled; it is declared uncovered in `meta.coverage_holes` (200, no bars)."""

    _NOW = 3_600_000_000  # 1970-01-01T01:00:00Z
    _P: ClassVar[dict[str, str]] = {"symbol": "BTCUSDT", "interval": "1"}

    def _client(self, service: object) -> TestClient:
        app = FastAPI()
        app.include_router(
            make_market_router(
                lambda: _FakeCache(), principal_resolver=_AUTHORIZED,
                read_service_provider=lambda: service,  # type: ignore[arg-type,return-value]  # duck-typed service
                symbol_listed=lambda s: s == "BTCUSDT", now_us=lambda: self._NOW,
            )
        )  # fmt: skip
        return TestClient(app, client=("127.0.0.1", 50000))

    def test_window_after_now_is_never_read_and_is_declared_uncovered(self) -> None:
        from candleviewer.ingestion.kline_backfill import KlineBackfillService
        from candleviewer.ingestion.kline_read import KlineReadService

        fetches: list[object] = []

        async def fetch(*a: object, **kw: object) -> list[object]:
            fetches.append(a)
            return []

        class _Hot:
            async def read_klines(self, *a: object, **kw: object) -> list[object]:
                return []

            async def write_klines(self, rows: object) -> None: ...

        backfill = KlineBackfillService(fetch_klines=fetch, cache=_Hot(), now_us=lambda: self._NOW)  # type: ignore[arg-type]  # structural fakes
        client = self._client(KlineReadService(_Hot(), backfill=backfill))  # type: ignore[arg-type]  # structural fake
        future = {**self._P, "from": "1970-01-01T02:00:00Z", "to": "1970-01-01T03:00:00Z"}
        body = client.get("/market/klines", params=future).json()
        assert body["bars"] == [] and body["meta"]["has_more"] is False
        hole = {"start_us": 7_200_000_000, "end_us": 10_800_000_000}
        assert body["meta"]["coverage_holes"] == [hole]
        assert fetches == [] and backfill.tracked_keys == 0  # no read, job or per-key state
        present = {**self._P, "from": "1970-01-01T00:00:00Z", "to": "1970-01-01T00:30:00Z"}
        assert client.get("/market/klines", params=present).status_code == 200
        assert backfill.tracked_keys == 1  # a present-time read is served as before

    def test_window_crossing_now_is_read_only_up_to_now(self) -> None:
        from candleviewer.ingestion.kline_coverage import Range
        from candleviewer.ingestion.kline_read import KlineRead

        asked: list[Range] = []

        class _Svc:
            async def read(
                self, symbol: str, interval: str, rng: Range, limit: int | None = None
            ) -> KlineRead:
                asked.append(rng)
                return KlineRead([], [], None, [], False)

        crossing = {**self._P, "from": "1970-01-01T00:30:00Z", "to": "1970-01-01T02:00:00Z"}
        body = self._client(_Svc()).get("/market/klines", params=crossing).json()
        assert asked and max(r.end_us for r in asked) == self._NOW
        assert body["meta"]["coverage_holes"] == [{"start_us": self._NOW, "end_us": 7_200_000_000}]
        assert body["meta"]["has_more"] is False

    def test_future_part_merges_with_the_adjacent_coverage_hole(self) -> None:
        from candleviewer.ingestion.kline_coverage import CoverageIndex

        app = FastAPI()
        app.include_router(
            make_market_router(
                lambda: _FakeCache(), principal_resolver=_AUTHORIZED,
                coverage_index_provider=lambda s, i: CoverageIndex(), now_us=lambda: self._NOW,
            )
        )  # fmt: skip
        crossing = {**self._P, "from": "1970-01-01T00:30:00Z", "to": "1970-01-01T02:00:00Z"}
        body = TestClient(app).get("/market/klines", params=crossing).json()
        hole = {"start_us": 1_800_000_000, "end_us": 7_200_000_000}  # [from, now) + [now, to)
        assert body["meta"]["coverage_holes"] == [hole]
