"""E12-T05 (#398) PR-B: `/market/bars` — every bar type served, 400/422 codes, precedence,
pagination round-trip, RBAC, and contract validation against the committed OpenAPI.

Stored rows are built by the real builders from the recorded BTCUSDT tape
(`ws/clean_publicTrade_BTCUSDT.jsonl`, 542 prints, C-13.5) and mapped with `bars.rows.bar_row`,
exactly what `BarWriter` persists. No renko builder is merged yet (E12-S04), so renko rows are
range-built bars stored under the renko `bar_param`; the route only reads stored rows, which is
what this tests. The fake `RowFetcher` evaluates the reader's parameterised SQL params.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse, Problem
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.metrics import bars_endpoint_422_no_data_recorded_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.rows import bar_param_for, bar_row, row_checksum
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.domain.sql_names import ts_us_from_row
from tests.unit.bars._trades import final_bars
from tests.unit.bars.test_time_builder_golden import _tape

_SPEC = load_openapi_spec()
_CODES = {e["code"]: e["status"] for e in _SPEC["x-error-codes"]}
_DECLARED = set(_SPEC["paths"]["/market/bars"]["get"]["responses"])
_TICK = Decimal("0.10")
_TAPE = _tape()
_T0 = _TAPE[0].ts_event
_NOW = _TAPE[-1].ts_event + 3_600_000_000

#: (bar_type, param) -> spec used to build the stored rows.
_SERIES: dict[tuple[str, str], BarSpec] = {
    ("time", "1"): BarSpec(kind="time", interval_ms=60_000),
    ("tick", "100"): BarSpec(kind="tick", tick_count=100),
    ("volume", "5"): BarSpec(kind="volume", volume_threshold=Decimal(5)),
    ("range", "20"): BarSpec(kind="range", range_ticks=20),
    ("delta", "1"): BarSpec(kind="delta", delta_threshold=Decimal(1)),
    ("renko", "20"): BarSpec(kind="renko", range_ticks=20),
}


def _build(spec: BarSpec) -> list[Bar]:
    if spec.kind == "time":
        tb = TimeBarBuilder(spec, "BTCUSDT")
        ups: list[BarUpdate] = []
        for t in _TAPE:
            ups += tb.on_trade(t)
            ups += tb.on_clock(t.ts_event)
        ups += tb.on_clock(_TAPE[-1].ts_event + 60_000_000)
        return final_bars(ups)
    builder: Any
    if spec.kind == "tick":
        builder = TickBarBuilder(spec, "BTCUSDT")
    elif spec.kind == "volume":
        builder = VolumeBarBuilder(spec, "BTCUSDT")
    elif spec.kind == "delta":
        builder = DeltaBarBuilder(spec, "BTCUSDT")
    else:  # range, and renko stand-in (no renko builder merged yet, E12-S04)
        as_range = BarSpec(kind="range", range_ticks=spec.range_ticks)
        builder = RangeBarBuilder(as_range, "BTCUSDT", lambda _s: _TICK)
    out: list[BarUpdate] = []
    for t in _TAPE:
        out += builder.on_trade(t)
    return final_bars(out)


def _rows() -> dict[str, list[dict[str, object]]]:
    """`bar_param` -> stored rows (ascending ts)."""
    store: dict[str, list[dict[str, object]]] = {}
    for spec in _SERIES.values():
        rows = [bar_row(b, spec) for b in _build(spec) if b.closed]
        store[bar_param_for(spec)] = sorted(rows, key=lambda r: int(str(r["ts"])))
    return store


_STORE = _rows()


class _Fetch:
    """Evaluates `build_range_query`'s params: (symbol, bar_param, start, to[, key x5]); limit is
    inlined. The optional key binds are the #2017 keyset `(ts, generation, index) >= key`."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls += 1
        symbol, bar_param, start, to = params[:4]
        start, to = ts_us_from_row(start), ts_us_from_row(to)
        limit = int(sql.rsplit("LIMIT ", 1)[1])
        key = None
        if len(params) == 9:
            key = (
                ts_us_from_row(params[4]),
                int(str(params[6])),
                -1 if "IS NULL" in sql else int(str(params[8])),
            )
        rows = [r for r in sorted(_STORE.get(str(bar_param), []), key=row_key)
                if r["symbol"] == symbol and start <= int(str(r["ts"])) < to
                and (key is None or row_key(r) >= key)]  # fmt: skip
        return rows[:limit]


async def _noop(*a: object) -> None: ...


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self._perms = perms

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return None if self._perms is None else MarketDataPrincipal("u1", self._perms)


def _client(
    *, perms: frozenset[str] | None = frozenset({"marketdata:read"}),
    recording_us: int | None = _T0, fetch: _Fetch | None = None, wired: bool = True,
    recording_wired: bool = True,
) -> TestClient:  # fmt: skip
    reader = BarReader(fetch or _Fetch(), _noop)

    async def started(symbol: str) -> int | None:
        return recording_us

    app = FastAPI()
    app.include_router(
        make_market_bars_router(
            lambda: reader if wired else None,
            recording_started_at_us=started if recording_wired else None,
            principal_resolver=_Resolver(perms), symbol_listed=lambda s: s == "BTCUSDT",
            now_us=lambda: _NOW,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


def _iso(us: int) -> str:
    from candleviewer.api.market_response import iso_us

    return iso_us(us).replace("+00:00", "Z")


_P: dict[str, Any] = {"symbol": "BTCUSDT", "from": _iso(_T0), "to": _iso(_NOW), "limit": 5000}


def _problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert str(status) in _DECLARED, f"{status} not declared on /market/bars"
    # #2088: the registry lists `validation_failed` at 400 only, though the spec's own
    # `UnprocessableEntity` example and the server also serve it at 422. Drop when #2088 lands.
    allowed = {_CODES[code]} | ({422} if code == "validation_failed" else set())
    assert status in allowed, f"{code} is catalogued as {_CODES[code]}"
    body: dict[str, Any] = resp.json()
    Problem.model_validate(body)
    assert body["code"] == code
    return body


class TestEveryBarType:
    @pytest.mark.parametrize(("bar_type", "param"), list(_SERIES))
    def test_served_oldest_first_and_validates(self, bar_type: str, param: str) -> None:
        """Gherkin: every supported bar type, oldest to newest, sources name the tier."""
        resp = _client().get("/market/bars", params={**_P, "bar_type": bar_type, "param": param})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        KlineResponse.model_validate(body)
        ts = [b["t"] for b in body["bars"]]
        assert ts and ts == sorted(ts)
        assert body["bar_type"] == bar_type and body["meta"]["sources"] == ["tape"]
        assert body["meta"]["count"] == len(ts) and body["meta"]["has_more"] is False
        bar = body["bars"][0]
        assert bar["delta"] is not None and bar["cvd"] is None  # tape flow; cvd never faked
        # #2017 / 22-api: every stored bar carries its identity (index, generation).
        assert all(isinstance(b["index"], int) and b["generation"] == 0 for b in body["bars"])
        if bar_type != "time":
            assert "close_time" in bar

    def test_include_delta_false_omits_order_flow(self) -> None:
        q = {**_P, "bar_type": "tick", "param": "100", "include_delta": "false"}
        bar = _client().get("/market/bars", params=q).json()["bars"][0]
        assert not {"delta", "cvd", "min_delta", "max_delta"} & set(bar)


class TestRefusals:
    def test_pre_recording_window_is_no_data_recorded(self) -> None:
        """Gherkin: tick:500 before recording -> 422 no_data_recorded, no bars, no read."""
        fetch = _Fetch()
        before = bars_endpoint_422_no_data_recorded_total._value.get()  # type: ignore[attr-defined]  # prometheus internals
        q = {**_P, "bar_type": "tick", "param": "500"}
        body = _problem(_client(recording_us=_T0 + 1, fetch=fetch).get("/market/bars", params=q),
                        422, "no_data_recorded")  # fmt: skip
        assert "bars" not in body and fetch.calls == 0
        assert "Choose a later window" in body["detail"] and "BTCUSDT" in body["detail"]
        assert bars_endpoint_422_no_data_recorded_total._value.get() == before + 1  # type: ignore[attr-defined]  # prometheus internals

    def test_no_tape_at_all_is_no_data_recorded(self) -> None:
        q = {**_P, "bar_type": "volume", "param": "5"}
        _problem(_client(recording_us=None).get("/market/bars", params=q), 422, "no_data_recorded")

    def test_no_data_recorded_wins_over_bar_window_too_large(self) -> None:
        """22-api precedence: pre-recording AND over the window cap -> no_data_recorded."""
        q = {**_P, "bar_type": "tick", "param": "100", "from": "2020-01-01T00:00:00Z"}
        _problem(_client().get("/market/bars", params=q), 422, "no_data_recorded")

    def test_time_bars_are_not_refused_before_recording(self) -> None:
        q = {**_P, "bar_type": "time", "param": "1"}
        assert _client(recording_us=_NOW).get("/market/bars", params=q).status_code == 200

    def test_path_traversal_param_is_400_naming_param_with_no_read(self) -> None:
        """Gherkin: param="../../etc" -> 400 validation_failed, nothing reaches storage."""
        fetch = _Fetch()
        q = {**_P, "bar_type": "tick", "param": "../../etc"}
        body = _problem(
            _client(fetch=fetch).get("/market/bars", params=q), 400, "validation_failed"
        )
        assert "param" in body["detail"] and "../" not in body["detail"] and fetch.calls == 0

    @pytest.mark.parametrize(
        ("bar_type", "param"),
        [("tick", "0"), ("tick", "abc"), ("bogus", "1"), ("time", "7"), ("volume", "1" * 25)],
    )
    def test_malformed_param_is_400(self, bar_type: str, param: str) -> None:
        q = {**_P, "bar_type": bar_type, "param": param}
        _problem(_client().get("/market/bars", params=q), 400, "validation_failed")

    @pytest.mark.parametrize(("bar_type", "param"), [("tick", "99"), ("range", "1"),
                                                      ("renko", "100001")])  # fmt: skip
    def test_param_outside_sr_e12_03_bounds_is_400(self, bar_type: str, param: str) -> None:
        q = {**_P, "bar_type": bar_type, "param": param}
        body = _problem(_client().get("/market/bars", params=q), 400, "validation_failed")
        # renko bounds are enforced inside from_wire (E12-S04): generic invalid-param text
        detail = body["detail"]
        assert "between" in detail or (bar_type == "renko" and "not valid" in detail)

    @pytest.mark.parametrize(("bar_type", "param"), [("renko", "atr:14"), ("pnf", "10:3"),
                                                      ("heikin_ashi", "5")])  # fmt: skip
    def test_unbuildable_type_is_422_naming_alternatives(self, bar_type: str, param: str) -> None:
        q = {**_P, "bar_type": bar_type, "param": param}
        body = _problem(_client().get("/market/bars", params=q), 422, "validation_failed")
        assert "bar_type=time" in body["detail"]

    def test_time_window_over_400_days(self) -> None:
        q = {**_P, "bar_type": "time", "param": "1", "from": "2020-01-01T00:00:00Z"}
        _problem(_client().get("/market/bars", params=q), 422, "bar_window_too_large")

    def test_non_time_window_over_31_days(self) -> None:
        q = {**_P, "bar_type": "tick", "param": "100", "to": "2099-01-01T00:00:00Z"}
        _problem(_client().get("/market/bars", params=q), 422, "bar_window_too_large")

    def test_unknown_symbol_is_422(self) -> None:
        q = {**_P, "symbol": "NOPEUSDT", "bar_type": "tick", "param": "100"}
        _problem(_client().get("/market/bars", params=q), 422, "validation_failed")

    def test_reader_not_composed_is_503(self) -> None:
        q = {**_P, "bar_type": "tick", "param": "100"}
        _problem(_client(wired=False).get("/market/bars", params=q), 503, "store_unavailable")


class TestPaginationAndRbac:
    _Q: ClassVar[dict[str, Any]] = {**_P, "bar_type": "tick", "param": "100", "limit": 1}

    def _walk(self, client: TestClient, q: dict[str, Any]) -> tuple[list[str], int]:
        """Start WITHOUT a cursor; follow only server-issued `next_cursor` (#2087 A1)."""
        cursor: str | None = None
        seen: list[str] = []
        pages = 0
        while True:
            resp = client.get(
                "/market/bars", params=q if cursor is None else {**q, "cursor": cursor}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            KlineResponse.model_validate(body)
            meta = body["meta"]
            assert meta["count"] == len(body["bars"]) <= q["limit"]
            assert meta["has_more"] is (meta["next_cursor"] is not None)
            assert body["bars"] or not meta["has_more"]  # never an empty page claiming more
            seen += [b["t"] for b in body["bars"]]
            pages += 1
            assert pages < 500
            cursor = meta["next_cursor"]
            if cursor is None:
                return seen, pages

    def test_uncursored_request_is_the_first_page_with_a_cursor(self) -> None:
        body = _client().get("/market/bars", params=self._Q).json()
        assert body["meta"]["count"] == 1 and body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"]

    @pytest.mark.parametrize(("bar_type", "param"), list(_SERIES))
    def test_round_trip_from_no_cursor_visits_every_bar_once(
        self, bar_type: str, param: str
    ) -> None:
        """Row-based paging: limit=2 over every stored series -> ceil(n/2) non-empty pages."""
        stored = _STORE[bar_param_for(_SERIES[(bar_type, param)])]
        # A time bar opens on its grid, before the first trade; start the window there.
        q = {**_P, "bar_type": bar_type, "param": param, "limit": 2,
             "from": _iso(min(int(str(r["ts"])) for r in stored))}  # fmt: skip
        expected = len(stored)
        seen, pages = self._walk(_client(), q)
        assert len(seen) == expected and seen == sorted(seen)
        assert pages == -(-expected // 2)

    def test_cursor_is_bound_to_series_and_route(self) -> None:
        """A klines cursor, or one for another bar_type/param/symbol, is invalid_cursor."""
        from candleviewer.api.market_response import cursor_scope, encode_cursor

        client = _client()
        cursor = client.get("/market/bars", params=self._Q).json()["meta"]["next_cursor"]
        for other in ({"param": "200"}, {"bar_type": "volume", "param": "5"}):
            resp = client.get("/market/bars", params={**self._Q, **other, "cursor": cursor})
            _problem(resp, 400, "invalid_cursor")
        klines = encode_cursor(cursor_scope("klines", "BTCUSDT", "1"), _T0)
        resp = client.get("/market/bars", params={**self._Q, "cursor": klines})
        _problem(resp, 400, "invalid_cursor")
        early = {**self._Q, "to": _iso(_T0), "cursor": cursor}  # cursor after `to`
        _problem(client.get("/market/bars", params=early), 400, "invalid_cursor")

    @pytest.mark.parametrize("bad", ["nope", "a" * 129])
    def test_bad_cursor_is_invalid_cursor_without_echo(self, bad: str) -> None:
        resp = _client().get("/market/bars", params={**self._Q, "cursor": bad})
        _problem(resp, 400, "invalid_cursor")
        assert bad not in resp.text

    def test_no_session_is_401(self) -> None:
        _problem(_client(perms=None).get("/market/bars", params=self._Q), 401, "unauthenticated")

    def test_forbidden_role_is_403_and_nothing_is_read(self) -> None:
        fetch = _Fetch()
        resp = _client(perms=frozenset({"orders:read"}), fetch=fetch).get(
            "/market/bars", params=self._Q
        )
        assert "bars" not in _problem(resp, 403, "forbidden") and fetch.calls == 0


def test_stored_corpus_is_non_trivial() -> None:
    assert all(len(v) >= 2 for v in _STORE.values()), {k: len(v) for k, v in _STORE.items()}


class TestRequestEdges:
    _Q: ClassVar[dict[str, Any]] = {"symbol": "BTCUSDT", "bar_type": "tick", "param": "100"}

    @pytest.mark.parametrize(
        "window",
        [{"from": "yesterday"}, {}, {"from": _iso(_NOW), "to": _iso(_T0)}],
        ids=["unparseable", "missing-from", "inverted"],
    )
    def test_bad_window_is_400(self, window: dict[str, str]) -> None:
        resp = _client().get("/market/bars", params={**self._Q, **window})
        _problem(resp, 400, "validation_failed")

    def test_naive_timestamps_are_utc_and_to_defaults_to_now(self) -> None:
        naive = _iso(_T0).removesuffix("Z")
        resp = _client().get("/market/bars", params={**self._Q, "from": naive})
        assert resp.status_code == 200 and resp.json()["meta"]["count"] > 0

    def test_storage_timeout_is_503(self) -> None:
        class _Down(_Fetch):
            async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
                raise ConnectionError("questdb down")

        resp = _client(fetch=_Down()).get("/market/bars", params={**_P, **self._Q})
        _problem(resp, 503, "store_unavailable")

    def test_include_open_serves_the_forming_bar(self) -> None:
        spec = _SERIES[("tick", "100")]
        forming = bar_row(_build(spec)[-1].model_copy(update={"closed": False}), spec)
        _STORE["tick:100"].append(forming)
        try:
            q = {**_P, **self._Q}
            closed = _client().get("/market/bars", params=q).json()["bars"]
            opened = _client().get("/market/bars", params={**q, "include_open": "true"}).json()
            assert [b["confirm"] for b in opened["bars"]][-1] is False
            assert len(opened["bars"]) == len(closed) + 1
        finally:
            _STORE["tick:100"].remove(forming)

    def test_no_resolver_fails_closed_501(self) -> None:
        app = FastAPI()
        app.include_router(make_market_bars_router(lambda: None, now_us=lambda: _NOW))
        resp = TestClient(app).get("/market/bars", params={**_P, **self._Q})
        assert resp.status_code == 501 and Problem.model_validate(resp.json())


def test_time_bar_estimate_over_250k_bars_is_refused_before_any_read() -> None:
    """SR-E12-02 (#2089 security low): ceil(window / interval) <= 250 000 for time bars.
    200 d of 1m bars = 288 000 bars: inside the 400 d cap, over the estimate."""
    fetch = _Fetch()
    q = {**_P, "bar_type": "time", "param": "1", "to": _iso(_T0 + 200 * 86_400_000_000)}
    body = _problem(_client(fetch=fetch).get("/market/bars", params=q), 422, "bar_window_too_large")
    assert "250,000" in body["detail"] and fetch.calls == 0
    ok = {**q, "to": _iso(_T0 + 150 * 86_400_000_000)}  # 216 000 bars: allowed, paged
    assert _client().get("/market/bars", params=ok).status_code == 200


class TestAdversarialRound:
    """#2089 adversarial review: M1 dropped-row paging, L2 equal-ts pin, L3 unwired provider,
    and the before-`from` cursor rejection."""

    _Q: ClassVar[dict[str, Any]] = {**_P, "bar_type": "tick", "param": "100", "limit": 2}

    def _walk(self, q: dict[str, Any]) -> list[str]:
        client, cursor, seen = _client(), None, []
        for _ in range(100):
            body = client.get(
                "/market/bars", params=q if cursor is None else {**q, "cursor": cursor}
            ).json()
            assert body["bars"] or not body["meta"]["has_more"]
            seen += [b["t"] for b in body["bars"]]
            cursor = body["meta"]["next_cursor"]
            if cursor is None:
                return seen
        raise AssertionError("paging did not terminate")

    def test_corrupt_row_at_page_boundary_keeps_paging(self) -> None:
        """M1: the last row of page 1 fails its checksum; has_more stays true and page 2
        continues, so no later bar becomes unreachable."""
        rows = _STORE["tick:100"]
        original = rows[1]
        rows[1] = {**original, "close": 1.0}  # value changed, checksum now mismatches
        try:
            client = _client()
            first = client.get("/market/bars", params=self._Q).json()
            assert first["meta"]["has_more"] is True and first["meta"]["next_cursor"]
            assert [b["t"] for b in first["bars"]] == [_iso_t(rows[0])]
            seen = self._walk(self._Q)
            assert len(seen) == len(rows) - 1  # only the corrupt bar is missing
        finally:
            rows[1] = original

    @pytest.mark.parametrize("limit", [1, 2])
    def test_equal_ts_renko_bricks_are_each_served_once_across_pages(self, limit: int) -> None:
        """#2017 (replaces the #2089 L2 skip pin): three renko bricks share one `ts` (index
        0..2). Paging by `(ts, generation, index)` serves each exactly once, then has_more=false."""
        rows = _STORE["renko:20"]
        saved = list(rows)
        ts = int(str(_STORE["renko:20"][0]["ts"]))
        bricks = []
        for i in range(3):
            b = {**saved[0], "ts": ts, "index": i}
            b["row_checksum"] = row_checksum(b)
            bricks.append(b)
        rows[:] = bricks
        try:
            client, cursor, got = _client(), None, []
            q = {**_P, "bar_type": "renko", "param": "20", "limit": limit}
            for _ in range(10):
                body = client.get(
                    "/market/bars", params=q if cursor is None else {**q, "cursor": cursor}
                ).json()
                KlineResponse.model_validate(body)
                got.append([b["index"] for b in body["bars"]])
                assert {b["generation"] for b in body["bars"]} <= {0}
                assert len({b["t"] for b in body["bars"]}) <= 1  # t repeats; identity is index
                cursor = body["meta"]["next_cursor"]
                assert body["meta"]["has_more"] is (cursor is not None)
                if cursor is None:
                    break
            assert got == ([[0], [1], [2]] if limit == 1 else [[0, 1], [2]])
        finally:
            rows[:] = saved

    def test_klines_v1_cursor_is_invalid_on_non_time_bars(self) -> None:
        from candleviewer.api.market_response import cursor_scope, encode_cursor

        v1 = encode_cursor(cursor_scope("bars", "BTCUSDT", "tick:100"), _T0)
        _problem(_client().get("/market/bars", params={**self._Q, "cursor": v1}),
                 400, "invalid_cursor")  # fmt: skip

    def test_sessions_provider_refuses_pre_recording_window_with_recording_started_at(
        self,
    ) -> None:
        """E16-T04 (replaces the E12-T05 503-when-unwired case): the real provider is the
        earliest session `first_event_ts` (`CoverageService`); a window before it is 422
        `no_data_recorded` carrying `recording_started_at`, never an empty success."""
        import asyncio

        from candleviewer.recorder.coverage import CoverageService
        from candleviewer.recorder.sessions import to_dt
        from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

        store = MemRecorderStore()
        sid = asyncio.run(store.open_session_at(
            recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
            ws_endpoint="x", started_at=to_dt(_T0 + 60_000_000)))  # fmt: skip
        asyncio.run(store.touch_session_events(sid, first=to_dt(_T0 + 60_000_000),
                                               last=to_dt(_NOW)))  # fmt: skip
        svc = CoverageService(store, now_us=UsClock(_NOW))
        fetch = _Fetch()
        app = FastAPI()
        app.include_router(make_market_bars_router(
            lambda: BarReader(fetch, _noop), recording_started_at_us=svc.recording_started_at_us,
            principal_resolver=_Resolver(frozenset({"marketdata:read"})),
            symbol_listed=lambda s: s == "BTCUSDT", now_us=lambda: _NOW))  # fmt: skip
        resp = TestClient(app, client=("127.0.0.1", 50000)).get("/market/bars", params=self._Q)
        body = _problem(resp, 422, "no_data_recorded")
        assert body["recording_started_at"] == _iso(_T0 + 60_000_000).replace("Z", "+00:00")
        assert fetch.calls == 0
        # No recording at all: still 422, `recording_started_at: null`.
        none = _problem(_client(recording_us=None).get("/market/bars", params=self._Q),
                        422, "no_data_recorded")  # fmt: skip
        assert none["recording_started_at"] is None
        # The router itself still fails closed (503) if composed without a provider.
        resp = _client(recording_wired=False, fetch=fetch).get("/market/bars", params=self._Q)
        _problem(resp, 503, "store_unavailable")
        time_q = {**_P, "bar_type": "time", "param": "1"}  # time bars need no recording fact
        assert _client(recording_wired=False).get("/market/bars", params=time_q).status_code == 200

    def test_cursor_before_from_is_invalid_cursor(self) -> None:
        from candleviewer.api.market_response import cursor_scope, encode_key_cursor

        early = encode_key_cursor(
            cursor_scope("bars", "BTCUSDT", "tick:100"), (_T0 - 60_000_000, 0, 0)
        )
        resp = _client().get("/market/bars", params={**self._Q, "cursor": early})
        _problem(resp, 400, "invalid_cursor")


def _iso_t(row: dict[str, object]) -> str:
    from candleviewer.api.market_response import iso_us

    return iso_us(int(str(row["ts"])))
