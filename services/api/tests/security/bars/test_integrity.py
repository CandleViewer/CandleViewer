"""E12-X02 integrity (#452; X01 AC-09, AC-10 and #452 AC5): a hostile upstream print never reaches
a bar, and a tampered stored row is never served.

- Upstream: E08-X02's `Rig` (`tests/security/ingestion/_harness.py`, in process, no socket) feeds
  the recorded BTCUSDT trade tape (C-13.5) through the production `TradeStream`, with the event
  window `create_app` wires, onto a real `Bus`, into a real `BarBuilderSet`. The same tape is fed
  twice: clean, and with a hostile print after every 40th recorded one. Every bar of every spec is
  equal across the two runs, each hostile frame is counted as rejected and the replayed duplicate
  as suppressed.
- Storage: a `bars_*` row edited after its checksum was written is withheld from `/market/bars`,
  counted and never served; the rest of the page is. The page says nothing of the withheld bar
  (#452 findings row F9, new here, a strict xfail on `SilentGap`).

Cited, not repeated here: the unit pins of the builders (late and out-of-order prints fold into the
forming bar, `tests/unit/bars/test_activity_builders.py`, `test_time_builder.py`; a print spanning
10^6 bricks, `test_volume_print_cap.py`), the >8 MiB and wrong-spec blob (`tests/unit/bars/
test_builder_set_persistence.py`, `too_large`), the oversized kline page refused before a row is
parsed (`tests/unit/exchange/bybit/test_klines.py`, `oversized`) and the reader's checksum unit
(`tests/unit/bars/test_bars_persistence.py`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from candleviewer.bars import reader
from candleviewer.bars.builder_set import BarBuilderSet
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import bars_checksum_mismatch_total
from candleviewer.bars.state_store import StateStore
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion import metrics as im
from candleviewer.ingestion.rejection import EventWindow
from candleviewer.ingestion.trade_stream import TradeStream
from tests.contract import _market_world as mw
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars.conftest import BAR_READ, Stores
from tests.security.ingestion._harness import Rig
from tests.security.ingestion.corpus import TRADE_TOPIC, TRADES, trade
from tests.unit.bars._set_harness import Clock, RecordingSink, settle

SYMBOL: Final = "BTCUSDT"
SPECS: Final = (
    BarSpec(kind="time", interval_ms=60_000),
    BarSpec(kind="tick", tick_count=10),
    BarSpec(kind="volume", volume_threshold=Decimal(2)),
)
#: 3000-01-01T00:00:00Z in ms: past the parser's absolute bound (2100, `frame_guard.MAX_TS_MS`).
YEAR_3000_MS: Final = 32_503_680_000_000
#: 2099-01-01T00:00:00Z in ms: inside that bound, so with an envelope that agrees with it only the
#: event window (now + 5 s) refuses it.
YEAR_2099_MS: Final = 4_070_908_800_000
EVERY: Final = 40
_Bars = list[tuple[str, str, Bar]]


def _ts(frame: str) -> int:
    ts: int = json.loads(frame)["data"][0]["T"]
    return ts


def _forged_envelope(ts_ms: int) -> str:
    """A frame whose envelope `ts` agrees with its far-future print: the parser's skew check
    against the envelope passes, so only the event window refuses it."""
    msg = json.loads(trade(T=ts_ms, i="h-forged"))
    msg["ts"] = ts_ms
    return json.dumps(msg, separators=(",", ":"))


#: One hostile frame per kind; `n` is the recorded frame it follows. Each is a whole frame the
#: stream must reject (`trade_prints_rejected_total`), never a print it publishes.
HOSTILE: Final[dict[str, Callable[[int], str]]] = {
    "negative_size": lambda n: trade(v="-0.5", i=f"h-neg-{n}", T=_ts(TRADES[n])),
    "zero_size": lambda n: trade(v="0", i=f"h-zero-{n}", T=_ts(TRADES[n])),
    "nan_price": lambda n: trade(p="__P__", i=f"h-nan-{n}").replace('"__P__"', "NaN"),
    "absurd_price": lambda n: trade(p="1e308", i=f"h-big-{n}", T=_ts(TRADES[n])),
    "string_ts": lambda n: trade(T="soon", i=f"h-str-{n}"),
    "year_3000": lambda n: trade(T=YEAR_3000_MS, i=f"h-3000-{n}"),
    "year_2099_forged_envelope": lambda n: _forged_envelope(YEAR_2099_MS),
    "wrong_symbol_shape": lambda n: trade(s=["BTCUSDT"], i=f"h-sym-{n}"),
}


class BarsDiverged(AssertionError):
    """A bar of the hostile run differs from the clean run's: a hostile print reached a builder."""


class TamperedServed(AssertionError):
    """The page of the tampered store is not the clean page less the edited row."""


def _stream(rig: Rig, *, window: bool) -> TradeStream:
    """The Rig's trade stream as `create_app` builds it: with the event window (#1892) the Rig
    leaves out, on the Rig's bus and clock. `window=False` is the negative control's removal."""
    now_us = lambda: int(rig.now_s * 1_000_000)  # noqa: E731 -- the Rig's own clock, in µs
    stream = TradeStream(
        bus=rig.bus, env="live", set_desired=lambda _t: None, parse_frame=parse_trade_frame,
        topic_for=trade_topic, is_listed=lambda s: s == SYMBOL, touch=lambda _t: None,
        clock=lambda: rig.now_s, now_us=now_us,
        event_window=EventWindow(now_us, lambda _s: None) if window else None,
    )  # fmt: skip
    stream.acquire("x02", SYMBOL)
    return stream


async def _run(tmp_path: Path, *, hostile: bool, window: bool = True) -> _Bars:
    """Every bar the set emits for `SPECS` over the recorded tape, hostile prints interleaved."""
    rig, sink = Rig(), RecordingSink()
    rig.now_s = _ts(TRADES[-1]) / 1000 + 60  # the wall clock a minute past the last print
    rig.trades = _stream(rig, window=window)
    bars = BarBuilderSet(
        rig.bus, "live",
        EmitRouter([sink]),
        StateStore(tmp_path), now_us=Clock(int(rig.now_s * 1_000_000)),
    )  # fmt: skip
    for i, spec in enumerate(SPECS):
        await bars.register(spec, SYMBOL, f"chart-{i}", user="u1")
    kinds = list(HOSTILE.values())
    for n, frame in enumerate(TRADES):
        await rig.feed(frame)
        if hostile and n % EVERY == EVERY - 1:
            await rig.feed(kinds[(n // EVERY) % len(kinds)](n))
            await rig.feed(TRADES[n])  # the same print again: a duplicate trade id
        await rig.trades.wait_backfills()
        rig.drain()  # the Rig's own subscriber: kept empty, as the pump's consumers keep theirs
    await settle(rig.bus, bars)
    await bars.stop()
    return sink.bars


def _counted() -> tuple[float, float]:
    dup = im.trade_duplicates_suppressed_total.labels(symbol=SYMBOL)._value.get()
    return im.trade_prints_rejected_total._value.get(), dup


async def check_hostile_prints_change_no_bar(tmp_path: Path, *, window: bool = True) -> None:
    """The defended outcome: the hostile run's bars equal the clean run's, each hostile frame is
    counted once as rejected, and every replayed print is suppressed as a duplicate."""
    clean = await _run(tmp_path / "clean", hostile=False, window=window)
    assert {h for h, _, _ in clean} == {s.spec_hash for s in SPECS}  # every spec emitted
    assert sum(k == "close" for _, k, _ in clean) >= 3 * len(SPECS)
    rejected, duplicates = _counted()
    dirty = await _run(tmp_path / "dirty", hostile=True, window=window)
    if dirty != clean:
        raise BarsDiverged(
            f"bars diverge; latest bar opens at {max(b.open_time for *_, b in dirty)}"
        )
    injected = len(TRADES) // EVERY
    assert injected >= len(HOSTILE)  # every hostile kind is fed at least once
    now_rejected, now_duplicates = _counted()
    assert now_rejected == rejected + injected  # one per hostile frame
    # each replay at least: a rejected frame that names its symbol opens a gap, and the heal that
    # follows offers prints the ring already holds, which it suppresses as well
    assert now_duplicates >= duplicates + injected


async def test_integrity_hostile_prints_between_recorded_ones_change_no_bar(tmp_path: Path) -> None:
    """#452 AC5 / X01 AC-10, with the event window `create_app` wires."""
    await check_hostile_prints_change_no_bar(tmp_path)


async def test_integrity_control_without_the_event_window_a_forged_print_reaches_a_bar(
    tmp_path: Path,
) -> None:
    """Negative control: with no event window, the 2099 print whose envelope agrees with it passes
    the parser and opens a time bar in 2099, so the check turns red on the bars."""
    with pytest.raises(BarsDiverged, match=f"latest bar opens at {YEAR_2099_MS * 1000}$"):
        await check_hostile_prints_change_no_bar(tmp_path, window=False)


def test_integrity_corpus_frame_is_the_recorded_tape_topic() -> None:
    """Guard: the hostile frames ride the recorded tape's topic, so the stream reads them as the
    same feed rather than ignoring an unknown topic."""
    assert {json.loads(f)["topic"] for f in TRADES} == {TRADE_TOPIC}


# -- a tampered stored row (AC-09, SR-E12-11) --------------------------------------------------


def _mismatches() -> float:
    return float(bars_checksum_mismatch_total.labels("bars_time", "mismatch")._value.get())


def check_edited_row_withheld(stores: Stores, monkeypatch: pytest.MonkeyPatch) -> None:
    """The defended outcome: a `bars_time` row whose close was edited after its checksum was
    written is absent from the page, every other row is served as before, and one integrity event
    is counted. The first read, of the untouched store, is the clean page."""
    query = {"symbol": SYMBOL, "bar_type": "time", "param": "1", "limit": 5000,
             "from": _iso(mw.T0), "to": _iso(mw.NOW)}  # fmt: skip
    control = stores.get("getBars", query).json()["bars"]
    rows = {k: list(v) for k, v in mw.stored_rows().items()}
    edited = rows["1m"][7] = {**rows["1m"][7], "close": 1.0}
    monkeypatch.setattr(mw, "stored_rows", lambda: rows)
    before = _mismatches()
    resp = stores.get("getBars", query)
    assert resp.status_code == 200, resp.text[:300]
    assert len(control) > 10 and stores.calls[BAR_READ] == 2
    served = resp.json()["bars"]
    expected = [b for b in control if b["index"] != edited["index"]]
    if served != expected:
        raise TamperedServed(f"served {len(served)} bars, expected {len(expected)}")
    assert _mismatches() == before + 1


def test_integrity_hand_edited_row_is_withheld_never_served(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X01 AC-09 through `/market/bars` (the reader's unit: `test_bars_persistence.py`)."""
    check_edited_row_withheld(stores, monkeypatch)


def test_integrity_control_without_the_checksum_check_the_edited_row_is_served(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: a reader that trusts every row serves the edited one."""
    monkeypatch.setattr(reader, "_untrusted", lambda row, spec: False)
    with pytest.raises(TamperedServed, match="served 179 bars, expected 178"):
        check_edited_row_withheld(stores, monkeypatch)


F9: Final = "#452 F9 (P2, owned row): a withheld row is a silent gap; no field of the page names it"


class SilentGap(AssertionError):
    """The page withholds a bar and tells the client nothing of it."""


@pytest.mark.xfail(strict=True, raises=SilentGap, reason=F9)
def test_integrity_withheld_bar_is_named_to_the_client(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#452 F9 (new in PR-2): the edited row is withheld and counted, but the 200 carries no sign
    of it (`meta` is the page's count, cursor, sources and times), so a chart draws a bar-wide gap
    that reads as no trading. This pins `meta.coverage_holes` (22 `DataMeta`, the contract's gap
    list); a fix using another field updates this check."""
    rows = {k: list(v) for k, v in mw.stored_rows().items()}
    edited = rows["1m"][7] = {**rows["1m"][7], "close": 1.0}
    monkeypatch.setattr(mw, "stored_rows", lambda: rows)
    query = {"symbol": SYMBOL, "bar_type": "time", "param": "1", "limit": 5000,
             "from": _iso(mw.T0), "to": _iso(mw.NOW)}  # fmt: skip
    before = _mismatches()
    resp = stores.get("getBars", query)
    assert resp.status_code == 200, resp.text[:300]
    assert edited["index"] not in {b["index"] for b in resp.json()["bars"]}
    assert _mismatches() == before + 1
    meta = resp.json()["meta"]
    at = ts_us_from_row(edited["ts"])
    holes = meta.get("coverage_holes") or []
    if not any(h["start_us"] <= at < h["end_us"] for h in holes):
        raise SilentGap(f"meta names no withheld bar: {sorted(meta)}")
