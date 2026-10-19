"""E12-T05 (#398) PR-A: `/market/klines` responses and every documented error validate against the
committed OpenAPI (`KlineResponse` / `Problem`, generated from `22-api-openapi.yaml`).

Bars come from the recorded corpus (`packages/fixtures/bybit/2026-10-05`, BTCUSDT 1m, 450 bars
spanning 2023-11-14 22:13 .. 2023-11-15 05:42 UTC). No network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse, Problem
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.ingestion.kline_read import KlineReadService
from tests._corpus import rest

_SPEC = load_openapi_spec()
_CODES = {e["code"]: e["status"] for e in _SPEC["x-error-codes"]}
_DECLARED = set(_SPEC["paths"]["/market/klines"]["get"]["responses"])


@dataclass(frozen=True, slots=True)
class _Kline:
    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool = True
    source: str = "ws"  # hot-tier kline (not an exchange_rest backfill row)


@dataclass(frozen=True, slots=True)
class _Tape:
    ts_us: int
    open: str = "1"
    high: str = "2"
    low: str = "0.5"
    close: str = "1.5"
    volume: str = "3.0"
    turnover: str = "4.5"
    confirmed: bool = True
    trades: int = 7
    delta: str | None = "1.25"
    min_delta: str | None = "-0.5"
    max_delta: str | None = "2.0"
    source: str = "tape"


def _corpus() -> list[_Kline]:
    pages = (rest(f"rest/kline_BTCUSDT_1_page{i}.json")["result"]["list"] for i in range(3))
    wire = [r for page in pages for r in page]
    return sorted(
        (_Kline(int(r[0]) * 1000, r[1], r[2], r[3], r[4], r[5], r[6]) for r in wire),
        key=lambda k: k.ts_us,
    )


class _Hot:
    def __init__(self, rows: list[_Kline]) -> None:
        self.rows = rows

    async def read_klines(
        self, sym: str, interval: str, rng: Any, tier: str = "auto", limit: int | None = None
    ) -> list[_Kline]:
        got = [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]
        return got[-limit:] if limit else got


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self._perms = perms

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return None if self._perms is None else MarketDataPrincipal("u1", self._perms)


_READ = frozenset({"marketdata:read"})
_START_US = 1_699_999_980_000_000  # 2023-11-14T22:13:00Z, first corpus bar


def _client(
    *, perms: frozenset[str] | None = _READ, tape: list[_Tape] | None = None,
    recording_us: int | None = None,
) -> TestClient:  # fmt: skip

    async def tape_reader(symbol: str, interval: str, rng: Any, limit: int | None) -> list[_Tape]:
        return [t for t in (tape or []) if rng.start_us <= t.ts_us < rng.end_us]

    async def started(symbol: str) -> int | None:
        return recording_us

    service = KlineReadService(
        _Hot(_corpus()), tape=tape_reader if tape is not None else None,
        recording_started_at_us=started,
    )  # fmt: skip
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Hot([]), principal_resolver=_Resolver(perms),
            read_service_provider=lambda: service, symbol_listed=lambda s: s == "BTCUSDT",
            now_us=lambda: 1_700_100_000_000_000,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


_P: dict[str, Any] = {
    "symbol": "BTCUSDT", "interval": "1",
    "from": "2023-11-14T22:00:00Z", "to": "2023-11-15T06:00:00Z", "limit": 1000,
}  # fmt: skip


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert str(status) in _DECLARED, f"{status} not declared on /market/klines"
    # `validation_failed` is also served at 422 app-wide (api/error_redaction.py, FastAPI request
    # validation) for semantically invalid input; every other code must match its catalogue status.
    allowed = {_CODES[code]} | ({422} if code == "validation_failed" else set())
    assert status in allowed, f"{code} is catalogued as {_CODES.get(code)}"
    body = resp.json()
    Problem.model_validate(body)
    assert body["code"] == code
    assert resp.headers["content-type"].startswith("application/problem+json")


class TestKlinesResponses:
    def test_corpus_window_validates_against_kline_response(self) -> None:
        body = _client().get("/market/klines", params=_P).json()
        KlineResponse.model_validate(body)
        ts = [b["t"] for b in body["bars"]]
        assert len(ts) == 450 and ts == sorted(ts)
        assert body["meta"]["sources"] == ["questdb"] and body["meta"]["has_more"] is False

    def test_window_after_now_is_an_empty_page_declared_uncovered(self) -> None:
        """#3808: a window after the server's now (2023-11-16T02:00Z here) is never read or
        backfilled: a contract-valid 200 with no bars that names the window as a hole."""
        q = {**_P, "from": "2023-11-16T03:00:00Z", "to": "2023-11-16T04:00:00Z"}
        body = _client().get("/market/klines", params=q).json()
        KlineResponse.model_validate(body)
        assert body["bars"] == [] and body["meta"]["has_more"] is False
        hole = {"start_us": 1_700_103_600_000_000, "end_us": 1_700_107_200_000_000}
        assert body["meta"]["coverage_holes"] == [hole]

    def test_kline_rows_have_null_not_zero_delta_with_include_delta(self) -> None:
        """Gherkin "Klines degrade honestly": pre-recording kline bars carry null order flow."""
        recording = _START_US + 1_000 * 60_000_000  # after the whole corpus window
        body = (
            _client(recording_us=recording)
            .get("/market/klines", params={**_P, "include_delta": "true"})
            .json()
        )
        KlineResponse.model_validate(body)
        for bar in body["bars"]:
            for name in ("delta", "min_delta", "max_delta", "cvd"):
                assert name in bar and bar[name] is None, (name, bar)
        assert body["meta"]["recording_started_at"].startswith("2023-11-15T")

    def test_without_include_delta_no_order_flow_fields(self) -> None:
        bar = _client().get("/market/klines", params=_P).json()["bars"][0]
        assert not {"delta", "cvd", "min_delta", "max_delta"} & set(bar)

    def test_tape_wins_over_klines_on_overlap(self) -> None:
        tape = [_Tape(ts_us=_START_US), _Tape(ts_us=_START_US + 60_000_000)]
        body = (
            _client(tape=tape).get("/market/klines", params={**_P, "include_delta": "true"}).json()
        )
        KlineResponse.model_validate(body)
        bars = body["bars"]
        assert len(bars) == 450  # replaced, not duplicated
        assert bars[0]["o"] == "1" and bars[0]["delta"] == "1.25" and bars[0]["trades"] == 7
        assert bars[2]["delta"] is None  # kline bar after the overlap stays null
        assert body["meta"]["sources"] == ["questdb", "tape"]

    def test_tape_reader_with_no_rows_never_claims_tape(self) -> None:
        body = _client(tape=[]).get("/market/klines", params=_P).json()
        assert "tape" not in body["meta"]["sources"]

    def test_include_open_governs_the_forming_bar(self) -> None:
        forming = _Tape(ts_us=_START_US, confirmed=False)
        params = {**_P, "from": "2023-11-14T22:13:00Z", "to": "2023-11-14T22:14:00Z"}
        closed_only = _client(tape=[forming]).get("/market/klines", params=params).json()
        assert closed_only["bars"] == []
        with_open = (
            _client(tape=[forming])
            .get("/market/klines", params={**params, "include_open": "true"})
            .json()
        )
        assert [b["confirm"] for b in with_open["bars"]] == [False]


class TestKlinesPagination:
    _WIDE: ClassVar[dict[str, Any]] = {**_P, "limit": 7}

    def _walk(self, client: TestClient, params: dict[str, Any]) -> tuple[list[str], int]:
        """A1: start WITHOUT a cursor; follow only server-issued `next_cursor`."""
        cursor: str | None = None
        seen: list[str] = []
        pages = 0
        while True:
            q = params if cursor is None else {**params, "cursor": cursor}
            resp = client.get("/market/klines", params=q)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            KlineResponse.model_validate(body)
            meta = body["meta"]
            assert meta["count"] == len(body["bars"]) <= params["limit"]
            assert meta["has_more"] is (meta["next_cursor"] is not None)
            # A4: never an empty page that claims more rows.
            assert body["bars"] or not meta["has_more"]
            seen.extend(b["t"] for b in body["bars"])
            pages += 1
            assert pages < 200
            cursor = meta["next_cursor"]
            if cursor is None:
                return seen, pages

    def test_uncursored_wide_window_is_served_as_first_page_with_cursor(self) -> None:
        body = _client().get("/market/klines", params=self._WIDE).json()
        assert body["meta"]["count"] == 7 and body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"]

    def test_round_trip_from_no_cursor_pages_by_rows(self) -> None:
        """A1 + A4: limit=7 over the 450 recorded bars -> 65 non-empty pages, each bar once."""
        seen, pages = self._walk(_client(), self._WIDE)
        assert len(seen) == len(set(seen)) == 450 and seen == sorted(seen)
        assert pages == 65

    def test_window_over_400_days_is_bar_window_too_large(self) -> None:
        q = {**self._WIDE, "from": "2020-01-01T00:00:00Z", "to": "2023-11-15T06:00:00Z"}
        _problem(_client().get("/market/klines", params=q), 422, "bar_window_too_large")

    @pytest.mark.parametrize("bad", ["x", "djE6YWJj", "Zm9v", "v1:12", "a" * 129])
    def test_malformed_cursor_is_invalid_cursor_without_echo(self, bad: str) -> None:
        """S1: a 129-char cursor is a 400 Problem, not FastAPI's echoing 422."""
        resp = _client().get("/market/klines", params={**self._WIDE, "cursor": bad})
        _problem(resp, 400, "invalid_cursor")
        assert bad not in resp.text

    def test_cursor_is_bound_to_its_request(self) -> None:
        """A3: a cursor replayed with another interval or symbol is invalid_cursor."""
        client = _client()
        cursor = client.get("/market/klines", params=self._WIDE).json()["meta"]["next_cursor"]
        other = {**self._WIDE, "interval": "5", "cursor": cursor}
        _problem(client.get("/market/klines", params=other), 400, "invalid_cursor")
        from candleviewer.api.market_response import InvalidCursor, cursor_scope, decode_cursor

        with pytest.raises(InvalidCursor):  # symbol is part of the scope too
            decode_cursor(cursor, scope=cursor_scope("klines", "ETHUSDT", "1"), end_us=2**62)
        with pytest.raises(InvalidCursor):  # and the route: a klines cursor is not a bars one
            decode_cursor(cursor, scope=cursor_scope("bars", "BTCUSDT", "1"), end_us=2**62)
        early = {**self._WIDE, "to": "2023-11-14T22:14:00Z", "cursor": cursor}
        _problem(client.get("/market/klines", params=early), 400, "invalid_cursor")

    @pytest.mark.parametrize("ts", [9 * 10**18, 0, 1_699_999_980_000_001])
    def test_forged_positions_are_rejected_not_clamped(self, ts: int) -> None:
        from candleviewer.api.market_response import cursor_scope, encode_cursor

        forged = encode_cursor(cursor_scope("klines", "BTCUSDT", "1"), ts)
        resp = _client().get("/market/klines", params={**self._WIDE, "cursor": forged})
        _problem(resp, 400, "invalid_cursor")

    def test_out_of_bounds_limit_is_a_problem_without_echo(self) -> None:
        """S1 audit: `limit` bounds fire before the handler; the shared handler keeps the
        Problem shape and drops the input."""
        from candleviewer.api.error_redaction import install_error_redaction

        client = _client()
        install_error_redaction(client.app)  # type: ignore[arg-type]  # TestClient.app is the FastAPI app
        resp = client.get("/market/klines", params={**_P, "limit": "987654321"})
        _problem(resp, 422, "validation_failed")
        assert "987654321" not in resp.text


class TestKlinesErrors:
    def test_no_session_is_401(self) -> None:
        _problem(_client(perms=None).get("/market/klines", params=_P), 401, "unauthenticated")

    def test_missing_permission_is_403_and_discloses_nothing(self) -> None:
        resp = _client(perms=frozenset({"orders:read"})).get("/market/klines", params=_P)
        _problem(resp, 403, "forbidden")
        assert "bars" not in resp.json()

    def test_bad_interval_is_400_validation_failed(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "interval": "7"})
        _problem(resp, 400, "validation_failed")

    def test_unknown_price_type_is_400(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "price_type": "last"})
        _problem(resp, 400, "validation_failed")

    @pytest.mark.parametrize("price_type", ["mark", "index", "premium_index"])
    def test_unrecorded_price_type_is_422_naming_the_alternative(self, price_type: str) -> None:
        resp = _client().get("/market/klines", params={**_P, "price_type": price_type})
        _problem(resp, 422, "validation_failed")
        assert "price_type=trade" in resp.json()["detail"]

    def test_unknown_symbol_is_422(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "symbol": "NOPEUSDT"})
        _problem(resp, 422, "validation_failed")

    def test_storage_not_ready_is_503(self) -> None:
        app = FastAPI()
        app.include_router(make_market_router(lambda: None, principal_resolver=_Resolver(_READ)))
        resp = TestClient(app).get("/market/klines", params=_P)
        _problem(resp, 503, "store_unavailable")


def test_klines_param_rejections_are_counted() -> None:
    """A6: klines rejections feed `bars_endpoint_param_rejected_total`."""
    from prometheus_client import REGISTRY

    def v(reason: str) -> float:
        got = REGISTRY.get_sample_value("bars_endpoint_param_rejected_total", {"reason": reason})
        return float(got or 0.0)

    inv, uns = v("invalid"), v("unsupported")
    client = _client()
    client.get("/market/klines", params={**_P, "interval": "7"})
    client.get("/market/klines", params={**_P, "price_type": "last"})
    client.get("/market/klines", params={**_P, "price_type": "mark"})
    assert (v("invalid"), v("unsupported")) == (inv + 2, uns + 1)


def test_tape_tier_failure_serves_klines_only_never_500() -> None:
    """S2/A2 end to end: a raw driver error in the tape tier degrades the response."""

    class UndefinedTableError(Exception):
        sqlstate = "42P01"

    from candleviewer.bars.reader import BarReader, tape_time_bar_reader

    class _Broken:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            raise UndefinedTableError('relation "bars_time" does not exist')

    async def _noop(*a: object) -> None: ...

    service = KlineReadService(
        _Hot(_corpus()), tape=tape_time_bar_reader(BarReader(_Broken(), _noop), timeout_s=1.0)
    )
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Hot([]), principal_resolver=_Resolver(_READ),
            read_service_provider=lambda: service, symbol_listed=lambda s: s == "BTCUSDT",
        )
    )  # fmt: skip
    resp = TestClient(app).get("/market/klines", params=_P)
    assert resp.status_code == 200
    assert resp.json()["meta"]["sources"] == ["questdb"] and resp.json()["meta"]["count"] == 450
