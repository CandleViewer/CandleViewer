"""E40-T03 DoD (#1866): a recorded Bybit tape replayed through `AlertEvaluator` twice.

Both replays must give identical deliveries and an identical store end state.

Input is the live-captured, redacted `ws/recorded_publicTrade_BTCUSDT.jsonl` of the shared corpus
(`packages/fixtures/bybit/2026-10-05`, C-13.5), parsed by the production trade parser via
`tests._corpus.normalize`. The fake clock follows the prints' exchange timestamps; no sleeps, no
network, no wall clock. Every print feeds the price metric and sends an `on_price_update` tick plus
a synthetic `on_bar_close` tick. The per-print bar tick is a determinism probe, not production bar
semantics: production sends `on_bar_close` once per closed bar via `AlertService.submit_tick`.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from candleviewer.alerts.evaluator import AlertTick
from candleviewer.exchange.base.trade_print import TradePrint
from tests._corpus import frames, normalize
from tests.alerts._evaluator_env import ir, make, row

FIXTURE = "ws/recorded_publicTrade_BTCUSDT.jsonl"  # prices 82745.80 .. 82751.20, ~10 s


def _prints() -> list[TradePrint]:
    out: list[TradePrint] = []
    for frame in frames(FIXTURE):
        out.extend(e for e in normalize(frame) if isinstance(e, TradePrint))
    for prev, cur in pairwise(out):
        assert cur.ts_event_us >= prev.ts_event_us, "recorded tape must be time-ordered"
    return out


def _alerts(gt_threshold: int = 82750) -> list[Any]:
    return [
        # every_time with a 2 s cooldown: re-arms on the recorded tape's quiet gaps.
        row("a-gt", condition_ir=ir("gt", gt_threshold), cooldown_seconds=2),
        # once: a crossing that the tape makes exactly once (82745.x up through 82748).
        row("a-cross", condition_ir=ir("crosses_above", 82748), trigger_mode="once"),
        # once per 1m bar: fed a synthetic per-print `on_bar_close` tick (determinism probe, not
        # production bar semantics); the tape never leaves its bar, so one delivery.
        row(
            "a-bar",
            trigger_mode="once_per_bar",
            condition_ir=ir("gt", 82745, trigger="on_bar_close", timeframe="1m"),
        ),
        # must NOT fire: the tape never gets near these levels.
        row("a-never-gt", condition_ir=ir("gt", 90000)),
        row("a-never-below", condition_ir=ir("crosses_below", 82700)),
    ]


async def _replay(
    prints: list[TradePrint], gt_threshold: int = 82750
) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    ev, store, src, clock, _ = make(*_alerts(gt_threshold))
    await ev.warm_up()
    for p in prints:
        ts = p.ts_event_us // 1000
        clock.now = ts
        src.set("price", str(p.price), ts)
        await ev.process(AlertTick("on_price_update", ts, p.symbol))
        await ev.process(AlertTick("on_bar_close", ts, p.symbol))
    deliveries = [
        (
            d.id,
            d.alert_id,
            d.user_id,
            d.channel,
            d.status,
            d.title,
            tuple(sorted(d.context.items(), key=lambda kv: kv[0])),
        )
        for d in store.deliveries
    ]
    state = {
        "rows": dict(store.rows),  # enabled / last_fired_at / last_bar_open_ms per alert
        "outbox": list(store.outbox),
        "fire_count": dict(store.fire_count),
        "armed": sorted(ev.alerts),
    }
    return deliveries, state


EXPECTED: list[tuple[str, str, int, str]] = [
    ("a-bar", "on_bar_close", 1792391736831, "82745.80"),
    ("a-cross", "on_price_update", 1792391738137, "82748.40"),
    ("a-gt", "on_price_update", 1792391739725, "82750.80"),
    ("a-gt", "on_price_update", 1792391741793, "82751.20"),
    ("a-gt", "on_price_update", 1792391746172, "82751.20"),
]


async def test_alert_evaluator_recorded_tape_replayed_twice_gives_identical_deliveries() -> None:
    prints = _prints()
    first, first_state = await _replay(prints)
    second, second_state = await _replay(prints)
    assert first, "vacuous: the recorded tape must fire at least one alert"
    assert first == second
    assert first_state["outbox"], "vacuous: nothing was queued"
    assert first_state == second_state


async def test_alert_evaluator_recorded_tape_matches_committed_expectation() -> None:
    prints = _prints()
    # Manifest entry: capture 2026-10-19, 20 frames, which hold these 46 prints.
    assert len(prints) == 46
    got, state = await _replay(prints)
    assert [(d[1], dict(d[6])["trigger_type"], dict(d[6])["event_ts_ms"],
             dict(d[6])["values"]["price"]) for d in got] == EXPECTED  # fmt: skip
    assert [d[0] for d in got] == [1, 2, 3, 4, 5]
    assert all((d[2], d[3], d[4]) == ("u1", "in_app", "queued") for d in got)
    assert dict(got[0][6])["bar_open_ms"] == 1792391700000
    assert dict(got[2][6])["bar_open_ms"] is None
    assert not {"a-never-gt", "a-never-below"} & {d[1] for d in got}
    assert state["rows"]["a-cross"].enabled is False  # `once` disarmed itself
    assert state["rows"]["a-gt"].last_fired_at is not None
    assert state["armed"] == ["a-bar", "a-gt", "a-never-below", "a-never-gt"]


async def test_alert_evaluator_recorded_tape_replay_detects_a_changed_alert() -> None:
    """Guard against a vacuous comparison: a perturbed threshold must change the deliveries."""
    prints = _prints()
    assert (await _replay(prints, gt_threshold=82751))[0] != (await _replay(prints))[0]
