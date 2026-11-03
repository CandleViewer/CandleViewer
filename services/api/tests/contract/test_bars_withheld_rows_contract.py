"""#452 F9 / #538: a `bars_*` row withheld for a failed checksum (SR-E12-11) is named in
`meta.coverage_holes` on `GET /market/bars` and on the WS `bars` snapshot (23 §6.1) (22
`DataMeta.coverage_holes`: "a range of the window the server cannot serve from its store is listed
here too, so a missing range is named, never silently absent"). Withholding is unchanged.

The stored rows, reader fake and route wiring are `test_market_bars_contract`'s (the recorded
BTCUSDT tape through the real builders); the WS side hydrates a real `SeriesStore` through the
real `read_tail`. The F9 assertion is the strict xfail of #5358
(`tests/security/bars/test_integrity.py::test_integrity_withheld_bar_is_named_to_the_client`),
restated here so the fix carries its own pin; the WS check is its equivalent
(`test_market_markers_parity_contract` holds the klines one and the parity check).
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, Withheld, bars_checksum_mismatch_total, row_key
from candleviewer.bars.rows import bar_param_for, row_checksum
from candleviewer.bars.series_store import SeriesStore
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.ws.bars_source import BarsSnapshotSource, _withheld_holes
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import TopicEmitter
from candleviewer.ws.topics import effective_options, parse_topic
from tests.contract import _market_world as mw
from tests.contract import test_market_bars_contract as bars_world
from tests.unit.ws._seq_support import validate

_TIME: Final = bars_world._SERIES["time", "1"]
_TICK: Final = bars_world._SERIES["tick", "100"]
_MIN: Final = 60_000_000


def _mismatches(spec: BarSpec) -> float:
    return float(bars_checksum_mismatch_total.labels(f"bars_{spec.kind}", "mismatch")._value.get())


def _edited(row: dict[str, object]) -> dict[str, object]:
    return {**row, "close": 1.0}  # changed after its checksum was written


def _store_with(
    spec: BarSpec, *edit: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The stored rows of `spec` with the rows at positions `edit` edited; and those rows."""
    rows = [dict(r) for r in bars_world._STORE[bar_param_for(spec)]]
    for n in edit:
        rows[n] = _edited(rows[n])
    return rows, [rows[n] for n in edit]


def _get_bars(client: TestClient, spec: BarSpec, **q: Any) -> dict[str, Any]:
    bar_type, param = next(k for k, v in bars_world._SERIES.items() if v == spec)
    resp = client.get("/market/bars", params={**bars_world._P, "bar_type": bar_type,
                                              "param": param, **q})  # fmt: skip
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    KlineResponse.model_validate(body)  # `meta` is `BarsMeta`
    return body


def _span(spec: BarSpec, rows: list[dict[str, object]], row: dict[str, object]) -> dict[str, int]:
    """The hole a withheld `row` leaves, by the #5581 ruling: `[open, next open)`, the next open
    being the first later one among the stored `rows`; with none, a time bar's width or 1 µs."""
    ts = int(str(row["ts"]))
    later = [int(str(r["ts"])) for r in rows if int(str(r["ts"])) > ts]
    end = min(later) if later else ts + (_MIN if spec.kind == "time" else 1)
    return {"start_us": ts, "end_us": end}


def _client(rows: list[dict[str, object]], spec: BarSpec) -> TestClient:
    return bars_world._client(fetch=bars_world._Fetch({bar_param_for(spec): rows}))


@pytest.mark.parametrize("spec", [_TIME, _TICK], ids=["time", "tick"])
def test_bars_a_withheld_row_is_named_in_coverage_holes(spec: BarSpec) -> None:
    """#452 F9 (the #5358 xfail's assertions): the edited row is withheld and counted, and the
    page names its range, so a chart never reads the gap as a quiet market."""
    control = _get_bars(_client(_store_with(spec)[0], spec), spec)["bars"]
    rows, (edited,) = _store_with(spec, 7 if spec.kind == "time" else 2)  # tick 100: 5 rows
    before = _mismatches(spec)
    body = _get_bars(_client(rows, spec), spec)
    assert body["bars"] == [
        b for b in control if b["index"] != edited["index"]
    ]  # the rest as before
    assert _mismatches(spec) == before + 1
    at = int(str(edited["ts"]))
    holes = body["meta"].get("coverage_holes") or []
    assert any(h["start_us"] <= at < h["end_us"] for h in holes), sorted(body["meta"])
    assert holes == [_span(spec, rows, edited)]


@pytest.mark.parametrize("spec", [_TIME, _TICK], ids=["time", "tick"])
def test_bars_a_clean_store_lists_no_coverage_holes(spec: BarSpec) -> None:
    rows, _ = _store_with(spec)
    assert "coverage_holes" not in _get_bars(_client(rows, spec), spec)["meta"]


@pytest.mark.parametrize("spec", [_TIME, _TICK], ids=["time", "tick"])
def test_bars_a_withheld_row_is_listed_once_on_the_page_that_spans_it(spec: BarSpec) -> None:
    """Paging is unchanged (the raw fetch decides `has_more`), and the withheld row at a page
    boundary (here the 4th row with `limit=3`: a non-time page's next key) is listed by the page
    whose span holds it, on no other page."""
    clean = len(_get_bars(_client(_store_with(spec)[0], spec), spec)["bars"])
    rows, (edited,) = _store_with(spec, 3)
    client = _client(rows, spec)
    cursor, served, listed = None, 0, []
    for _ in range(500):
        q: dict[str, Any] = {"limit": 3} | ({} if cursor is None else {"cursor": cursor})
        body = _get_bars(client, spec, **q)
        served += len(body["bars"])
        listed += body["meta"].get("coverage_holes", [])
        if (cursor := body["meta"]["next_cursor"]) is None:
            break
    assert served == clean - 1 and listed == [_span(spec, rows, edited)]


def test_bars_m1_a_withheld_sibling_at_the_next_pages_open_time_is_listed() -> None:
    """M1 (the #5581 Opus lens's probe): row 1 of the tick-100 series re-signed with row 2's `ts`,
    then edited. With `limit=2` it is withheld at the next page's first `ts` but before its key, so
    the next page starts past it: only this page can name it, as `[ts, ts + 1)` (a 1 µs report
    past the span). It printed `PAGED served 4 listed []` before the fix."""
    rows = [dict(r) for r in bars_world._STORE[bar_param_for(_TICK)]]
    moved = {**rows[1], "ts": rows[2]["ts"]}
    moved["row_checksum"] = row_checksum(moved)
    rows[1] = _edited(moved)
    client, cursor, served, listed = _client(rows, _TICK), None, 0, []
    for _ in range(50):
        q: dict[str, Any] = {"limit": 2} | ({} if cursor is None else {"cursor": cursor})
        body = _get_bars(client, _TICK, **q)
        served += len(body["bars"])
        listed += body["meta"].get("coverage_holes", [])
        if (cursor := body["meta"]["next_cursor"]) is None:
            break
    at = int(str(rows[2]["ts"]))
    assert (served, listed) == (len(rows) - 1, [{"start_us": at, "end_us": at + 1}])


def test_bars_e12_q04_world_names_the_withheld_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    """BQ 8: the recorded E12-Q04 world (`_market_world`, `create_app`'s composition), one stored
    row edited as #5358's `test_integrity.py` does; its marked bar keeps `gap_before`/`tape_gap`."""
    rows = {k: list(v) for k, v in mw.stored_rows().items()}
    edited = rows["1m"][7] = {**rows["1m"][7], "close": 1.0}
    monkeypatch.setattr(mw, "stored_rows", lambda: rows)
    query = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1", "limit": 5000,
             "from": bars_world._iso(mw.T0), "to": bars_world._iso(mw.NOW)}  # fmt: skip
    resp = mw.MarketWorld().get("getBars", query)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    KlineResponse.model_validate(body)
    assert edited["index"] not in {b["index"] for b in body["bars"]}
    assert body["meta"]["coverage_holes"] == [_span(_TIME, rows["1m"], edited)]
    marked = next(b for b in body["bars"] if b["index"] == rows["1m"][1]["index"])
    assert marked.get("gap_before") is True and marked.get("tape_gap") is True


# -- the WS `bars` snapshot ----------------------------------------------------------------------


class _Tail:
    """`read_tail`'s statements over `rows`: the table-row bound finds fewer rows than it scans
    (no bound), and the tail is the builder rows from its start, newest first, limited."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        if sql.startswith("SELECT ts "):
            return []
        start = ts_us_from_row(params[2])
        rows = [r for r in self._rows if int(str(r["ts"])) >= start and r["index"] is not None]
        return sorted(rows, key=row_key, reverse=True)[: int(sql.rsplit("LIMIT ", 1)[1])]


async def _snapshot(rows: list[dict[str, object]]) -> dict[str, Any]:
    reader = BarReader(_Tail(rows), bars_world._noop, now_us=lambda: bars_world._NOW)
    store = SeriesStore(reader.read_tail)
    await store.ensure("BTCUSDT", _TIME)
    out: list[dict[str, Any]] = []
    emitter = TopicEmitter(out.append, connection_id="c", wall_ms=lambda: 1, clock=lambda: 0.0,
                           source=BarsSnapshotSource(store, lambda s: (1, 3)))  # fmt: skip
    topic = parse_topic("bars.BTCUSDT.time.1")
    opts = {"encoding": "structured", "history": 1000}
    assert emitter.snapshot(Subscription("s_01", topic, opts, effective_options(topic, opts)),
                            "initial")  # fmt: skip
    for frame in out:
        validate(frame)  # 23 §13 `snapMeta`
    return out[0]


async def test_ws_snapshot_names_a_withheld_row_as_rest_does() -> None:
    """The WS `SilentGap` check: the series store hydrates from the stored rows through the real
    `read_tail`, the edited row is withheld, and the snapshot names it as `/market/bars` does."""
    rows, (edited,) = _store_with(_TIME, 7)
    frame = await _snapshot(rows)
    assert frame["meta"]["coverage_holes"] == [_span(_TIME, rows, edited)]
    rest = _get_bars(_client(rows, _TIME), _TIME)
    assert rest["meta"]["coverage_holes"] == frame["meta"]["coverage_holes"]


async def test_ws_snapshot_of_a_clean_store_names_no_hole() -> None:
    rows, _ = _store_with(_TIME)
    assert "coverage_holes" not in (await _snapshot(rows))["meta"]


@pytest.mark.parametrize(("spec", "sent", "listed"), [
    (_TIME, [0, 2], [(_MIN, 2 * _MIN)]),  # no bar sent at its open time
    (_TIME, [0, 1], []),  # a bar sent at its open time fills it (one bar per open time)
    (_TICK, [0, 2], [(_MIN, _MIN + 11)]),
    (_TICK, [0, 1], [(_MIN, _MIN + 11)]),  # L2: listed as on REST, whatever is sent
])  # fmt: skip
def test_ws_withheld_holes_list_only_what_no_sent_bar_fills(
    spec: BarSpec, sent: list[int], listed: list[tuple[int, int]]
) -> None:
    bars = [Bar.model_construct(open_time=i * _MIN, index=i) for i in sent]
    withheld = (Withheld((_MIN, 0, 1), _MIN, _MIN + (_MIN if spec.kind == "time" else 11)),
                Withheld((-_MIN, 0, -1), -_MIN, 0))  # before the oldest bar sent  # fmt: skip
    assert _withheld_holes(spec, withheld, bars) == listed
