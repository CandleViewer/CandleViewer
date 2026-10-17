"""E12-T06 D2 (#2195, #399): the `bars` snapshot source, `23-ws-protocol.md` §3.4, §6.1, §14.3."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.bars.series_store import SeriesStore
from candleviewer.ws.bars_source import BarsSnapshotSource, Seed
from candleviewer.ws.binary import BARS, decode_b64
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody, TopicEmitter
from candleviewer.ws.topics import effective_options, parse_topic
from tests.contract.ws._harness import check_schema
from tests.unit.ws._seq_support import validate

SPEC = BarSpec(kind="time", interval_ms=300_000)
SYM, CH, H = "BTCUSDT", "bars.BTCUSDT.time.5", SPEC.spec_hash
SCHEMA = "cv://ws/v1/bars.schema.json"
RS = "bb000000-0000-4000-8000-000000000001"
T0, STEP, GEN = 1_700_000_000_000_000, 300_000_000, 7
KEYS = ("generation", "index", "t_ms", "trades", "confirm")


def _bar(i: int, *, closed: bool = True, px: str = "100.5") -> Bar:
    p = Decimal(px) + i
    return Bar.model_construct(
        spec_hash=H, symbol=SYM, index=i, open_time=T0 + i * STEP,
        close_time=T0 + (i + 1) * STEP - 1, open=p, high=p + 1, low=p - 1, close=p,
        volume=Decimal("2.5"), buy_volume=Decimal("1"), sell_volume=Decimal("1.5"),
        delta=Decimal("-0.5"), min_delta=Decimal("-1"), max_delta=Decimal("0.5"), trade_count=3,
        turnover=Decimal("251.25"), vwap=p, closed=closed, partial=False, gap_before=False,
    )  # fmt: skip


def _up(kind: str, i: int, px: str = "100.5") -> BarUpdate:
    return BarUpdate.model_construct(kind=kind, bar=_bar(i, closed=kind == "close", px=px))


async def _store(closes: int = 0, *, forming: bool = True, px: str = "100.5") -> SeriesStore:
    """A held series: `closes` closed bars, then the forming bar (when `forming`)."""
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    ups = [_up("close", i, px) for i in range(closes)] + [_up("open", closes, px)] * forming
    await store.emit(BarEmission(SPEC, GEN, ups))  # no updates: no generation is named
    return store


def _sub(ch: str = CH, *, rs: str | None = None, **opts: Any) -> Subscription:
    topic = parse_topic(ch)
    return Subscription("s_01", topic, opts, effective_options(topic, opts), replay_session_id=rs)


def _src(
    store: SeriesStore, scales: tuple[int, int] | None = (1, 3), seed: Seed | None = None
) -> BarsSnapshotSource:
    return BarsSnapshotSource(store, lambda s: scales if s == SYM else None, seed=seed)


def _build(src: BarsSnapshotSource, sub: Subscription) -> SnapshotBody:
    body = src.build(sub)
    assert body is not None
    return body


@pytest.mark.parametrize(
    ("opts", "want"),
    [({}, [0, 1, 2, 3]), ({"history": 3}, [1, 2, 3]), ({"history": 1}, [3]), ({"history": 0}, [])],
)
async def test_build_sends_the_newest_history_bars_oldest_first_and_the_forming_bar_last(
    opts: dict[str, Any], want: list[int]
) -> None:
    body = _build(_src(await _store(3)), _sub(encoding="structured", **opts))
    check_schema(SCHEMA, body.structured, "bars snapshot")
    bars = body.structured["bars"]
    assert [(b["generation"], b["index"]) for b in bars] == [(GEN, i) for i in want]
    assert [b["confirm"] for b in bars] == [i < 3 for i in want]  # the forming bar is last
    assert body.parts == ()  # a structured subscription gets no kind-4 form built


async def test_build_version_is_the_lowest_build_among_the_bars_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.1: bar 0 was built by build 2 under a running build 3; a snapshot without it is 3."""
    monkeypatch.setitem(BUILD_VERSIONS, "time", 3)

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(GEN, _bar(i)) for i in range(3)], builds={(GEN, 0, T0): 2})

    store = SeriesStore(tail)
    await store.ensure(SYM, SPEC)
    src = _src(store)
    assert _build(src, _sub(history=3)).meta["build_version"] == 2
    assert _build(src, _sub(history=2)).meta["build_version"] == 3


async def test_an_empty_series_sends_no_bars_with_the_running_build_in_either_encoding() -> None:
    seeds: list[tuple[str, BarSpec, int]] = []
    src = _src(await _store(forming=False), seed=lambda *a: seeds.append(a))
    plain, binary = _build(src, _sub(encoding="structured")), _build(src, _sub(encoding="binary"))
    assert (plain.structured["bars"], plain.meta["build_version"]) == ([], 1)
    (part,) = binary.parts  # kind 4 still: one empty frame, not the structured fallback
    assert (part.body_kind, part.records, binary.meta["build_version"]) == (BARS, (), 1)
    assert seeds == []  # nothing named a generation yet: no baseline to seed


@pytest.mark.parametrize("include_delta", [False, True])
async def test_both_encodings_validate_and_carry_the_meta_and_the_same_bars_at_covering_scales(
    include_delta: bool,
) -> None:
    """`100.25` is finer than the instrument's price scale 1: the frame takes scale 2."""
    src = _src(await _store(2, px="100.25"))
    out: list[dict[str, Any]] = []
    emitter = TopicEmitter(
        out.append, connection_id="c", wall_ms=lambda: 1, clock=lambda: 0.0, source=src
    )
    for encoding in ("structured", "binary"):
        assert emitter.snapshot(_sub(encoding=encoding, include_delta=include_delta), "initial")
    owner = {"spec_hash": H, "build_version": 1, "include_delta": include_delta}
    for frame in out:
        validate(frame)
        assert frame["meta"] == {"reason": "initial", "source": "live", **owner}
    want, part = out[0]["p"]["bars"], decode_b64(out[1]["p"])
    assert all(("delta" in b) is include_delta for b in want)
    got = structured(part)["bars"]
    assert (part.price_scale, part.qty_scale, len(got)) == (2, 3, 3)
    for item, dec in zip(want, got, strict=True):
        assert {k: dec[k] for k in KEYS} == {k: item[k] for k in KEYS}
        for k in ("o", "h", "l", "c", "v", "turnover"):
            assert Decimal(dec[k]) == Decimal(item[k]), k
        assert Decimal(dec["delta"]) == Decimal(item.get("delta", 0))


@pytest.mark.parametrize(("px", "scales"), [("100.5", None), ("1E+18", (1, 3))],
                         ids=["no-scales", "outside-i64"])  # fmt: skip
async def test_the_whole_snapshot_goes_structured_when_kind_4_cannot_carry_it(
    px: str, scales: tuple[int, int] | None
) -> None:
    """§3.4's trigger: no instrument scales, or a value outside its 64-bit field."""
    store = await _store(2, px=px)
    with capture_logs() as logs:
        body = _build(_src(store, scales), _sub(encoding="binary"))
    assert body.parts == () and len(body.structured["bars"]) == 3
    check_schema(SCHEMA, body.structured, "bars snapshot")
    assert [e["event"] for e in logs] == ["ws_bars_snapshot_structured"]


async def test_a_bar_neither_form_can_carry_keeps_the_subscription_pending() -> None:
    store = await _store(1, px="NaN")
    with capture_logs() as logs:
        assert _src(store).build(_sub(encoding="structured")) is None
    assert [(e["event"], e["log_level"]) for e in logs] == [("ws_bars_snapshot_refused", "error")]


async def test_generation_is_the_store_version_and_continuity_is_always_false() -> None:
    store = await _store(1)
    src, sub = _src(store), _sub()
    before = src.generation(sub)
    await store.emit(BarEmission(SPEC, GEN, [_up("update", 1)]))
    assert src.generation(sub) == store.version(SYM, H) > before > 0
    assert src.continuity(sub, 0) is False and src.continuity(sub, None) is False


@pytest.mark.parametrize(("ch", "rs"), [(CH, RS), ("bars.ETHUSDT.time.5", None),
                                        ("bars.BTCUSDT.renko.atr:14", None)])  # fmt: skip
async def test_a_replay_unheld_or_unbuildable_series_builds_none(ch: str, rs: str | None) -> None:
    """The live store is no replay state; a series it does not keep has nothing to send."""
    src = _src(await _store(1))
    assert src.build(_sub(ch, rs=rs)) is None and src.generation(_sub(ch, rs=rs)) == 0


async def test_each_build_seeds_the_publisher_with_the_generation_it_sent() -> None:
    seeds: list[tuple[str, BarSpec, int]] = []
    _build(_src(await _store(1), seed=lambda *a: seeds.append(a)), _sub())
    assert seeds == [(SYM, SPEC, GEN)]
